import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_VERSION = 2


def _data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    path = os.path.join(base, "aethel")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class Project:
    id: int
    name: str
    path: str
    added_at: str


def _to_project(row: sqlite3.Row) -> Project:
    return Project(row["id"], row["name"], row["path"], row["added_at"])


class Database:
    def __init__(self):
        self.db_path = os.path.join(_data_dir(), "aethel.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        # user_version lets later slices migrate without guessing at tables.
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    added_at TEXT NOT NULL
                );
                """
            )
        if version < 2:
            # Only the router base URL lives here. It is not a secret; under
            # SPEC 2.5 anything sensitive would go to the keyring instead.
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute(
            "SELECT * FROM projects ORDER BY added_at, id"
        ).fetchall()
        return [_to_project(r) for r in rows]

    def get_project(self, project_id: int) -> Project | None:
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return _to_project(row) if row else None

    def add_project(self, name: str, path: str) -> Project:
        # Raises sqlite3.IntegrityError when the same folder is added twice.
        added_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO projects (name, path, added_at) VALUES (?, ?, ?)",
            (name, path, added_at),
        )
        self.conn.commit()
        return Project(cur.lastrowid, name, path, added_at)

    def rename_project(self, project_id: int, name: str) -> None:
        self.conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?", (name, project_id)
        )
        self.conn.commit()

    def remove_project(self, project_id: int) -> None:
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()
