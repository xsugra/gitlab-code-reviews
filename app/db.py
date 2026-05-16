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

CREATE TABLE IF NOT EXISTS webhook_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE,
    project_name TEXT NOT NULL DEFAULT '',
    webhook_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_configs_project
    ON webhook_configs(project_id);
"""


_MIGRATIONS = [
    "ALTER TABLE webhook_configs ADD COLUMN created_by TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE webhook_configs ADD COLUMN updated_by TEXT NOT NULL DEFAULT ''",
]


async def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(_SCHEMA)
        for sql in _MIGRATIONS:
            try:
                await conn.execute(sql)
            except Exception:
                pass
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


async def get_webhook_config(project_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM webhook_configs WHERE project_id = ?", (project_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_webhook_config_by_id(config_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM webhook_configs WHERE id = ?", (config_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_webhook_configs() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM webhook_configs ORDER BY project_id"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def save_webhook_config(
        project_id: int, project_name: str, webhook_url: str, enabled: bool = True,
        created_by: str = "",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """INSERT INTO webhook_configs
               (project_id, project_name, webhook_url, enabled, created_by, updated_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, project_name, webhook_url, int(enabled), created_by, created_by, now, now),
        )
        await conn.commit()
        return cursor.lastrowid


async def update_webhook_config(config_id: int, **fields) -> None:
    allowed = {"project_name", "webhook_url", "enabled", "updated_by"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [config_id]
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            f"UPDATE webhook_configs SET {set_clause} WHERE id = ?", values
        )
        await conn.commit()


async def delete_webhook_config(config_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM webhook_configs WHERE id = ?", (config_id,))
        await conn.commit()
