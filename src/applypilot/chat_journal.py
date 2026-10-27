"""Private at-most-once HH chat reply reservations, separate from applications."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class ChatJournal:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS chat_replies (
                account TEXT NOT NULL, thread_id TEXT NOT NULL, inbound_key TEXT NOT NULL,
                vacancy_id TEXT NOT NULL, reply_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account, thread_id, inbound_key))''')
        path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def reserve(self, account: str, thread_id: str, vacancy_id: str,
                inbound_key: str, reply: str) -> bool:
        """Persist before any send click. Existing/uncertain replies never retry."""
        digest = hashlib.sha256(reply.encode('utf-8')).hexdigest()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute('''INSERT INTO chat_replies
                    (account,thread_id,inbound_key,vacancy_id,reply_sha256,state)
                    VALUES (?,?,?,?,?,'submitting')''',
                             (account, thread_id, inbound_key, vacancy_id, digest))
            except sqlite3.IntegrityError:
                return False
        return True

    def finish(self, account: str, thread_id: str, inbound_key: str, state: str) -> None:
        if state not in {'sent', 'unknown', 'stale'}:
            raise ValueError('Unsupported chat outcome')
        with self.connect() as conn:
            conn.execute('''UPDATE chat_replies SET state=?,updated_at=CURRENT_TIMESTAMP
                WHERE account=? AND thread_id=? AND inbound_key=? AND state='submitting' ''',
                         (state, account, thread_id, inbound_key))

    def status(self, account: str, thread_id: str, inbound_key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute('''SELECT state FROM chat_replies
                WHERE account=? AND thread_id=? AND inbound_key=?''',
                               (account, thread_id, inbound_key)).fetchone()
        # A crashed process may retain submitting. Both states block any resend.
        return 'unknown' if row and row[0] == 'submitting' else row[0] if row else None
