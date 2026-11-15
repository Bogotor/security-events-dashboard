import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from app import Server, Store


class ExampleTests(unittest.TestCase):
    def test_example_sends_real_events_without_printing_the_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'examples').mkdir()
            (root / 'data').mkdir()
            token = 'integration-test-local-credential'
            (root / 'data' / 'ingest.token').write_text(token)
            script = root / 'examples' / 'send_event.py'
            shutil.copy2(Path(__file__).resolve().parents[1] / 'examples' / 'send_event.py', script)
            store = Store(':memory:')
            server = Server(('127.0.0.1', 0), store, token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for kind in ['login_failed'] * 5 + ['login_success', 'role_changed']:
                    result = subprocess.run(
                        [sys.executable, str(script), '--port', str(server.server_port), '--type', kind],
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn(token, result.stdout + result.stderr)
                snapshot = store.snapshot()
                self.assertEqual(len(snapshot['events']), 7)
                self.assertEqual({a['rule'] for a in snapshot['alerts']},
                                 {'repeated_failures', 'success_after_failures', 'role_changed'})
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                store.db.close()
