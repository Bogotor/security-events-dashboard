import io
import json
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

from app import Store, scenario
from webapp import DemoApplication, MAX_SESSION_EVENTS, MAX_WRITES_PER_MINUTE, SESSION_SECONDS


class Client:
    def __init__(self, app):
        self.app = app
        self.cookie = ""
        self.token = ""

    def request(self, path, data=None, method=None, headers=None, raw=None):
        environ = {}
        setup_testing_defaults(environ)
        body = json.dumps(data).encode() if data is not None else b""
        if raw is not None:
            body = raw
        environ.update(HTTP_HOST="vigia.example.test", PATH_INFO=path, QUERY_STRING="", REQUEST_METHOD=method or ("POST" if data is not None or raw is not None else "GET"),
                       HTTP_COOKIE=self.cookie, HTTP_ORIGIN="https://vigia.example.test", HTTP_X_PANEL_TOKEN=self.token,
                       CONTENT_TYPE="application/json", CONTENT_LENGTH=str(len(body)))
        environ["wsgi.url_scheme"] = "https"
        environ["wsgi.input"] = io.BytesIO(body)
        environ.update(headers or {})
        response = {}

        def start_response(status, headers, exc_info=None):
            response["status"] = int(status.split()[0])
            response["headers"] = dict(headers)

        iterable = validator(self.app)(environ, start_response)
        try:
            content = b"".join(iterable)
        finally:
            if hasattr(iterable, "close"):
                iterable.close()
        if "Set-Cookie" in response["headers"]:
            cookies = SimpleCookie(response["headers"]["Set-Cookie"])
            self.cookie = "; ".join(key + "=" + value.value for key, value in cookies.items())
        response["body"] = json.loads(content) if "application/json" in response["headers"]["Content-Type"] else content
        return response

    def bootstrap(self):
        result = self.request("/api/bootstrap")
        if result["status"] == 200:
            self.token = result["body"]["panel_token"]
        return result


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1800000000
        self.app = DemoApplication("https://vigia.example.test", Path(self.directory.name), clock=lambda: self.now)
        self.a = Client(self.app)
        self.b = Client(self.app)

    def tearDown(self):
        self.directory.cleanup()

    def test_static_and_health_do_not_create_sessions_or_expose_files(self):
        self.assertEqual(self.a.request("/")["status"], 200)
        self.assertEqual(self.a.request("/health")["body"]["status"], "ok")
        self.assertEqual(self.a.cookie, "")
        for path in ("/wsgi.py", "/data/registry.sqlite3", "/../app.py"):
            self.assertEqual(self.a.request(path)["status"], 404)

    def test_bootstrap_sets_protected_cookie_and_public_metadata(self):
        result = self.a.bootstrap()
        self.assertEqual(result["body"]["mode"], "public_demo")
        cookie = result["headers"]["Set-Cookie"]
        for part in ("__Host-vigia=", "HttpOnly", "SameSite=Lax", "Secure", "Path=/", "Max-Age=86400"):
            self.assertIn(part, cookie)
        self.assertIn("max-age=", result["headers"]["Strict-Transport-Security"])
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")

    def test_anonymous_state_and_external_ingestion_are_rejected(self):
        self.assertEqual(self.a.request("/api/state")["status"], 401)
        self.a.bootstrap()
        self.assertEqual(self.a.request("/api/events", {}, headers={"HTTP_AUTHORIZATION": "Bearer anything"})["status"], 403)

    def test_visitors_have_separate_events_alerts_and_notes(self):
        self.a.bootstrap()
        self.b.bootstrap()
        self.a.request("/api/simulate", {"scenario": "suspicious"})
        mine = self.a.request("/api/state")["body"]
        other = self.b.request("/api/state")["body"]
        self.assertEqual(len(mine["events"]), 6)
        self.assertEqual(len(mine["alerts"]), 2)
        self.assertEqual(other, {"events": [], "alerts": []})
        alert_id = mine["alerts"][0]["id"]
        result = self.b.request("/api/alerts/update", {"id": alert_id, "status": "resolved", "note": "Ajena"})
        self.assertEqual(result["status"], 400)
        self.assertEqual(self.a.request("/api/state")["body"]["alerts"][0]["status"], "pending")

    def test_invalid_origin_host_and_other_visitors_csrf_are_rejected(self):
        self.a.bootstrap()
        self.b.bootstrap()
        for headers in ({"HTTP_ORIGIN": "https://attacker.test"}, {"HTTP_HOST": "attacker.test"},
                        {"HTTP_X_PANEL_TOKEN": self.b.token}, {"HTTP_X_PANEL_TOKEN": ""}):
            self.assertEqual(self.a.request("/api/simulate", {"scenario": "role"}, headers=headers)["status"], 403)
        self.assertEqual(self.a.request("/api/bootstrap", headers={"HTTP_SEC_FETCH_SITE": "cross-site"})["status"], 403)

    def test_session_persists_across_application_restart(self):
        self.a.bootstrap()
        self.a.request("/api/simulate", {"scenario": "role"})
        alert_id = self.a.request("/api/state")["body"]["alerts"][0]["id"]
        self.a.request("/api/alerts/update", {"id": alert_id, "status": "resolved", "note": "Solicitud verificada"})
        restarted = DemoApplication("https://vigia.example.test", Path(self.directory.name), clock=lambda: self.now)
        self.a.app = restarted
        result = self.a.request("/api/state")["body"]
        self.assertEqual(result["alerts"][0]["note"], "Solicitud verificada")
        self.assertEqual(result["alerts"][0]["status"], "resolved")

    def test_reset_only_clears_own_session(self):
        self.a.bootstrap()
        self.b.bootstrap()
        self.a.request("/api/simulate", {"scenario": "role"})
        self.b.request("/api/simulate", {"scenario": "normal"})
        self.assertEqual(self.a.request("/api/reset", {})["status"], 200)
        self.assertEqual(self.a.request("/api/state")["body"], {"events": [], "alerts": []})
        self.assertEqual(len(self.b.request("/api/state")["body"]["events"]), 2)

    def test_mutation_limit_persists_and_recovers_next_minute(self):
        self.a.bootstrap()
        for _ in range(MAX_WRITES_PER_MINUTE):
            self.assertEqual(self.a.request("/api/simulate", {"scenario": "normal"})["status"], 201)
        self.assertEqual(self.a.request("/api/reset", {})["status"], 429)
        self.now += 61
        self.assertEqual(self.a.request("/api/reset", {})["status"], 200)

    def test_invalid_mutations_also_consume_their_quota(self):
        self.a.bootstrap()
        for _ in range(MAX_WRITES_PER_MINUTE):
            self.assertEqual(self.a.request("/api/simulate", {"scenario": "unknown"})["status"], 400)
        self.assertEqual(self.a.request("/api/simulate", {"scenario": "role"})["status"], 429)

    def test_read_limit_is_independent_from_mutation_limit(self):
        self.a.bootstrap()
        with patch("webapp.MAX_READS_PER_MINUTE", 2):
            self.assertEqual(self.a.request("/api/state")["status"], 200)
            self.assertEqual(self.a.request("/api/state")["status"], 429)
            self.assertEqual(self.a.request("/api/simulate", {"scenario": "role"})["status"], 201)

    def test_expiry_removes_old_data_when_another_session_is_started(self):
        self.a.bootstrap()
        previous_cookie = self.a.cookie
        self.a.request("/api/simulate", {"scenario": "normal"})
        self.assertEqual(len(list(self.app.sessions_dir.glob("*.sqlite3"))), 1)
        self.now += SESSION_SECONDS + 1
        self.assertEqual(self.a.request("/api/state")["status"], 401)
        self.a.bootstrap()
        self.assertNotEqual(self.a.cookie, previous_cookie)
        self.assertEqual(len(list(self.app.sessions_dir.glob("*.sqlite3"))), 0)
        self.assertEqual(self.a.request("/api/state")["body"]["events"], [])

    def test_new_session_rate_and_total_capacity_are_bounded(self):
        with patch("webapp.MAX_NEW_SESSIONS_PER_MINUTE", 1):
            self.assertEqual(self.a.bootstrap()["status"], 200)
            self.assertEqual(self.b.bootstrap()["status"], 429)
        self.now += 61
        with patch("webapp.MAX_SESSIONS", 1):
            self.assertEqual(self.b.bootstrap()["status"], 503)

    def test_event_limit_can_be_cleared_by_session_owner(self):
        self.a.bootstrap()
        session_id = SimpleCookie(self.a.cookie)["__Host-vigia"].value
        store = Store(self.app.database_path(session_id))
        try:
            items = [scenario("role")[0] for _ in range(MAX_SESSION_EVENTS)]
            store.ingest(items)
        finally:
            store.db.close()
        self.assertEqual(self.a.request("/api/simulate", {"scenario": "role"})["status"], 409)
        self.assertEqual(self.a.request("/api/reset", {})["status"], 200)
        self.assertEqual(self.a.request("/api/simulate", {"scenario": "role"})["status"], 201)

    def test_body_limits_type_and_method_are_enforced(self):
        self.a.bootstrap()
        self.assertEqual(self.a.request("/api/state", {}, method="POST")["status"], 405)
        self.assertEqual(self.a.request("/api/simulate", {}, headers={"CONTENT_TYPE": "text/plain"})["status"], 415)
        self.assertEqual(self.a.request("/api/simulate", raw=b"x" * 16385)["status"], 413)
        self.assertEqual(self.a.request("/api/simulate", raw=b"not json")["status"], 400)

    def test_cookie_cannot_supply_paths_or_fix_an_unknown_session(self):
        self.a.cookie = "__Host-vigia=../../anything"
        self.assertEqual(self.a.request("/api/state")["status"], 401)
        self.a.cookie = "__Host-vigia=" + "a" * 64
        self.a.bootstrap()
        self.assertNotEqual(self.a.cookie, "__Host-vigia=" + "a" * 64)

    def test_public_configuration_requires_https_and_absolute_storage(self):
        for origin in ("http://public.example", "https://vigia.example.test/path", "https://name:password@example.test"):
            with self.assertRaises(ValueError):
                DemoApplication(origin, Path(self.directory.name))
        with self.assertRaises(ValueError):
            DemoApplication("https://vigia.example.test", Path("relative"))
