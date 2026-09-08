"""SQLite is the commit boundary for state, stock, receipts and audit events.

Each callback runs off the asyncio loop in one BEGIN IMMEDIATE transaction.
An interrupted awaiting coroutine does not pretend to roll back a committed write.
"""

import asyncio
import json
import sqlite3
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pickmate.domain.models import Session
from pickmate.storage.seed import inventory

worker_lease = ContextVar("worker_lease", default=None)


class SupersededWorker(Exception):
    pass


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.clock_domain = f"api-{uuid4().hex}"

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    async def initialize(self):
        def migrate():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as con:
                con.execute("PRAGMA journal_mode=WAL")
                con.executescript("""
                    CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY);
                    CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS inventory(sku TEXT PRIMARY KEY, payload TEXT NOT NULL,
                        available INTEGER NOT NULL CHECK(available>=0), version INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS completions(operation_id TEXT PRIMARY KEY,
                        task_id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL REFERENCES sessions(id),
                        task_version INTEGER NOT NULL, sku TEXT NOT NULL REFERENCES inventory(sku),
                        quantity INTEGER NOT NULL CHECK(quantity>0 AND quantity<=1000),
                        confirmation_id TEXT NOT NULL, utc TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL REFERENCES sessions(id), payload TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS events_session ON events(session_id,seq);
                    CREATE TABLE IF NOT EXISTS inputs(session_id TEXT NOT NULL REFERENCES sessions(id),
                        event_id TEXT NOT NULL, PRIMARY KEY(session_id,event_id));
                    INSERT OR IGNORE INTO migrations VALUES(1);
                """)
                for item in inventory():
                    con.execute(
                        "INSERT OR IGNORE INTO inventory VALUES(?,?,?,?)",
                        (item.sku, item.model_dump_json(), item.available, 1),
                    )

        await asyncio.to_thread(migrate)

    async def create(self, session):
        def write():
            with self.connect() as con:
                con.execute(
                    "INSERT INTO sessions VALUES(?,?)", (session.session_id, session.model_dump_json())
                )

        await asyncio.to_thread(write)

    async def change(self, sid, fn):
        def transaction():
            with self.connect() as con:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()
                if row is None:
                    raise KeyError("Session not found")
                state = Session.model_validate_json(row["state"])
                lease = worker_lease.get()
                if lease and (lease[0] != sid or lease[1] != state.worker_epoch):
                    raise SupersededWorker("Worker lease was superseded")

                def emit(kind, **data):
                    event = dict(
                        type=kind,
                        session_id=sid,
                        utc=datetime.now(timezone.utc).isoformat(),
                        monotonic_ms=time.monotonic_ns() / 1e6,
                        clock_domain=self.clock_domain,
                        task_id=state.task.task_id if state.task else None,
                        task_version=state.task.task_version if state.task else None,
                        response_epoch=state.response_epoch,
                        data=data,
                    )
                    con.execute(
                        "INSERT INTO events(session_id,payload) VALUES(?,?)", (sid, json.dumps(event))
                    )

                result = fn(state, con, emit)
                con.execute("UPDATE sessions SET state=? WHERE id=?", (state.model_dump_json(), sid))
                return result

        # Shield prevents cancellation from being mistaken for transaction rollback.
        task = asyncio.create_task(asyncio.to_thread(transaction))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    @staticmethod
    def items(con):
        return [
            dict(json.loads(r["payload"]), available=r["available"], inventory_version=r["version"])
            for r in con.execute("SELECT * FROM inventory ORDER BY sku")
        ]

    async def snapshot(self, sid):
        def read():
            with self.connect() as con:
                con.execute("BEGIN")
                row = con.execute("SELECT state FROM sessions WHERE id=?", (sid,)).fetchone()
                if not row:
                    raise KeyError("Session not found")
                s = json.loads(row["state"])
                s.pop("owner_hash")
                s["inventory"] = self.items(con)
                s["history"] = [
                    dict(r)
                    for r in con.execute("SELECT * FROM completions WHERE session_id=? ORDER BY utc", (sid,))
                ]
                s["events"] = [
                    dict(json.loads(r["payload"]), seq=r["seq"])
                    for r in con.execute(
                        "SELECT * FROM (SELECT * FROM events WHERE session_id=? ORDER BY seq DESC LIMIT 500) ORDER BY seq",
                        (sid,),
                    )
                ]
                s["revision"] = s["events"][-1]["seq"] if s["events"] else 0
                return s

        return await asyncio.to_thread(read)

    async def export_events(self, sid):
        def read():
            with self.connect() as con:
                return [
                    dict(json.loads(r["payload"]), seq=r["seq"])
                    for r in con.execute("SELECT * FROM events WHERE session_id=? ORDER BY seq", (sid,))
                ]

        return await asyncio.to_thread(read)
