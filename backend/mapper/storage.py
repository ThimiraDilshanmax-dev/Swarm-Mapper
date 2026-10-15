from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "sessions.sqlite3"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL,
            source TEXT NOT NULL, status TEXT NOT NULL, profile TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS samples(
            session_id TEXT NOT NULL, idx INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(session_id, idx));
          CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
            created REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS results(
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            created REAL NOT NULL, payload TEXT NOT NULL);
        """)
        # An interrupted run remains inspectable and cannot silently resume motion.
        self.db.execute("UPDATE sessions SET status='interrupted' WHERE status IN ('mapping','paused')")
        self.db.commit()
        self.dirty = 0

    def create(self, sid: str, name: str, source: str, profile: dict):
        self.db.execute("INSERT INTO sessions(id,name,created,source,status,profile) VALUES(?,?,?,?,?,?)",
                        (sid, name, time.time(), source, "mapping", json.dumps(profile)))
        self.db.commit()

    def sample(self, sid: str, idx: int, payload: dict):
        self.db.execute("INSERT INTO samples VALUES(?,?,?)", (sid, idx, json.dumps(payload, allow_nan=False)))
        self.dirty += 1
        if self.dirty >= 20:
            self.db.commit()
            self.dirty = 0

    def event(self, sid: str | None, kind: str, message: str):
        self.db.execute("INSERT INTO events(session_id,created,kind,message) VALUES(?,?,?,?)",
                        (sid, time.time(), kind, message))
        self.db.commit()

    def finish(self, sid: str, status: str, summary: dict):
        self.db.execute("UPDATE sessions SET status=?, summary=? WHERE id=?",
                        (status, json.dumps(summary), sid))
        self.db.commit()

    def sessions(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sessions ORDER BY created DESC").fetchall()
        names = [d[0] for d in self.db.execute("SELECT * FROM sessions LIMIT 0").description]
        result = []
        for row in rows:
            d = dict(zip(names, row))
            d["profile"], d["summary"] = json.loads(d["profile"]), json.loads(d["summary"])
            d["samples"] = self.db.execute("SELECT COUNT(*) FROM samples WHERE session_id=?", (d["id"],)).fetchone()[0]
            result.append(d)
        return result

    def get(self, sid: str) -> dict:
        session = next((s for s in self.sessions() if s["id"] == sid), None)
        if not session:
            raise KeyError(sid)
        session["samples_data"] = [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM samples WHERE session_id=? ORDER BY idx", (sid,))]
        session["events"] = [dict(created=r[0], kind=r[1], message=r[2]) for r in self.db.execute(
            "SELECT created,kind,message FROM events WHERE session_id=? ORDER BY id", (sid,))]
        session["results"] = [dict(id=r[0],created=r[1],payload=json.loads(r[2])) for r in self.db.execute(
            "SELECT id,created,payload FROM results WHERE session_id=? ORDER BY id", (sid,))]
        return session

    def result(self, sid: str, payload: dict):
        self.db.execute("INSERT INTO results(session_id,created,payload) VALUES(?,?,?)",
                        (sid,time.time(),json.dumps(payload)))
        self.db.commit()

    def note(self, sid: str, note: str):
        self.db.execute("UPDATE sessions SET note=? WHERE id=?", (note, sid))
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()
