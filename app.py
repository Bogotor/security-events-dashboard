"""Panel local de eventos de seguridad. Solo requiere Python 3.9+."""
import argparse
import ipaddress
import json
import os
import secrets
import sqlite3
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc
EVENT_TYPES = {"login_failed", "login_success", "role_changed"}
STATUSES = {"pending", "investigating", "resolved"}
WINDOW = timedelta(minutes=5)
MAX_EVENTS = 5000


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("occurred_at debe ser una fecha ISO 8601 con zona horaria.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("occurred_at debe ser una fecha ISO 8601 válida.")
    if result.tzinfo is None:
        raise ValueError("occurred_at debe incluir zona horaria.")
    return result.astimezone(UTC)


def validate_event(data):
    if not isinstance(data, dict):
        raise ValueError("El evento debe ser un objeto JSON.")
    allowed = {"event_id", "occurred_at", "type", "user", "source_ip", "metadata"}
    if set(data) - allowed:
        raise ValueError("El evento contiene campos no permitidos.")
    result = dict(data)
    for key in ("event_id", "user"):
        value = result.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value):
            raise ValueError(key + " debe contener entre 1 y 100 caracteres sin controles.")
    if not isinstance(result.get("type"), str) or result["type"] not in EVENT_TYPES:
        raise ValueError("Tipo de evento no reconocido.")
    occurred = parse_time(result.get("occurred_at"))
    if occurred > datetime.now(UTC) + WINDOW:
        raise ValueError("La fecha del evento está demasiado adelantada.")
    result["occurred_at"] = iso(occurred)
    try:
        result["source_ip"] = str(ipaddress.ip_address(result.get("source_ip", "")))
    except ValueError:
        raise ValueError("source_ip debe ser una dirección IP válida.")
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict) or set(metadata) - {"old_role", "new_role"}:
        raise ValueError("metadata solo admite old_role y new_role; no envíes secretos.")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 60 or any(ord(c) < 32 for c in v) for v in metadata.values()):
        raise ValueError("Los roles deben ser textos de hasta 60 caracteres sin controles.")
    if result["type"] == "role_changed" and (set(metadata) != {"old_role", "new_role"} or metadata["old_role"] == metadata["new_role"]):
        raise ValueError("Un cambio de rol necesita old_role y new_role diferentes.")
    result["metadata"] = metadata
    return result


def detect(events):
    """Recalcula por tiempo del evento para admitir recepción fuera de orden."""
    failures = defaultdict(deque)
    last_failure_alert = {}
    alerts = []
    for event in sorted(events, key=lambda e: (e["occurred_at"], e["event_id"])):
        stamp = parse_time(event["occurred_at"])
        user = event["user"]
        recent = failures[user]
        while recent and stamp - parse_time(recent[0]["occurred_at"]) > WINDOW:
            recent.popleft()

        def add(rule, title, severity, evidence, explanation):
            alerts.append({"id": rule + ":" + event["event_id"], "rule": rule,
                           "title": title, "severity": severity, "user": user,
                           "occurred_at": event["occurred_at"], "explanation": explanation,
                           "evidence": [item["event_id"] for item in evidence]})

        if event["type"] == "login_failed":
            recent.append(event)
            last = last_failure_alert.get(user)
            if len(recent) >= 5 and (last is None or stamp - last > WINDOW):
                add("repeated_failures", "Intentos de acceso repetidos", "medium", list(recent),
                    "Se registraron al menos cinco accesos fallidos para la misma cuenta en cinco minutos. Revisa si son errores legítimos o un intento de adivinación de contraseña.")
                last_failure_alert[user] = stamp
        elif event["type"] == "login_success":
            if len(recent) >= 5:
                add("success_after_failures", "Acceso después de múltiples fallos", "high", list(recent) + [event],
                    "Hubo un acceso exitoso tras al menos cinco fallos en cinco minutos. Comprueba con la persona si reconoce el acceso; esta secuencia por sí sola no confirma una intrusión.")
            recent.clear()
            last_failure_alert.pop(user, None)
        else:
            add("role_changed", "Cambio de permisos", "medium", [event],
                "Se modificó el rol de una cuenta. Verifica que exista una solicitud aprobada y que los privilegios correspondan a sus funciones.")
    return alerts


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, type TEXT NOT NULL,
                user TEXT NOT NULL, source_ip TEXT NOT NULL, metadata TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investigations (
                alert_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

    def events(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY occurred_at, event_id").fetchall()
            return [dict(row, metadata=json.loads(row["metadata"])) for row in rows]

    def ingest(self, items):
        checked = [validate_event(item) for item in items]
        with self.lock, self.db:
            inserted = 0
            for item in checked:
                old = self.db.execute("SELECT * FROM events WHERE event_id=?", (item["event_id"],)).fetchone()
                if old:
                    previous = dict(old, metadata=json.loads(old["metadata"]))
                    if previous != item:
                        raise ValueError("event_id ya existe con un contenido diferente.")
                    continue
                if self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= MAX_EVENTS:
                    raise ValueError("Límite local de 5000 eventos alcanzado. Exporta los datos antes de iniciar otra base.")
                self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (
                    item["event_id"], item["occurred_at"], item["type"], item["user"],
                    item["source_ip"], json.dumps(item["metadata"], ensure_ascii=False)))
                inserted += 1
            if inserted:
                self.db.execute("DELETE FROM alerts")
                self.db.executemany("INSERT INTO alerts VALUES (?,?)", [
                    (a["id"], json.dumps(a, ensure_ascii=False)) for a in detect(self.events())])
            return inserted

    def snapshot(self):
        with self.lock:
            events = self.events()
            investigations = {r["alert_id"]: dict(r) for r in self.db.execute("SELECT * FROM investigations")}
            alerts = []
            for row in self.db.execute("SELECT payload FROM alerts"):
                alert = json.loads(row["payload"])
                review = investigations.get(alert["id"], {})
                alert.update(status=review.get("status", "pending"), note=review.get("note", ""), updated_at=review.get("updated_at"))
                alerts.append(alert)
            alerts.sort(key=lambda a: (a["occurred_at"], a["id"]), reverse=True)
            return {"events": list(reversed(events)), "alerts": alerts}

    def update(self, alert_id, status, note):
        if not isinstance(status, str) or status not in STATUSES or not isinstance(note, str) or len(note) > 2000:
            raise ValueError("Estado inválido o nota superior a 2000 caracteres.")
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM alerts WHERE id=?", (alert_id,)).fetchone():
                raise ValueError("La alerta ya no existe. Actualiza el panel.")
            self.db.execute("INSERT OR REPLACE INTO investigations VALUES (?,?,?,?)",
                            (alert_id, status, note, iso(datetime.now(UTC))))


def scenario(name):
    now = datetime.now(UTC)
    prefix = uuid.uuid4().hex[:8]
    user = ("operador" if name == "role" else "camila" if name == "suspicious" else "diego") + "." + prefix + "@demo.test"

    def event(kind, seconds, metadata=None):
        return {"event_id": str(uuid.uuid4()), "occurred_at": iso(now + timedelta(seconds=seconds)),
                "type": kind, "user": user, "source_ip": "203.0.113.42" if name == "suspicious" else "192.0.2.18",
                "metadata": metadata or {}}

    if name == "suspicious":
        return [event("login_failed", -150 + n * 25) for n in range(5)] + [event("login_success", 0)]
    if name == "role":
        return [event("role_changed", 0, {"old_role": "viewer", "new_role": "admin"})]
    if name == "normal":
        return [event("login_failed", -45), event("login_success", 0)]
    raise ValueError("Escenario desconocido.")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, ingest_token):
        super().__init__(address, Handler)
        self.store = store
        self.ingest_token = ingest_token
        self.panel_token = secrets.token_urlsafe(32)


class Handler(BaseHTTPRequestHandler):
    server_version = "SecurityPanel"

    def log_message(self, format, *args):
        # Nunca registrar cuerpos, cabeceras de autorización ni rutas aportadas por el cliente.
        pass

    def respond(self, status, body, content_type="application/json; charset=utf-8"):
        payload = json.dumps(body, ensure_ascii=False).encode() if not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {"127.0.0.1:" + str(port), "localhost:" + str(port)}

    def do_GET(self):
        if not self.valid_host():
            return self.respond(403, {"error": "Host no permitido."})
        if self.path == "/api/state":
            return self.respond(200, self.server.store.snapshot())
        if self.path == "/api/bootstrap":
            return self.respond(200, {"panel_token": self.server.panel_token})
        if self.path == "/api/export":
            return self.respond(200, self.server.store.snapshot())
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path in files:
            name, mime = files[self.path]
            return self.respond(200, (ROOT / "static" / name).read_bytes(), mime)
        return self.respond(404, {"error": "Recurso no encontrado."})

    def do_POST(self):
        if not self.valid_host():
            return self.respond(403, {"error": "Host no permitido."})
        if self.path == "/api/events":
            authorized = secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.ingest_token)
        else:
            origin = self.headers.get("Origin")
            expected = "http://" + self.headers.get("Host", "")
            authorized = origin == expected and secrets.compare_digest(self.headers.get("X-Panel-Token", ""), self.server.panel_token)
        if not authorized:
            return self.respond(403, {"error": "Solicitud no autorizada."})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 16384:
                return self.respond(413, {"error": "El cuerpo debe tener entre 1 y 16384 bytes."})
            if self.headers.get_content_type() != "application/json":
                return self.respond(415, {"error": "Se requiere application/json."})
            self.connection.settimeout(5)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Se requiere un objeto JSON.")
            if self.path == "/api/events":
                inserted = self.server.store.ingest([data])
                return self.respond(201 if inserted else 200, {"inserted": inserted})
            if self.path == "/api/simulate":
                name = data.get("scenario")
                if not isinstance(name, str):
                    raise ValueError("Escenario inválido.")
                inserted = self.server.store.ingest(scenario(name))
                return self.respond(201, {"inserted": inserted})
            if self.path == "/api/alerts/update":
                alert_id = data.get("id")
                if not isinstance(alert_id, str):
                    raise ValueError("Identificador inválido.")
                self.server.store.update(alert_id, data.get("status"), data.get("note", ""))
                return self.respond(200, {"saved": True})
            return self.respond(404, {"error": "Recurso no encontrado."})
        except (ValueError, TypeError, OverflowError):
            return self.respond(400, {"error": "Datos inválidos. Revisa el esquema y los límites documentados."})
        except (TimeoutError, OSError):
            return self.respond(408, {"error": "Tiempo de recepción agotado."})
        except sqlite3.Error:
            return self.respond(500, {"error": "No se pudo guardar la operación."})


def main():
    parser = argparse.ArgumentParser(description="Panel de seguridad local, sin dependencias externas.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_path = args.data_dir / "ingest.token"
    if not token_path.exists():
        descriptor = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(secrets.token_urlsafe(32))
    token = token_path.read_text().strip()
    if len(token) < 32:
        parser.error("La credencial local de ingesta no es válida.")
    store = Store(args.data_dir / "events.sqlite3")
    server = Server(("127.0.0.1", args.port), store, token)
    print("Panel local: http://127.0.0.1:%s" % server.server_port, flush=True)
    print("Solo escucha en tu computador. Credencial de ingesta en: %s" % token_path, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.db.close()


if __name__ == "__main__":
    main()
