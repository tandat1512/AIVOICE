"""Tầng C: Translation Buffer — 3-layer state management."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ChunkState(Enum):
    volatile_interim = "volatile_interim"
    stable_interim = "stable_interim"
    committed = "committed"


@dataclass
class _BufferEntry:
    chunk_id: str
    text: str
    state: ChunkState


class TranslationBuffer:
    """Tracks translation chunks across three stability layers.

    Layer order (most volatile → most stable):
      volatile_interim → stable_interim → committed
    """

    def __init__(self) -> None:
        self._entries: dict[str, _BufferEntry] = {}
        # Ordered insertion lists per layer
        self._volatile: list[str] = []
        self._stable: list[str] = []
        self._committed: list[str] = []

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add_chunk(self, chunk_id: str, text: str, state: ChunkState) -> None:
        entry = _BufferEntry(chunk_id=chunk_id, text=text, state=state)
        self._entries[chunk_id] = entry
        self._layer_list(state).append(chunk_id)

    def replace_volatile(self, chunk_id: str, new_text: str) -> bool:
        """Replace text for a volatile chunk. Returns False if chunk not volatile."""
        entry = self._entries.get(chunk_id)
        if entry is None or entry.state != ChunkState.volatile_interim:
            return False
        entry.text = new_text
        return True

    def promote_volatile_to_stable(self, chunk_id: str) -> bool:
        """Move chunk from volatile → stable. Returns False if not found/volatile."""
        entry = self._entries.get(chunk_id)
        if entry is None or entry.state != ChunkState.volatile_interim:
            return False
        self._volatile.remove(chunk_id)
        entry.state = ChunkState.stable_interim
        self._stable.append(chunk_id)
        return True

    def commit_chunk(self, chunk_id: str, final_text: str | None = None) -> bool:
        """Move chunk to committed, optionally replacing its text.

        If the chunk is already committed (pre-placed placeholder), update text
        in-place to preserve insertion order when clauses finish out of sequence.
        """
        entry = self._entries.get(chunk_id)
        if entry is None:
            return False
        if entry.state == ChunkState.committed:
            # Already in committed list — just update text, don't reorder.
            if final_text is not None:
                entry.text = final_text
            return True
        old_state = entry.state
        self._layer_list(old_state).remove(chunk_id)
        if final_text is not None:
            entry.text = final_text
        entry.state = ChunkState.committed
        self._committed.append(chunk_id)
        return True

    def revise_committed_chunk(self, chunk_id: str, text: str) -> bool:
        """Replace the text of an already-committed chunk in place (e.g. a
        PhoWhisper correction re-translated). Returns False if not committed."""
        entry = self._entries.get(chunk_id)
        if entry is None or entry.state != ChunkState.committed:
            return False
        entry.text = text
        return True

    def clear_volatile(self) -> None:
        """Discard all volatile chunks."""
        for cid in list(self._volatile):
            del self._entries[cid]
        self._volatile.clear()

    def clear_committed_chunks(self) -> None:
        """Discard all committed chunks (used on revision/reset)."""
        for cid in list(self._committed):
            del self._entries[cid]
        self._committed.clear()

    def remove_committed_chunk(self, chunk_id: str) -> None:
        """Remove a specific committed chunk (used during partial revisions)."""
        if chunk_id in self._entries:
            del self._entries[chunk_id]
        if chunk_id in self._committed:
            self._committed.remove(chunk_id)

    def clear_all(self) -> None:
        self._entries.clear()
        self._volatile.clear()
        self._stable.clear()
        self._committed.clear()

    # ── Query ─────────────────────────────────────────────────────────────────

    def to_delta(self) -> dict[str, Any]:
        """Return current buffer state as delta dict for WebSocket emission."""
        return {
            "committed": [
                {"id": cid, "text": self._entries[cid].text}
                for cid in self._committed
            ],
            "stable_interim": [
                {"id": cid, "text": self._entries[cid].text}
                for cid in self._stable
            ],
            "volatile_interim": [
                {"id": cid, "text": self._entries[cid].text}
                for cid in self._volatile
            ],
        }

    def committed_text(self) -> str:
        return " ".join(self._entries[cid].text for cid in self._committed)

    def stable_text(self) -> str:
        return " ".join(self._entries[cid].text for cid in self._stable)

    def volatile_text(self) -> str:
        return " ".join(self._entries[cid].text for cid in self._volatile)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _layer_list(self, state: ChunkState) -> list[str]:
        if state == ChunkState.volatile_interim:
            return self._volatile
        if state == ChunkState.stable_interim:
            return self._stable
        return self._committed
