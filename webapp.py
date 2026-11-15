"""Entrada WSGI de la demo pública. Reutiliza las reglas y SQLite de app.py."""
import argparse
import json
import re
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from app import ROOT, STATUSES, Store, scenario

SESSION_SECONDS = 24 * 60 * 60
MAX_SESSIONS = 128
MAX_SESSION_EVENTS = 384
MAX_READS_PER_MINUTE = 120
MAX_WRITES_PER_MINUTE = 20
MAX_NEW_SESSIONS_PER_MINUTE = 10
MAX_BODY = 16384
ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8")}
STATUS_TEXT = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized",
               403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
               409: "Conflict", 413: "Content Too Large", 415: "Unsupported Media Type",
               429: "Too Many Requests", 500: "Internal Server Error", 503: "Service Unavailable"}


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class DemoApplication:
    def __init__(self, origin, data_dir, allow_local_http=False, clock=time.time):
        parsed = urlsplit(origin)
        local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        if (parsed.scheme != "https" and not (allow_local_http and local)) or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("El origen debe ser una URL HTTPS sin ruta, por ejemplo https://cuenta.alwaysdata.net")
        if not Path(data_dir).is_absolute():
            raise ValueError("La carpeta de datos debe ser una ruta absoluta.")
        self.origin = origin
        self.host = parsed.netloc
        self.secure = parsed.scheme == "https"
        self.cookie_name = "__Host-vigia" if self.secure else "vigia-preview"
        self.clock = clock
        self.data_dir = Path(data_dir)
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.registry_path = self.data_dir / "registry.sqlite3"
        with closing(self.registry()) as registry:
            registry.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires INTEGER NOT NULL,
                    read_window INTEGER NOT NULL, reads INTEGER NOT NULL,
                    write_window INTEGER NOT NULL, writes INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admission (
                    id INTEGER PRIMARY KEY CHECK(id=1), window INTEGER NOT NULL, count INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO admission VALUES (1, 0, 0);
            """)
        self.registry_path.chmod(0o600)

    def registry(self):
        connection = sqlite3.connect(str(self.registry_path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def database_path(self, session_id):
        if not ID_PATTERN.fullmatch(session_id):
            raise ValueError("Identificador de sesión inválido.")
        return self.sessions_dir / (session_id + ".sqlite3")

    @contextmanager
    def request_registry(self):
        with closing(self.registry()) as registry:
            registry.execute("BEGIN IMMEDIATE")
            try:
                yield registry
            except sqlite3.Error:
                registry.rollback()
                raise
            except Exception:
                # Las peticiones inválidas también consumen su cuota de intentos.
                registry.commit()
                raise
            else:
                registry.commit()

    def cookie_session(self, environ):
        try:
            cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
            value = cookies[self.cookie_name].value if self.cookie_name in cookies else ""
            return value if ID_PATTERN.fullmatch(value) else None
        except CookieError:
            return None

    def cleanup(self, registry, now):
        # Todas las operaciones de sesión toman BEGIN IMMEDIATE en el registro.
        # Esto también serializa la limpieza entre varios procesos WSGI.
        expired = registry.execute("SELECT id FROM sessions WHERE expires<=?", (now,)).fetchall()
        for row in expired:
            path = self.database_path(row["id"])
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(str(path) + suffix)
                candidate.unlink(missing_ok=True)
        registry.execute("DELETE FROM sessions WHERE expires<=?", (now,))

    def get_session(self, registry, environ, create=False):
        now = int(self.clock())
        session_id = self.cookie_session(environ)
        row = registry.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (session_id, now)).fetchone()
        if row:
            return row, None
        if not create:
            raise APIError(401, "La sesión caducó. Recarga el panel para comenzar otra demo.")
        self.cleanup(registry, now)
        if registry.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= MAX_SESSIONS:
            raise APIError(503, "El laboratorio alcanzó su capacidad temporal. Intenta más tarde.")
        window = now // 60
        admission = registry.execute("SELECT * FROM admission WHERE id=1").fetchone()
        count = admission["count"] if admission["window"] == window else 0
        if count >= MAX_NEW_SESSIONS_PER_MINUTE:
            raise APIError(429, "Se están abriendo muchas sesiones. Intenta nuevamente en un minuto.")
        registry.execute("UPDATE admission SET window=?, count=? WHERE id=1", (window, count + 1))
        session_id = secrets.token_hex(32)
        registry.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", (
            session_id, secrets.token_hex(32), now + SESSION_SECONDS, window, 0, window, 0))
        row = registry.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        cookie = "%s=%s; Path=/; Max-Age=%s; HttpOnly; SameSite=Lax" % (self.cookie_name, session_id, SESSION_SECONDS)
        if self.secure:
            cookie += "; Secure"
        return row, cookie

    def limit(self, registry, session, mutation):
        window = int(self.clock()) // 60
        prefix, maximum = ("write", MAX_WRITES_PER_MINUTE) if mutation else ("read", MAX_READS_PER_MINUTE)
        field = "writes" if mutation else "reads"
        count = session[field] if session[prefix + "_window"] == window else 0
        if count >= maximum:
            raise APIError(429, "Demasiadas acciones en esta sesión. Intenta nuevamente en un minuto.")
        # Los nombres de columna vienen exclusivamente de las constantes anteriores.
        registry.execute("UPDATE sessions SET %s=?, %s_window=? WHERE id=?" % (field, prefix),
                         (count + 1, window, session["id"]))

    def response(self, start_response, status, body, content_type="application/json; charset=utf-8", cookie=None):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        headers = [("Content-Type", content_type), ("Content-Length", str(len(payload))),
                   ("Cache-Control", "no-store"), ("Vary", "Cookie"),
                   ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                   ("Referrer-Policy", "no-referrer"), ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
                   ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
        if self.secure:
            headers.append(("Strict-Transport-Security", "max-age=31536000"))
        if cookie:
            headers.append(("Set-Cookie", cookie))
        if status in (429, 503):
            headers.append(("Retry-After", "60"))
        start_response("%s %s" % (status, STATUS_TEXT[status]), headers)
        return [payload]

    def read_json(self, environ):
        try:
            size = int(environ.get("CONTENT_LENGTH", "0"))
        except ValueError:
            raise APIError(400, "Content-Length inválido.")
        if size < 1 or size > MAX_BODY:
            raise APIError(413, "El cuerpo debe tener entre 1 y 16384 bytes.")
        if environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower() != "application/json":
            raise APIError(415, "Se requiere application/json.")
        raw = environ["wsgi.input"].read(size)
        if len(raw) != size:
            raise APIError(400, "Cuerpo incompleto.")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise APIError(400, "Se requiere un objeto JSON.")
        return data

    def __call__(self, environ, start_response):
        cookie = None
        try:
            if environ.get("HTTP_HOST") != self.host:
                raise APIError(403, "Host no permitido.")
            method = environ.get("REQUEST_METHOD", "GET")
            path = environ.get("PATH_INFO", "/")
            if path == "/api/events":
                raise APIError(403, "La ingesta externa está deshabilitada en la demo pública.")
            routes = {"/api/bootstrap": "GET", "/api/state": "GET", "/api/export": "GET",
                      "/api/simulate": "POST", "/api/alerts/update": "POST", "/api/reset": "POST",
                      "/health": "GET", **{p: "GET" for p in STATIC_FILES}}
            if path not in routes:
                raise APIError(404, "Recurso no encontrado.")
            if method != routes[path]:
                raise APIError(405, "Método no permitido.")
            if path == "/health":
                return self.response(start_response, 200, {"status": "ok", "mode": "public_demo"})
            if path in STATIC_FILES:
                name, mime = STATIC_FILES[path]
                return self.response(start_response, 200, (ROOT / "static" / name).read_bytes(), mime)
            if environ.get("HTTP_SEC_FETCH_SITE") == "cross-site":
                raise APIError(403, "Solicitud de otro sitio no permitida.")
            mutation = method == "POST"
            if mutation and environ.get("HTTP_ORIGIN") != self.origin:
                raise APIError(403, "Origen no permitido.")
            with self.request_registry() as registry:
                session, cookie = self.get_session(registry, environ, create=path == "/api/bootstrap")
                if mutation and not secrets.compare_digest(environ.get("HTTP_X_PANEL_TOKEN", "").encode(), session["csrf"].encode()):
                    raise APIError(403, "Credencial de sesión inválida.")
                self.limit(registry, session, mutation)
                if path == "/api/bootstrap":
                    result = {"panel_token": session["csrf"], "mode": "public_demo", "retention_hours": 24,
                              "max_events": MAX_SESSION_EVENTS}
                    status = 200
                else:
                    store = Store(self.database_path(session["id"]))
                    try:
                        if not mutation:
                            status, result = 200, store.snapshot()
                        else:
                            data = self.read_json(environ)
                            if path == "/api/simulate":
                                items = scenario(data.get("scenario"))
                                count = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                                if count + len(items) > MAX_SESSION_EVENTS:
                                    raise APIError(409, "Alcanzaste el límite de eventos. Exporta tus datos y reinicia tu demo.")
                                result, status = {"inserted": store.ingest(items)}, 201
                            elif path == "/api/reset":
                                with store.db:
                                    for table in ("events", "alerts", "investigations"):
                                        store.db.execute("DELETE FROM " + table)
                                result, status = {"reset": True}, 200
                            else:
                                if not isinstance(data.get("id"), str) or data.get("status") not in STATUSES:
                                    raise APIError(400, "Investigación inválida.")
                                store.update(data["id"], data["status"], data.get("note", ""))
                                result, status = {"saved": True}, 200
                    finally:
                        store.db.close()
            return self.response(start_response, status, result, cookie=cookie)
        except APIError as error:
            return self.response(start_response, error.status, {"error": error.message})
        except (ValueError, TypeError, OverflowError, RecursionError):
            return self.response(start_response, 400, {"error": "Datos inválidos. Revisa los campos y límites de la demo."})
        except sqlite3.OperationalError:
            return self.response(start_response, 503, {"error": "El laboratorio está ocupado. Intenta nuevamente en unos momentos."})
        except (sqlite3.Error, OSError):
            return self.response(start_response, 500, {"error": "No se pudo completar la operación."})


def main():
    from wsgiref.simple_server import make_server
    parser = argparse.ArgumentParser(description="Previsualización local de la entrada WSGI pública.")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "preview-public")
    args = parser.parse_args()
    origin = "http://127.0.0.1:%s" % args.port
    application = DemoApplication(origin, args.data_dir.resolve(), allow_local_http=True)
    with make_server("127.0.0.1", args.port, application) as server:
        print("Demo WSGI local: " + origin, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
