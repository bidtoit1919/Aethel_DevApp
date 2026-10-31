import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_VERSION = 5

# Events not tied to a project (Arena runs without one) use this id.
GLOBAL = 0


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
    # JSON list of context items chosen for the next launch.
    context_json: str | None = None
    task: str | None = None
    test_command: str | None = None
    # "1"/"0"; NULL means the default (on).
    auto_compact: str | None = None
    auto_init: str | None = None

    @property
    def context(self) -> list[dict]:
        try:
            items = json.loads(self.context_json or "[]")
        except ValueError:
            return []
        return items if isinstance(items, list) else []

    def flag(self, name: str) -> bool:
        return getattr(self, name) != "0"


DEFAULT_COLUMNS = (
    "router_url",
    "preferred_agent",
    "preferred_model",
    "preferred_terminal",
    "context_json",
    "task",
    "test_command",
    "auto_compact",
    "auto_init",
)


@dataclass
class Suite:
    id: int
    name: str
    tag: str
    prompts: list
    models: list
    created_at: str


@dataclass
class Event:
    id: int
    project_id: int
    kind: str
    created_at: str
    summary: str
    data: dict
    # For session_end: the launch event this closes.
    ref_id: int | None = None


def _to_event(row: sqlite3.Row) -> Event:
    return Event(
        row["id"],
        row["project_id"],
        row["kind"],
        row["created_at"],
        row["summary"],
        json.loads(row["data"]),
        row["ref_id"],
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_project(row: sqlite3.Row) -> Project:
    return Project(
        row["id"],
        row["name"],
        row["path"],
        row["added_at"],
        *(row[c] for c in DEFAULT_COLUMNS),
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
        if version < 4:
            # Event payloads differ per kind (SPEC 3.5), so they are stored as
            # JSON next to the few columns the timeline needs to list them.
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    data TEXT NOT NULL,
                    ref_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS events_by_project
                    ON events (project_id, created_at);
                """
            )
        if version < 5:
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
            for column in DEFAULT_COLUMNS:
                if column not in cols:
                    self.conn.execute(f"ALTER TABLE projects ADD COLUMN {column} TEXT")
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS suites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    prompts TEXT NOT NULL,
                    models TEXT NOT NULL,
                    created_at TEXT NOT NULL
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
        added_at = now_iso()
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
        self.conn.execute("DELETE FROM events WHERE project_id = ?", (project_id,))
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

    def add_event(
        self,
        project_id: int,
        kind: str,
        summary: str,
        data: dict,
        ref_id: int | None = None,
    ) -> Event:
        created_at = now_iso()
        cur = self.conn.execute(
            "INSERT INTO events (project_id, kind, created_at, summary, data, ref_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, kind, created_at, summary, json.dumps(data), ref_id),
        )
        self.conn.commit()
        return Event(cur.lastrowid, project_id, kind, created_at, summary, data, ref_id)

    def list_events(self, project_id: int) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE project_id = ? ORDER BY created_at DESC, id DESC",
            (project_id,),
        ).fetchall()
        return [_to_event(r) for r in rows]

    def get_event(self, event_id: int) -> Event | None:
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return _to_event(row) if row else None

    def update_event_data(self, event_id: int, data: dict) -> None:
        self.conn.execute(
            "UPDATE events SET data = ? WHERE id = ?", (json.dumps(data), event_id)
        )
        self.conn.commit()

    def ended_launch_ids(self, project_id: int) -> set[int]:
        rows = self.conn.execute(
            "SELECT ref_id FROM events WHERE project_id = ? AND kind = 'session_end'",
            (project_id,),
        ).fetchall()
        return {r["ref_id"] for r in rows}

    def recent_events(self, limit: int = 30) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_to_event(r) for r in rows]

    def events_of_kind(self, kind: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE kind = ? ORDER BY created_at DESC, id DESC", (kind,)
        ).fetchall()
        return [_to_event(r) for r in rows]

    def count_events(self, project_id: int, kind: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE project_id = ? AND kind = ?",
            (project_id, kind),
        ).fetchone()[0]

    def save_suite(self, name: str, tag: str, prompts: list, models: list, suite_id: int | None = None) -> int:
        if suite_id is None:
            cur = self.conn.execute(
                "INSERT INTO suites (name, tag, prompts, models, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, tag, json.dumps(prompts), json.dumps(models), now_iso()),
            )
            suite_id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE suites SET name = ?, tag = ?, prompts = ?, models = ? WHERE id = ?",
                (name, tag, json.dumps(prompts), json.dumps(models), suite_id),
            )
        self.conn.commit()
        return suite_id

    def list_suites(self) -> list[Suite]:
        rows = self.conn.execute("SELECT * FROM suites ORDER BY name").fetchall()
        return [
            Suite(r["id"], r["name"], r["tag"], json.loads(r["prompts"]), json.loads(r["models"]), r["created_at"])
            for r in rows
        ]

    def delete_suite(self, suite_id: int) -> None:
        self.conn.execute("DELETE FROM suites WHERE id = ?", (suite_id,))
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
