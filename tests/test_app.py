import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import Server, Store, detect, iso, validate_event

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def event(n, kind="login_failed", seconds=None, user="ana@demo.test"):
    return {"event_id": "event-%03d" % n, "occurred_at": iso(BASE + timedelta(seconds=n if seconds is None else seconds)),
            "type": kind, "user": user, "source_ip": "192.0.2.10", "metadata": {}}


class DetectionTests(unittest.TestCase):
    def test_four_failures_do_not_alert(self):
        self.assertEqual(detect([event(n) for n in range(4)]), [])

    def test_five_failures_alert_once_with_evidence(self):
        alerts = detect([event(n) for n in range(9)])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule"], "repeated_failures")
        self.assertEqual(len(alerts[0]["evidence"]), 5)

    def test_window_includes_exactly_five_minutes(self):
        items = [event(n, seconds=n * 75) for n in range(5)]
        self.assertEqual(len(detect(items)), 1)
        items[-1]["occurred_at"] = iso(BASE + timedelta(seconds=301))
        self.assertEqual(detect(items), [])

    def test_accounts_are_independent(self):
        items = [event(n, user="ana" if n % 2 else "diego") for n in range(8)]
        self.assertEqual(detect(items), [])

    def test_success_after_failures_and_reset(self):
        items = [event(n) for n in range(5)] + [event(5, "login_success"), event(6, "login_success")]
        alerts = detect(items)
        self.assertEqual([a["rule"] for a in alerts], ["repeated_failures", "success_after_failures"])
        self.assertEqual(len(alerts[1]["evidence"]), 6)

    def test_expired_failures_do_not_trigger_success_alert(self):
        items = [event(n) for n in range(5)] + [event(6, "login_success", seconds=600)]
        self.assertEqual([a["rule"] for a in detect(items)], ["repeated_failures"])

    def test_unordered_events_have_identical_results(self):
        items = [event(n) for n in range(5)] + [event(5, "login_success")]
        self.assertEqual(detect(items), detect(list(reversed(items))))

    def test_role_change_exposes_its_evidence(self):
        item = event(1, "role_changed")
        item["metadata"] = {"old_role": "viewer", "new_role": "admin"}
        self.assertEqual(detect([validate_event(item)])[0]["evidence"], [item["event_id"]])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.db.close()

    def test_retry_is_idempotent_and_conflicts_roll_back(self):
        self.assertEqual(self.store.ingest([event(1)]), 1)
        self.assertEqual(self.store.ingest([event(1)]), 0)
        changed = event(1, user="different")
        with self.assertRaises(ValueError):
            self.store.ingest([event(2), changed])
        self.assertEqual(len(self.store.events()), 1)

    def test_late_events_rebuild_alerts(self):
        self.store.ingest([event(5, "login_success")])
        self.assertEqual(self.store.snapshot()["alerts"], [])
        self.store.ingest([event(n) for n in range(5)])
        self.assertEqual(len(self.store.snapshot()["alerts"]), 2)

    def test_notes_and_status_survive_recalculation(self):
        self.store.ingest([event(n) for n in range(5)])
        alert_id = self.store.snapshot()["alerts"][0]["id"]
        self.store.update(alert_id, "resolved", "El usuario confirmó el acceso.")
        self.store.ingest([event(6, user="other")])
        alert = self.store.snapshot()["alerts"][0]
        self.assertEqual(alert["status"], "resolved")
        self.assertEqual(alert["note"], "El usuario confirmó el acceso.")

    def test_data_survives_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = Store(path)
            store.ingest([event(n) for n in range(5)])
            alert_id = store.snapshot()["alerts"][0]["id"]
            store.update(alert_id, "investigating", "Validando autorización")
            store.db.close()
            reopened = Store(path)
            try:
                self.assertEqual(len(reopened.events()), 5)
                self.assertEqual(reopened.snapshot()["alerts"][0]["status"], "investigating")
            finally:
                reopened.db.close()

    def test_invalid_note_status_and_missing_alert_are_rejected(self):
        for status, note in [("invalid", ""), ("resolved", "x" * 2001), ("resolved", "ok")]:
            with self.assertRaises(ValueError):
                self.store.update("missing", status, note)

    def test_validation_rejects_secret_fields_and_naive_dates(self):
        variants = [dict(event(1), password="secret"), dict(event(1), metadata={"token": "secret"}),
                    dict(event(1), occurred_at="2025-01-01T00:00:00"), dict(event(1), source_ip="invalid"),
                    dict(event(1), type=[]), dict(event(1), user="ana\nforged"),
                    dict(event(1), type="role_changed", metadata={"old_role": "admin", "new_role": "admin"})]
        for item in variants:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_event(item)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.server = Server(("127.0.0.1", 0), cls.store, "test-ingestion-credential")
        cls.base = "http://127.0.0.1:%s" % cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.store.db.close()

    def send(self, path, data=None, headers=None):
        request = Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                          headers={"Content-Type": "application/json", **(headers or {})})
        return urlopen(request, timeout=3)

    def test_ingestion_requires_credential(self):
        with self.assertRaises(HTTPError) as error:
            self.send("/api/events", event(1))
        self.assertEqual(error.exception.code, 403)
        with self.send("/api/events", event(1), {"Authorization": "Bearer test-ingestion-credential"}) as response:
            self.assertEqual(response.status, 201)

    def test_browser_mutation_requires_token_and_matching_origin(self):
        with self.send("/api/bootstrap") as response:
            token = json.load(response)["panel_token"]
        for headers in [{}, {"X-Panel-Token": token, "Origin": "https://attacker.test"}]:
            with self.assertRaises(HTTPError) as error:
                self.send("/api/simulate", {"scenario": "normal"}, headers)
            self.assertEqual(error.exception.code, 403)
        with self.send("/api/simulate", {"scenario": "normal"}, {"X-Panel-Token": token, "Origin": self.base}) as response:
            self.assertEqual(response.status, 201)

    def test_rebinding_and_arbitrary_files_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.send("/", headers={"Host": "attacker.test"})
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.send("/../app.py")
        self.assertEqual(error.exception.code, 404)

    def test_security_headers_and_export_do_not_expose_ingestion_token(self):
        with self.send("/") as response:
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        with self.send("/api/export") as response:
            self.assertNotIn("test-ingestion-credential", response.read().decode())


if __name__ == "__main__":
    unittest.main()
