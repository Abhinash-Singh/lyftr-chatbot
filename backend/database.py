import json
import os
from datetime import datetime, timezone

import aiosqlite


async def init_db(db_path: str) -> None:
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session_id
            ON messages(session_id)
            """
        )
        await db.commit()


async def save_message(
    db_path: str,
    session_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        created_at = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata) if metadata else None
        await db.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, metadata_json, created_at),
        )
        await db.commit()


async def get_session_messages(db_path: str, session_id: str) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, metadata FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()

    result: list[dict] = []
    for row in rows:
        msg: dict = {"role": row["role"], "content": row["content"]}
        if row["metadata"]:
            msg["metadata"] = json.loads(row["metadata"])
        result.append(msg)
    return result


async def session_exists(db_path: str, session_id: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
            (session_id,),
        )
        row = await cursor.fetchone()
    return row is not None
