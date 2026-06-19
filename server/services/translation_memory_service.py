"""SQLite-backed translation memory with simple string similarity search."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from server.schemas.memory_schema import TranslationMemoryCreate


class TranslationMemoryService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self._db_path = Path(db_path) if db_path else root / "data" / "translation_memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add(self, item: TranslationMemoryCreate) -> dict:
        source = item.source_text.strip()
        translated = item.translated_text.strip()
        if not source or not translated:
            raise ValueError("source_text and translated_text are required")

        existing = self._find_exact(source, item.src_lang, item.tgt_lang)
        if existing:
            return existing

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO translation_memory(source_text, translated_text, src_lang, tgt_lang, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source, translated, item.src_lang, item.tgt_lang, now),
            )
            con.commit()
            item_id = int(cur.lastrowid)
        return self.get(item_id)

    def get(self, item_id: int) -> dict:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id, source_text, translated_text, src_lang, tgt_lang, created_at
                FROM translation_memory WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
        if row is None:
            raise KeyError("translation memory item not found")
        return dict(row)

    def search(
        self,
        query: str,
        *,
        src_lang: str = "",
        tgt_lang: str = "",
        limit: int = 5,
        min_score: float = 0.62,
    ) -> list[dict]:
        q = query.strip()
        if not q:
            return []

        clauses = []
        params: list[str] = []
        if src_lang:
            clauses.append("src_lang = ?")
            params.append(src_lang)
        if tgt_lang:
            clauses.append("tgt_lang = ?")
            params.append(tgt_lang)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT id, source_text, translated_text, src_lang, tgt_lang, created_at
                FROM translation_memory
                {where}
                ORDER BY id DESC
                LIMIT 500
                """,
                params,
            ).fetchall()

        scored: list[dict] = []
        q_norm = self._normalize(q)
        for row in rows:
            item = dict(row)
            score = SequenceMatcher(None, q_norm, self._normalize(item["source_text"])).ratio()
            if score >= min_score:
                item["score"] = round(score, 4)
                scored.append(item)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def _find_exact(self, source_text: str, src_lang: str, tgt_lang: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id, source_text, translated_text, src_lang, tgt_lang, created_at
                FROM translation_memory
                WHERE source_text = ? AND src_lang = ? AND tgt_lang = ?
                ORDER BY id DESC LIMIT 1
                """,
                (source_text, src_lang, tgt_lang),
            ).fetchone()
        return dict(row) if row else None

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    src_lang TEXT NOT NULL,
                    tgt_lang TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_tm_langs ON translation_memory(src_lang, tgt_lang)")
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())
