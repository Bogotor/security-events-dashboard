"""Envía un evento ficticio a Vigía sin mostrar la credencial local."""
import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--user', default='analista@demo.test')
    parser.add_argument('--type', choices=['login_failed', 'login_success', 'role_changed'], default='login_failed')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('El puerto debe estar entre 1 y 65535.')
    token_path = Path(__file__).resolve().parents[1] / 'data' / 'ingest.token'
    try:
        token = token_path.read_text().strip()
    except OSError:
        parser.exit(1, 'No se pudo leer la credencial. Inicia primero python3 app.py con su carpeta de datos predeterminada.\n')
    event = {
        'event_id': str(uuid.uuid4()),
        'occurred_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'type': args.type,
        'user': args.user,
        'source_ip': '192.0.2.25',
        'metadata': {'old_role': 'viewer', 'new_role': 'admin'} if args.type == 'role_changed' else {},
    }
    request = Request(
        'http://127.0.0.1:%s/api/events' % args.port,
        data=json.dumps(event).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
        method='POST',
    )
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
        print('Evento enviado: %s | %s | insertados: %s' % (event['event_id'], event['type'], result['inserted']))
    except HTTPError as error:
        parser.exit(1, 'El servidor rechazó el evento (HTTP %s). Revisa el usuario, los datos y la credencial local.\n' % error.code)
    except (URLError, TimeoutError):
        parser.exit(1, 'No se pudo conectar con Vigía. Comprueba que el servidor esté iniciado en el puerto indicado.\n')


if __name__ == '__main__':
    main()
