import os
import tempfile
import unittest
from unittest.mock import patch

import wsgi
from test_webapp import Client


class WSGIEntryTests(unittest.TestCase):
    def test_entrypoint_starts_from_environment_without_external_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(wsgi, "_application", None), patch.dict(os.environ, {
                "VIGIA_PUBLIC_ORIGIN": "https://vigia.example.test", "VIGIA_DATA_DIR": directory,
            }):
                client = Client(wsgi.application)
                self.assertEqual(client.bootstrap()["status"], 200)
                self.assertEqual(client.request("/api/simulate", {"scenario": "normal"})["status"], 201)

    def test_missing_configuration_fails_closed_without_exposing_environment(self):
        with patch.object(wsgi, "_application", None), patch.dict(os.environ, {}, clear=True):
            result = Client(wsgi.application).request("/")
            self.assertEqual(result["status"], 503)
            self.assertNotIn(b"Traceback", result["body"])
