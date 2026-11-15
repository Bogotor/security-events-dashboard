"""Punto de entrada para el tipo de sitio Python WSGI de Alwaysdata."""
import os
import threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webapp import DemoApplication

_application = None
_lock = threading.Lock()


def application(environ, start_response):
    global _application
    if _application is None:
        with _lock:
            if _application is None:
                origin = os.environ.get("VIGIA_PUBLIC_ORIGIN", "")
                data_dir = os.environ.get("VIGIA_DATA_DIR", "")
                try:
                    if not data_dir:
                        raise ValueError("Falta la carpeta de datos.")
                    _application = DemoApplication(origin, data_dir)
                except (ValueError, OSError):
                    body = b"Vigia necesita configurar su origen HTTPS y su carpeta privada de datos."
                    start_response("503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8"),
                                   ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                    return [body]
    return _application(environ, start_response)
