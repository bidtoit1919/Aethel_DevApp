import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_VERSION = 3


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
    router_url: str | None = None
    preferred_agent: str | None = None
    preferred_model: str | None = None
    preferred_terminal: str | None = None


DEFAULT_COLUMNS = (
    "router_url",
    "preferred_agent",
    "preferred_model",
    "preferred_terminal",
)


def _to_project(row: sqlite3.Row) -> Project:
    return Project(
        row["id"],
        row["name"],
        row["path"],
        row["added_at"],
        row["router_url"],
        row["preferred_agent"],
        row["preferred_model"],
        row["preferred_terminal"],
    )


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
        if version < 3:
            # NULL means "no override / unset", so existing rows keep the
            # global behaviour without any data backfill.
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
            # An uncommitted earlier draft added this column under another
            # name without bumping user_version; keep its values.
            if "router_endpoint_override" in cols and "router_url" not in cols:
                self.conn.execute(
                    "ALTER TABLE projects RENAME COLUMN "
                    "router_endpoint_override TO router_url"
                )
                cols.add("router_url")
            for column in DEFAULT_COLUMNS:
                if column not in cols:
                    self.conn.execute(
                        f"ALTER TABLE projects ADD COLUMN {column} TEXT"
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

    def set_project_default(self, project_id: int, column: str, value: str | None) -> None:
        # Column name is interpolated into SQL, so it must come from the
        # fixed schema list, never from caller-supplied text.
        if column not in DEFAULT_COLUMNS:
            raise ValueError(f"unknown project default: {column}")
        self.conn.execute(
            f"UPDATE projects SET {column} = ? WHERE id = ?", (value, project_id)
        )
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
