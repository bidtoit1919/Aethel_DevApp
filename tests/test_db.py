import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from aethel import db


SLICE2_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO projects (name, path, added_at)
    VALUES ('demo', '/tmp/demo', '2026-10-30T00:00:00+00:00');
INSERT INTO settings VALUES ('router_base_url', 'http://localhost:1/v1');
PRAGMA user_version = 2;
"""


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": self._tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.path = os.path.join(self._tmp.name, "aethel", "aethel.db")
        os.makedirs(os.path.dirname(self.path))

    def tearDown(self):
        self._tmp.cleanup()

    def seed(self, extra=""):
        conn = sqlite3.connect(self.path)
        conn.executescript(SLICE2_SCHEMA + extra)
        conn.close()

    def test_slice2_database_keeps_projects(self):
        self.seed()
        database = db.Database()
        [project] = database.list_projects()
        self.assertEqual((project.name, project.path), ("demo", "/tmp/demo"))
        self.assertIsNone(project.router_url)
        self.assertIsNone(project.preferred_model)
        self.assertEqual(database.get_setting("router_base_url"), "http://localhost:1/v1")
        version = database.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_draft_column_is_renamed_with_its_value(self):
        self.seed(
            """
            ALTER TABLE projects ADD COLUMN router_endpoint_override TEXT;
            ALTER TABLE projects ADD COLUMN preferred_agent TEXT;
            ALTER TABLE projects ADD COLUMN preferred_model TEXT;
            ALTER TABLE projects ADD COLUMN preferred_terminal TEXT;
            UPDATE projects SET router_endpoint_override = 'http://other:2/v1';
            """
        )
        database = db.Database()
        cols = {r["name"] for r in database.conn.execute("PRAGMA table_info(projects)")}
        self.assertNotIn("router_endpoint_override", cols)
        [project] = database.list_projects()
        self.assertEqual(project.router_url, "http://other:2/v1")

    def test_defaults_round_trip_and_reopen(self):
        self.seed()
        database = db.Database()
        pid = database.list_projects()[0].id
        database.set_project_default(pid, "preferred_model", "some/model")
        database.set_project_default(pid, "router_url", None)
        database.conn.close()
        [project] = db.Database().list_projects()
        self.assertEqual(project.preferred_model, "some/model")

    def test_events_round_trip_and_follow_project_removal(self):
        self.seed()
        database = db.Database()
        pid = database.list_projects()[0].id
        launch = database.add_event(pid, "launch", "Claude Code", {"model": "m"})
        database.add_event(pid, "session_end", "done", {}, ref_id=launch.id)
        events = database.list_events(pid)
        self.assertEqual([e.kind for e in events], ["session_end", "launch"])
        self.assertEqual(database.get_event(launch.id).data, {"model": "m"})
        self.assertEqual(database.ended_launch_ids(pid), {launch.id})
        database.remove_project(pid)
        self.assertEqual(database.list_events(pid), [])

    def test_unknown_column_rejected(self):
        database = db.Database()
        with self.assertRaises(ValueError):
            database.set_project_default(1, "name; DROP TABLE projects", "x")


if __name__ == "__main__":
    unittest.main()
