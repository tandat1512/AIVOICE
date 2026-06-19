"""Streaming Translation Router — orchestrates all 5 layers (A-E)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
import uuid

_CONTEXT_DISABLED = os.environ.get("CONTEXT_DISABLED", "1") == "1"

from ..debug_log import olog
from .chunk_manager import TranslationUnitDetector
from .buffer.translation_buffer import TranslationBuffer, ChunkState
from .postprocess.post_processor import PostProcessor
from .postprocess.profanity_filter import filter_profanity
from .engines.base import BaseEngine
from .punctuation import VietnamesePunctuator

_log = logging.getLogger(__name__)
_SENTENCE_DISPATCH_WORDS = 20  # fallback: dispatch after this many accumulated words
_LONG_PAUSE_MS = 600           # silence >= this → treat as sentence end (period); matches sherpa SILENCE_TICKS×TICK_S
_SHORT_PAUSE_MS = 300          # silence >= this but < _LONG_PAUSE_MS → comma hint
_MIN_DISPATCH_WORDS = 2        # wait-final: skip translating/speaking segments shorter than this
                               # (1-word fragments like "hứa" are usually spurious commits)
_EARLY_TTS_WORDS = 7          # dispatch first TTS clip once this many words are translated
_EARLY_TTS_BOUNDARY = ",;:"   # natural clause endings that trigger early dispatch at _EARLY_TTS_WORDS
_EARLY_TTS_HARD = 11          # hard threshold: dispatch regardless of boundary
_TAIL_HOLDBACK_WORDS = 3      # don't dispatch the last N words of an early cụm; keeps
                               # them for the next cụm so the final remainder isn't a
                               # 1-2 word "vụn" fragment
_TTS_MAX_QUEUE = 3            # skip TTS when this many utterances are already queued
_MAX_CLAUSE_WORDS = 25        # split sentences longer than this at comma boundaries
_CLAUSE_SPLIT_RE = re.compile(r'(?<=[,;])\s+')


def _split_clauses(text: str) -> list[str]:
    """Split long text at comma/semicolon boundaries to keep clauses under _MAX_CLAUSE_WORDS."""
    if len(text.split()) <= _MAX_CLAUSE_WORDS:
        return [text]
    parts = [p.strip() for p in _CLAUSE_SPLIT_RE.split(text) if p.strip()]
    return parts if len(parts) > 1 else [text]


class StreamingTranslationRouter:
    """Per-session translation orchestrator (Tầng A-E).

    Boundary detection (B) gates interim dispatch; fast-path engine (C) streams
    tokens; post-processor (E) cleans output; buffer (C-store) tracks 3 layers;
    translation_update delta events drive the layered UI.
    """

    def __init__(
        self,
        engine: BaseEngine,
        tts_dispatcher=None,
        tts_voice: str = "af_sarah",
        wait_final: bool = False,
        sid: str = "",
    ) -> None:
        self._engine = engine
        self._detector = TranslationUnitDetector()
        self._buffer = TranslationBuffer()
        self._post = PostProcessor()
        self._punct = VietnamesePunctuator()
        self._tts = tts_dispatcher
        self._tts_voice = tts_voice
        self._session_id = str(uuid.uuid4())[:12]
        self._sid = sid or self._session_id[:8]

        # [RES] observability: count of in-flight translate_stream() calls
        # (_translate_committed + _retranslate_chunk), diagnostic-only.
        self._active_translations = 0
        self._active_lock = threading.Lock()

        # wait_final: when True (PhoWhisper accuracy backend), translation + TTS
        # fire ONLY on PhoWhisper-confirmed final segments — never on the live
        # Sherpa display stream. This eliminates the "speak then re-speak corrected
        # text" double-playback that streaming dispatch causes. Other (streaming)
        # backends keep the legacy committed-delta dispatch below.
        self._wait_final = wait_final

        # Session state — reset on new connection
        self._prev_committed = ""
        self._prev_interim = ""

        # Punctuated display version of committed text (sent to UI via SYNC)
        self._committed_display: str = ""

        # Committed translation: track frontier so we only translate the delta
        # (new words added since last queued translation), never re-translate history.
        self._committed_queued_to: str = ""
        self._committed_gen: int = 0   # incremented on revision to invalidate old threads

        # Sentence accumulation: batch committed deltas into sentence-sized chunks
        # before dispatching to the translation engine.
        self._sentence_buf: str = ""
        self._sentence_word_count: int = 0
        self._dispatched_chunks: list[tuple[str, int]] = []

        # Cancellation event for in-flight interim thread
        self._i_cancel: threading.Event | None = None

        # Monotonic counter so the client can drop stale interim tokens
        self._interim_gen: int = 0

        # Maps an STT segment id -> its committed translation chunk id, so a later
        # PhoWhisper correction can re-translate that exact chunk in place.
        self._seg_to_chunk: dict[str, str] = {}

        # Maps a committed translation chunk id -> diarized speaker index, injected
        # into translation_update deltas so the UI can color-code speakers.
        self._chunk_speaker: dict[str, int] = {}

        # Cross-segment context: last 50 chars of committed EN output, passed as
        # target_prefix to the translation engine so consecutive sentences flow
        # more naturally. Disabled when CONTEXT_DISABLED=1 in environment.
        self._last_en_tail: str = ""

    def reset(self) -> None:
        """Reset all per-session state. Call on new WebSocket connection."""
        if self._i_cancel:
            self._i_cancel.set()
        self._i_cancel = None
        self._committed_gen += 1      # signals all in-flight committed threads to stop
        self._committed_queued_to = ""
        self._committed_display = ""
        self._sentence_buf = ""
        self._sentence_word_count = 0
        self._prev_committed = ""
        self._prev_interim = ""
        self._buffer.clear_all()
        self._interim_gen = 0
        self._dispatched_chunks.clear()
        self._seg_to_chunk.clear()
        self._chunk_speaker.clear()
        self._last_en_tail = ""
        if self._tts is not None:
            self._tts.cancel_session(self._session_id)

    def active_translations(self) -> int:
        """Number of in-flight translate_stream() calls (for [RES] logging)."""
        with self._active_lock:
            return self._active_translations

    def _enter_translation(self) -> None:
        with self._active_lock:
            self._active_translations += 1

    def _exit_translation(self) -> None:
        with self._active_lock:
            self._active_translations -= 1

    def set_voice(self, voice: str) -> None:
        """Change the TTS voice used for subsequently-dispatched utterances."""
        if voice:
            self._tts_voice = voice

    def _delta(self) -> dict:
        """Buffer delta with the diarized speaker index attached to each committed
        chunk (0 when diarization is unavailable)."""
        delta = self._buffer.to_delta()
        for chunk in delta.get("committed", []):
            chunk["speaker"] = self._chunk_speaker.get(chunk["id"], 0)
        return delta

    def on_stt_update(
        self,
        committed: str,
        interim: str,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        src_lang: str = "vi",
        tgt_lang: str = "en",
        silence_ms: int = 0,
        is_final: bool = False,
        final_text: str = "",
        seg_id: str = "",
        correction: str = "",
        speaker: int = 0,
        stt_ms: "int | str" = "n/a",
    ) -> None:
        """Called from the STT callback thread. Schedules work on the event loop."""
        loop.call_soon_threadsafe(
            self._schedule,
            committed, interim, loop, send_q, src_lang, tgt_lang, silence_ms,
            is_final, final_text, seg_id, correction, speaker, stt_ms,
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _schedule(
        self,
        committed: str,
        interim: str,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        src_lang: str,
        tgt_lang: str,
        silence_ms: int = 0,
        is_final: bool = False,
        final_text: str = "",
        seg_id: str = "",
        correction: str = "",
        speaker: int = 0,
        stt_ms: "int | str" = "n/a",
    ) -> None:
        committed_changed = committed != self._prev_committed
        interim_changed = interim != self._prev_interim

        if not committed_changed and not interim_changed and not is_final and not correction:
            return

        # ── Update + emit the punctuated display (both modes) ────────────────
        if committed_changed:
            self._update_display(committed, silence_ms)
        send_q.put_nowait({
            "type": "sync",
            "committed": self._committed_display,
            "interim": interim,
            "speaker": speaker,
        })

        # ── Wait-final mode: translate + TTS ONLY on confirmed segments ──────
        # The live Sherpa stream drives the display above but never triggers
        # translation/TTS, so audio that was already spoken is never re-spoken.
        if self._wait_final:
            if committed_changed:
                self._prev_committed = committed
            if interim_changed or committed_changed:
                self._prev_interim = interim
            if is_final and final_text and final_text.strip():
                self._dispatch_final(final_text.strip(), src_lang, tgt_lang, loop, send_q, seg_id, speaker)
            elif correction and correction.strip() and seg_id:
                # PhoWhisper refined this segment — re-translate its chunk in place
                # (display only). No TTS: the Sherpa audio already played.
                self._dispatch_correction(seg_id, correction.strip(), src_lang, tgt_lang, loop, send_q)
            return

        # ── Streaming mode (sherpa/dual/whisper): legacy committed-delta ─────
        if committed_changed:
            self._prev_committed = committed

            if committed:
                is_revision = False
                if committed.startswith(self._committed_queued_to):
                    new_text = committed[len(self._committed_queued_to):].strip()
                else:
                    # Partial Revision: only drop translation chunks affected by the STT correction
                    old_words = self._committed_queued_to.split()
                    new_words = committed.split()
                    
                    prefix_len = 0
                    for o, n in zip(old_words, new_words):
                        if o == n: prefix_len += 1
                        else: break
                        
                    dispatched_word_count = sum(c_len for _, c_len in self._dispatched_chunks)
                    
                    if prefix_len < dispatched_word_count:
                        # Roll back dispatched chunks that overlap with the correction
                        words_to_discard = dispatched_word_count - prefix_len
                        discarded = 0
                        while words_to_discard > 0 and self._dispatched_chunks:
                            cid, c_len = self._dispatched_chunks.pop()
                            self._buffer.remove_committed_chunk(cid)
                            discarded += c_len
                            words_to_discard -= c_len
                        
                        safe_prefix_len = max(0, dispatched_word_count - discarded)
                        self._committed_gen += 1  # Stop threads translating discarded chunks
                    else:
                        safe_prefix_len = dispatched_word_count
                        
                    self._committed_queued_to = " ".join(old_words[:safe_prefix_len])
                    self._sentence_buf = ""
                    self._sentence_word_count = 0
                    
                    new_text = " ".join(new_words[safe_prefix_len:])
                    is_revision = True

                if new_text:
                    self._committed_queued_to = committed
                    sep = " " if self._sentence_buf else ""
                    self._sentence_buf = self._sentence_buf + sep + new_text
                    self._sentence_word_count += len(new_text.split())

                    should_dispatch = (
                        is_revision
                        or self._punct.has_sentence_end(self._sentence_buf)
                        or (self._sentence_buf and self._sentence_buf[-1] in ".?!…。！？")
                        or self._sentence_word_count >= _SENTENCE_DISPATCH_WORDS
                        or silence_ms >= _LONG_PAUSE_MS
                    )

                    if should_dispatch:
                        # Punctuate before sending to translation so the model
                        # receives a complete sentence, not a raw word stream.
                        dispatch_text = self._punct.punctuate(
                            self._sentence_buf, is_commit_boundary=True
                        )
                        chunk_word_count = self._sentence_word_count
                        self._sentence_buf = ""
                        self._sentence_word_count = 0
                        gen = self._committed_gen
                        chunk_id = str(uuid.uuid4())[:8]
                        self._dispatched_chunks.append((chunk_id, chunk_word_count))
                        self._buffer.clear_volatile()
                        self._buffer.add_chunk(chunk_id, "", ChunkState.committed)

                        t_lock = time.monotonic()
                        threading.Thread(
                            target=self._translate_committed,
                            args=(dispatch_text, src_lang, tgt_lang, chunk_id, gen, loop, send_q, t_lock),
                            kwargs={"stt_ms": stt_ms},
                            daemon=True,
                        ).start()
            else:
                self._committed_gen += 1
                self._committed_queued_to = ""
                self._sentence_buf = ""
                self._sentence_word_count = 0
                self._buffer.clear_all()

        # ── Interim changed → translate if boundary is ready ──────────────────
        if interim_changed or committed_changed:
            self._prev_interim = interim

            # Cancel previous interim thread
            if self._i_cancel:
                self._i_cancel.set()
            self._interim_gen += 1
            gen = self._interim_gen

            # Clear volatile interim layer in buffer
            self._buffer.clear_volatile()
            send_q.put_nowait({"type": "clear_trans_i"})

            if interim and self._detector.is_translatable_boundary(interim, src_lang):
                i_event = threading.Event()
                self._i_cancel = i_event
                full_text = (committed + " " + interim).strip()
                v_id = str(uuid.uuid4())[:8]
                self._buffer.add_chunk(v_id, "", ChunkState.volatile_interim)

                threading.Thread(
                    target=self._translate_interim,
                    args=(full_text, src_lang, tgt_lang, v_id, gen, loop, send_q, i_event),
                    daemon=True,
                ).start()
            else:
                self._i_cancel = None
                # Emit delta with empty volatile (so UI clears the volatile layer)
                send_q.put_nowait({
                    "type": "translation_update",
                    "delta": self._delta(),
                })

    # ── Display + wait-final dispatch ─────────────────────────────────────────

    def _update_display(self, committed: str, silence_ms: int) -> None:
        """Maintain the punctuated committed display text shown in the UI.

        Display-only — independent of translation/TTS dispatch. Silence duration
        drives punctuation: long pause → period, short → comma.
        """
        if not committed:
            self._committed_display = ""
            return
        long_pause = silence_ms >= _LONG_PAUSE_MS
        short_pause = _SHORT_PAUSE_MS <= silence_ms < _LONG_PAUSE_MS
        if committed.startswith(self._prev_committed):
            raw_delta = committed[len(self._prev_committed):].strip()
            is_eou = long_pause or self._punct.has_sentence_end(raw_delta) or (raw_delta and raw_delta[-1] in ".?!…。！？")
            punct_delta = self._punct.punctuate(
                raw_delta, is_commit_boundary=is_eou, short_pause=short_pause and not is_eou
            )
            sep = " " if self._committed_display else ""
            self._committed_display = self._committed_display + sep + punct_delta
        else:
            # Revision (e.g. PhoWhisper corrected an earlier segment) — rebuild.
            is_eou = long_pause or self._punct.has_sentence_end(committed) or (committed and committed[-1] in ".?!…。！？")
            self._committed_display = self._punct.punctuate(
                committed, is_commit_boundary=is_eou, short_pause=short_pause and not is_eou
            )

    def _dispatch_final(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        seg_id: str = "",
        speaker: int = 0,
    ) -> None:
        """Translate + speak one Sherpa-committed segment, exactly once.

        Long sentences are split at comma boundaries so each clause translates
        independently — prevents 50-word sentences from causing 12s+ latency.
        """
        if len(text.split()) < _MIN_DISPATCH_WORDS:
            return
        text = filter_profanity(text)
        dispatch_text = self._punct.punctuate(text, is_commit_boundary=True)
        clauses = _split_clauses(dispatch_text)
        _log.info("[Router] dispatch_final | seg=%s words=%d clauses=%d src=%r",
                  seg_id or "-", len(text.split()), len(clauses), text[:60])
        gen = self._committed_gen
        for i, clause in enumerate(clauses):
            if not clause.strip():
                continue
            chunk_id = str(uuid.uuid4())[:8]
            self._chunk_speaker[chunk_id] = speaker   # for diarized UI coloring
            if i == 0 and seg_id:
                self._seg_to_chunk[seg_id] = chunk_id  # link first clause for PhoWhisper
            self._buffer.add_chunk(chunk_id, "", ChunkState.committed)
            t_lock = time.monotonic()
            threading.Thread(
                target=self._translate_committed,
                args=(clause, src_lang, tgt_lang, chunk_id, gen, loop, send_q, t_lock),
                daemon=True,
            ).start()

    def _dispatch_correction(
        self,
        seg_id: str,
        corrected_vi: str,
        src_lang: str,
        tgt_lang: str,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
    ) -> None:
        """Re-translate a PhoWhisper-corrected segment and revise its committed
        chunk in place — DISPLAY ONLY, never re-speaks (the Sherpa audio played)."""
        chunk_id = self._seg_to_chunk.get(seg_id)
        if not chunk_id:
            return   # segment was never dispatched (too short / not found)
        dispatch_text = self._punct.punctuate(corrected_vi, is_commit_boundary=True)
        gen = self._committed_gen
        threading.Thread(
            target=self._retranslate_chunk,
            args=(dispatch_text, src_lang, tgt_lang, chunk_id, gen, loop, send_q),
            daemon=True,
        ).start()

    def _retranslate_chunk(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        chunk_id: str,
        gen: int,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
    ) -> None:
        """Translate corrected text and revise an existing committed chunk in place.
        No token streaming, no TTS — just a quiet in-place text update for the UI."""
        nllb_src = _lang_to_nllb(src_lang)
        nllb_tgt = _lang_to_nllb(tgt_lang)
        accumulated = ""
        prefix = "" if _CONTEXT_DISABLED else self._last_en_tail
        t_translate_start = time.monotonic()
        self._enter_translation()
        try:
            try:
                for tok in self._engine.translate_stream(text, nllb_src, nllb_tgt, target_prefix=prefix):
                    if self._committed_gen != gen:
                        return
                    accumulated += tok
            except Exception as exc:
                _log.warning("[Router] correction translate error: %s", exc)
                return
        finally:
            self._exit_translation()
        if self._committed_gen != gen:
            return
        final_text = self._post.process(accumulated, tgt_lang)
        if not self._buffer.revise_committed_chunk(chunk_id, final_text):
            return   # chunk gone (reset) — drop silently
        translate_ms = round((time.monotonic() - t_translate_start) * 1000)
        # Correction never re-triggers TTS (display-only revision) -> no cụm/audio timing.
        olog("SEG", sid=self._sid, kind="correction", seg=chunk_id, src=text, tgt=final_text,
             stt_ms="n/a", translate_ms=translate_ms, words=len(text.split()),
             model=type(self._engine).__name__, cum=0,
             tts_first="n/a", tts_done="n/a", e2e_first_audio="n/a")
        loop.call_soon_threadsafe(send_q.put_nowait, {
            "type": "translation_update",
            "delta": self._delta(),
        })

    def _translate_committed(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        chunk_id: str,
        gen: int,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        t_lock: float,
        stt_ms: "int | str" = "n/a",
    ) -> None:
        nllb_src = _lang_to_nllb(src_lang)
        nllb_tgt = _lang_to_nllb(tgt_lang)
        accumulated = ""
        t_translate_start = time.monotonic()

        tts_enabled = self._tts is not None and tgt_lang == "en"
        prefix = "" if _CONTEXT_DISABLED else self._last_en_tail

        # Incremental cụm dispatch: last_dispatch_idx is the char offset into
        # `accumulated` up to which text has already been sent to TTS. Each new
        # cụm is the tail since last_dispatch_idx; seq counts dispatched cụm
        # (seq == 0 -> first cụm, gets capitalized; later ones don't).
        last_dispatch_idx: int = 0
        seq: int = 0
        first_chunk_cb_attached = False

        def _dispatch_cum(tail_text: str) -> bool:
            nonlocal seq, first_chunk_cb_attached
            tail_text = tail_text.strip()
            if not tail_text:
                return False
            if self._tts.pending_count(self._session_id) >= _TTS_MAX_QUEUE:
                return False
            clip = self._post.process(tail_text, tgt_lang, capitalize=(seq == 0))
            if not clip:
                return False
            on_first_chunk = None
            if not first_chunk_cb_attached:
                first_chunk_cb_attached = True

                def on_first_chunk() -> None:
                    t_first_audio = time.monotonic()
                    loop.call_soon_threadsafe(send_q.put_nowait, {
                        "type": "latency",
                        "utterance_id": chunk_id,
                        "first_audio_ms": round((t_first_audio - t_lock) * 1000),
                    })

            self._tts.dispatch(
                text=clip,
                session_id=self._session_id,
                utterance_id=f"{chunk_id}-{seq}",
                loop=loop,
                send_q=send_q,
                voice=self._tts_voice,
                on_first_chunk=on_first_chunk,
            )
            seq += 1
            return True

        self._enter_translation()
        try:
            try:
                for tok in self._engine.translate_stream(text, nllb_src, nllb_tgt, target_prefix=prefix):
                    if self._committed_gen != gen:
                        return
                    accumulated += tok
                    loop.call_soon_threadsafe(send_q.put_nowait, {"type": "trans_stream_c", "token": tok})

                    # Incremental TTS: dispatch each cụm (clause/phrase chunk) as soon
                    # as its boundary is reached, so Kokoro can start synthesizing the
                    # first cụm while NLLB is still decoding the rest of the sentence.
                    if tts_enabled:
                        tail = accumulated[last_dispatch_idx:]
                        n = len(tail.split())
                        at_boundary = tail.rstrip()[-1:] in _EARLY_TTS_BOUNDARY
                        if (n >= _EARLY_TTS_WORDS and at_boundary) or n >= _EARLY_TTS_HARD:
                            # Hold back the last few words so the eventual final
                            # remainder isn't a 1-2 word fragment.
                            dispatch_text = tail.rsplit(None, _TAIL_HOLDBACK_WORDS)[0]
                            if _dispatch_cum(dispatch_text):
                                last_dispatch_idx += len(dispatch_text)
            except Exception as exc:
                _log.warning("[Router] committed translate error: %s", exc)
                return
        finally:
            self._exit_translation()

        if self._committed_gen != gen:
            return

        t_translate_done = time.monotonic()
        translate_ms = round((t_translate_done - t_translate_start) * 1000)
        chunk_words = len(text.split())

        _log.info("[Router] translate | chunk=%s words=%d translate_ms=%d model=%s tts_enabled=%s",
                  chunk_id, chunk_words, translate_ms,
                  type(self._engine).__name__, tts_enabled)

        # Post-process and update committed buffer slot
        final_text = self._post.process(accumulated, tgt_lang)
        self._last_en_tail = final_text[-50:]
        self._buffer.commit_chunk(chunk_id, final_text)
        loop.call_soon_threadsafe(send_q.put_nowait, {
            "type": "translation_update",
            "delta": self._delta(),
        })

        # ── TTS dispatch: remaining tail (or the whole sentence if nothing was
        # dispatched yet) ────────────────────────────────────────────────────
        if tts_enabled:
            _dispatch_cum(accumulated[last_dispatch_idx:])

        # [SEG] emitted after TTS dispatch so `cum` reflects the final cụm
        # count. tts_first/tts_done/e2e_first_audio land in GĐ2 once TTS dub
        # timing callbacks exist; n/a while TTS is disabled/not dubbing.
        olog("SEG", sid=self._sid, kind="final", seg=chunk_id, src=text, tgt=final_text,
             stt_ms=stt_ms, translate_ms=translate_ms, words=chunk_words,
             model=type(self._engine).__name__, cum=seq,
             tts_first="n/a", tts_done="n/a", e2e_first_audio="n/a")

        # ── Latency telemetry ─────────────────────────────────────────────────
        loop.call_soon_threadsafe(send_q.put_nowait, {
            "type": "latency",
            "utterance_id": chunk_id,
            "translate_ms": translate_ms,
            "chunk_words": chunk_words,
        })
        _log.info("[Router] chunk=%s  words=%d  translate=%dms  cụm=%d",
                  chunk_id, chunk_words, translate_ms, seq)

    def _translate_interim(
        self,
        full_text: str,
        src_lang: str,
        tgt_lang: str,
        chunk_id: str,
        gen: int,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        cancel: threading.Event,
    ) -> None:
        nllb_src = _lang_to_nllb(src_lang)
        nllb_tgt = _lang_to_nllb(tgt_lang)
        accumulated = ""
        try:
            for tok in self._engine.translate_stream(full_text, nllb_src, nllb_tgt):
                if cancel.is_set():
                    return
                accumulated += tok
                # Include gen so client can drop tokens from superseded interim streams
                loop.call_soon_threadsafe(send_q.put_nowait, {
                    "type": "trans_stream_i",
                    "token": tok,
                    "gen": gen,
                })
        except Exception as exc:
            _log.warning("[Router] interim translate error: %s", exc)
            return

        if cancel.is_set():
            return

        # Post-process and update volatile buffer slot
        final_text = self._post.process(accumulated, tgt_lang)
        self._buffer.replace_volatile(chunk_id, final_text)
        loop.call_soon_threadsafe(send_q.put_nowait, {
            "type": "translation_update",
            "delta": self._delta(),
        })


# ── Language code mapping ─────────────────────────────────────────────────────

_LANG_MAP: dict[str, str] = {
    "vi": "vie_Latn",
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "th": "tha_Thai",
}


def _lang_to_nllb(lang: str) -> str:
    code = _LANG_MAP.get(lang)
    if code is None:
        raise ValueError(f"[Router] unsupported language code: {lang!r}")
    return code
