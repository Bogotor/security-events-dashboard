"""Crea una copia consistente de SQLite; no imprime datos ni cookies de sesión."""
import argparse
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def copy_database(source, target):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(str(target))) as writer:
            reader.backup(writer)
            if writer.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("La copia no superó la verificación de integridad.")
    target.chmod(0o600)


def backup(data_dir, output_dir):
    data_dir = Path(data_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir == data_dir or data_dir in output_dir.parents:
        raise ValueError("La copia debe estar fuera de la carpeta de datos activa.")
    if not (data_dir / "registry.sqlite3").is_file():
        raise ValueError("No se encuentra una base de sesiones para respaldar.")
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = output_dir / name
    target.mkdir(parents=True, mode=0o700)
    (target / "sessions").mkdir(mode=0o700)
    with closing(sqlite3.connect(str(data_dir / "registry.sqlite3"), timeout=10)) as registry:
        registry.execute("BEGIN IMMEDIATE")
        try:
            ids = [row[0] for row in registry.execute("SELECT id FROM sessions")]
            copy_database(data_dir / "registry.sqlite3", target / "registry.sqlite3")
            for session_id in ids:
                # Se valida cada nombre antes de construir la ruta a su base.
                if len(session_id) != 64 or any(c not in "0123456789abcdef" for c in session_id):
                    raise ValueError("Identificador de sesión inválido en el registro.")
                source = data_dir / "sessions" / (session_id + ".sqlite3")
                if source.exists():
                    copy_database(source, target / "sessions" / source.name)
        finally:
            registry.rollback()
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        target = backup(args.data_dir, args.output_dir)
    except (OSError, ValueError, sqlite3.Error, RuntimeError):
        parser.exit(1, "No se pudo completar la copia. Conserva la base activa y revisa rutas, permisos y espacio disponible.\n")
    print("Copia SQLite verificada: " + str(target))


if __name__ == "__main__":
    main()
