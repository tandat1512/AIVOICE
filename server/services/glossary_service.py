"""SQLite-backed glossary service."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from server.schemas.glossary_schema import GlossaryItemCreate, GlossaryItemUpdate


class GlossaryService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self._db_path = Path(db_path) if db_path else root / "data" / "glossary.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def list_items(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, source_term, target_term, src_lang, tgt_lang, note, created_at FROM glossary ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_item(self, item: GlossaryItemCreate) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO glossary(source_term, target_term, src_lang, tgt_lang, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source_term.strip(),
                    item.target_term.strip(),
                    item.src_lang.strip(),
                    item.tgt_lang.strip(),
                    item.note.strip(),
                    now,
                ),
            )
            con.commit()
            item_id = int(cur.lastrowid)
        return self.get_item(item_id)

    def get_item(self, item_id: int) -> dict:
        with self._connect() as con:
            row = con.execute(
                "SELECT id, source_term, target_term, src_lang, tgt_lang, note, created_at FROM glossary WHERE id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise KeyError("glossary item not found")
        return dict(row)

    def update_item(self, item_id: int, patch: GlossaryItemUpdate) -> dict:
        current = self.get_item(item_id)
        data = patch.model_dump(exclude_unset=True)
        if not data:
            return current
        merged = {**current, **{k: (v.strip() if isinstance(v, str) else v) for k, v in data.items() if v is not None}}
        with self._connect() as con:
            con.execute(
                """
                UPDATE glossary
                SET source_term = ?, target_term = ?, src_lang = ?, tgt_lang = ?, note = ?
                WHERE id = ?
                """,
                (
                    merged["source_term"],
                    merged["target_term"],
                    merged["src_lang"],
                    merged["tgt_lang"],
                    merged.get("note") or "",
                    item_id,
                ),
            )
            con.commit()
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> None:
        with self._connect() as con:
            cur = con.execute("DELETE FROM glossary WHERE id = ?", (item_id,))
            con.commit()
        if cur.rowcount == 0:
            raise KeyError("glossary item not found")

    def terms_for(self, src_lang: str, tgt_lang: str) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, source_term, target_term, src_lang, tgt_lang, note, created_at
                FROM glossary
                WHERE src_lang = ? AND tgt_lang = ?
                ORDER BY length(source_term) DESC
                """,
                (src_lang, tgt_lang),
            ).fetchall()
        return [dict(row) for row in rows]

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_term TEXT NOT NULL,
                    target_term TEXT NOT NULL,
                    src_lang TEXT NOT NULL,
                    tgt_lang TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_glossary_langs ON glossary(src_lang, tgt_lang)")
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        return con
