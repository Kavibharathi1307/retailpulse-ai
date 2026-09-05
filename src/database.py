"""SQLite connection management and startup bootstrap (Milestone 2).

The database file lives at ``data/retailpulse.db`` and is committed to the
repository, so the application works immediately after a fresh clone. On startup
:func:`ensure_database` only verifies the schema and, if the committed dataset
is missing for any reason, regenerates it deterministically.
"""

from contextlib import contextmanager
from pathlib import Path

import sqlite3

from src.config import DATABASE_PATH
from src.schema import apply_schema


def open_connection(db_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    """Open a connection to the retail database with useful defaults."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(db_path: Path = DATABASE_PATH):
    """Context manager yielding a short-lived connection to the database."""
    conn = open_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def ensure_database(db_path: Path = DATABASE_PATH) -> None:
    """Make sure the database exists and is populated.

    * If the committed dataset is present, this is a fast no-op.
    * If application tables are missing or empty, the deterministic sample
      dataset is generated on the spot so the app always starts.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = open_connection(db_path)
    try:
        apply_schema(conn)
        populated = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] > 0
    finally:
        conn.close()

    if not populated:
        from src.data_generation import generate_dataset

        generate_dataset(db_path, force=False)