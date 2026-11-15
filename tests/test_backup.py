import tempfile
import unittest
from pathlib import Path

from scripts.backup_demo import backup
from test_webapp import Client
from webapp import DemoApplication


class BackupTests(unittest.TestCase):
    def test_consistent_backup_can_restore_sessions_events_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = DemoApplication("https://vigia.example.test", root / "active")
            client = Client(application)
            client.bootstrap()
            client.request("/api/simulate", {"scenario": "role"})
            alert_id = client.request("/api/state")["body"]["alerts"][0]["id"]
            client.request("/api/alerts/update", {"id": alert_id, "status": "resolved", "note": "Prueba de restauración"})
            target = backup(root / "active", root / "backups")
            client.request("/api/reset", {})
            self.assertEqual(client.request("/api/state")["body"]["events"], [])
            client.app = DemoApplication("https://vigia.example.test", target)
            restored = client.request("/api/state")["body"]
            self.assertEqual(len(restored["events"]), 1)
            self.assertEqual(restored["alerts"][0]["note"], "Prueba de restauración")
            self.assertEqual(restored["alerts"][0]["status"], "resolved")

    def test_backup_rejects_a_destination_inside_live_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            DemoApplication("https://vigia.example.test", root)
            with self.assertRaises(ValueError):
                backup(root, root / "backup")
