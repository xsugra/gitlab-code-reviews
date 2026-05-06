import logging
import os
from datetime import datetime, timezone

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/reviews.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    project_name TEXT NOT NULL,
    mr_iid INTEGER NOT NULL,
    mr_title TEXT,
    mr_url TEXT,
    model TEXT NOT NULL,
    chunks_count INTEGER NOT NULL,
    review_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_project_mr ON reviews(project_id, mr_iid);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(created_at);
"""


async def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()
    log.info("Database initialized at %s", DB_PATH)


async def save_review(
    project_id: int,
    project_name: str,
    mr_iid: int,
    mr_title: str,
    mr_url: str,
    model: str,
    chunks_count: int,
    review_text: str,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """INSERT INTO reviews
               (project_id, project_name, mr_iid, mr_title, mr_url, model, chunks_count, review_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, project_name, mr_iid, mr_title, mr_url, model, chunks_count, review_text, now),
        )
        await conn.commit()
        return cursor.lastrowid


async def get_reviews(project_id: int | None = None, mr_iid: int | None = None, limit: int = 50) -> list[dict]:
    query = "SELECT * FROM reviews WHERE 1=1"
    params: list = []
    if project_id is not None:
        query += " AND project_id = ?"
        params.append(project_id)
    if mr_iid is not None:
        query += " AND mr_iid = ?"
        params.append(mr_iid)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
