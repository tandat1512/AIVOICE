"""Tầng A: Input Processor — classifies STT events into TranslationRequests."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class EventType(Enum):
    interim_grow = "interim_grow"            # new words appended to end of interim
    interim_update = "interim_update"        # words changed mid-interim (correction)
    final_commit = "final_commit"            # interim cleared, committed grew
    sentence_boundary = "sentence_boundary"  # punctuation detected at commit boundary
    no_change = "no_change"                  # neither committed nor interim changed


@dataclass
class TranslationRequest:
    event_type: EventType
    new_tokens: list[str]
    full_text: str          # committed + interim combined
    committed_text: str     # committed portion only
    prev_committed: str
    session_id: str
    language_pair: Tuple[str, str]  # (src, tgt)


_SENTENCE_END = frozenset([".", "!", "?", "…", "。", "！", "？"])


class EventClassifier:
    """Classifies STT update pairs into EventType."""

    def classify(
        self,
        committed: str,
        interim: str,
        prev_committed: str,
        prev_interim: str,
        session_id: str = "",
        src_lang: str = "vi",
        tgt_lang: str = "en",
    ) -> TranslationRequest:
        committed_changed = committed != prev_committed
        interim_changed = interim != prev_interim

        full_text = (committed + " " + interim).strip()

        if not committed_changed and not interim_changed:
            return TranslationRequest(
                event_type=EventType.no_change,
                new_tokens=[],
                full_text=full_text,
                committed_text=committed,
                prev_committed=prev_committed,
                session_id=session_id,
                language_pair=(src_lang, tgt_lang),
            )

        event_type = self._classify_event(
            committed, interim, prev_committed, prev_interim,
            committed_changed, interim_changed,
        )
        new_tokens = self._compute_new_tokens(committed, interim, prev_committed, prev_interim)

        return TranslationRequest(
            event_type=event_type,
            new_tokens=new_tokens,
            full_text=full_text,
            committed_text=committed,
            prev_committed=prev_committed,
            session_id=session_id,
            language_pair=(src_lang, tgt_lang),
        )

    def _classify_event(
        self,
        committed: str,
        interim: str,
        prev_committed: str,
        prev_interim: str,
        committed_changed: bool,
        interim_changed: bool,
    ) -> EventType:
        # Committed grew and interim is empty → sentence commit
        if committed_changed and not interim:
            new_part = committed[len(prev_committed):].strip() if committed.startswith(prev_committed) else committed
            if any(ch in new_part for ch in _SENTENCE_END):
                return EventType.sentence_boundary
            return EventType.final_commit

        # Interim changed
        if interim_changed:
            prev_words = prev_interim.split() if prev_interim else []
            curr_words = interim.split() if interim else []
            # Grow: current interim starts with all prior words and adds more
            if (curr_words and
                    len(curr_words) > len(prev_words) and
                    curr_words[:len(prev_words)] == prev_words):
                return EventType.interim_grow
            return EventType.interim_update

        # Committed changed but interim is non-empty (Sherpa rolling commit)
        return EventType.final_commit

    def _compute_new_tokens(
        self,
        committed: str,
        interim: str,
        prev_committed: str,
        prev_interim: str,
    ) -> list[str]:
        """Return tokens genuinely added in this update using difflib."""
        prev_words = (prev_committed + " " + prev_interim).strip().split()
        curr_words = (committed + " " + interim).strip().split()
        if not prev_words:
            return curr_words

        matcher = difflib.SequenceMatcher(None, prev_words, curr_words, autojunk=False)
        added: list[str] = []
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("insert", "replace"):
                added.extend(curr_words[j1:j2])
        return added
