from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "sessions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                mode TEXT DEFAULT 'manus',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                step_number INTEGER,
                step_type TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def create_session(mode: str) -> str:
    session_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute("INSERT INTO sessions (id, mode, title) VALUES (?, ?, ?)", (session_id, mode, "New Chat"))
    return session_id


def get_sessions() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.mode, s.created_at, s.updated_at,
                   m.content AS last_message
            FROM sessions s
            LEFT JOIN messages m
              ON m.id = (
                  SELECT id FROM messages
                  WHERE session_id = s.id
                  ORDER BY timestamp DESC, id DESC
                  LIMIT 1
              )
            ORDER BY s.updated_at DESC, s.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, step_number, step_type, timestamp
            FROM messages
            WHERE session_id = ?
            ORDER BY timestamp ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_message(
    session_id: str,
    role: str,
    content: str,
    step_number: int | None = None,
    step_type: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (session_id, role, content, step_number, step_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, step_number, step_type),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )


def update_session_title(session_id: str, title: str) -> None:
    safe = (title or "New Chat").strip()[:50] or "New Chat"
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (safe, session_id),
        )


def delete_session(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


init_db()
