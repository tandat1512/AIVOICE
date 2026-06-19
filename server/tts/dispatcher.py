"""TTSDispatcher — submits text to a TTS engine and streams audio chunks back to
the WebSocket send queue, one utterance at a time per session.

Wire protocol (matches server/main.py sender expectations):

    {"type": "tts_start", "utterance_id": "u123", "sample_rate": 24000, "voice": "af_heart"}
    <binary PCM Int16 chunk>
    <binary PCM Int16 chunk>
    ...
    {"type": "tts_end",   "utterance_id": "u123", "chunks": 4}

    {"type": "tts_cancel","utterance_id": "u123"}    (sent on cancellation)
    {"type": "tts_error", "utterance_id": "u123", "msg": "..."}

Serial playback
---------------
Each session gets its own FIFO queue + single worker thread. Utterances for a
session are synthesized strictly one at a time, in dispatch order — so audio
never overlaps and chunks arrive in the order the user should hear them.

Cancellation
------------
Each utterance carries a unique utterance_id and an internal threading.Event.
    cancel_utterance(session_id, utterance_id) — single utterance
    cancel_session(session_id) — all utterances for one WebSocket session
                                 (drains the queue + stops the session worker)
The dispatcher emits a tts_cancel JSON event whenever an utterance stops early.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from typing import Callable, NamedTuple, Optional

from .engines.base import BaseTTSEngine


_log = logging.getLogger(__name__)

_STOP = None  # sentinel pushed onto a session queue to stop its worker


class _Job(NamedTuple):
    text: str
    voice: Optional[str]
    utterance_id: str
    cancel: threading.Event
    loop: asyncio.AbstractEventLoop
    send_q: asyncio.Queue
    session_id: str = ""
    on_first_chunk: Optional[Callable[[], None]] = None


class _Session:
    __slots__ = ("queue", "cancels", "thread")

    def __init__(self) -> None:
        self.queue: "queue.Queue[Optional[_Job]]" = queue.Queue()
        self.cancels: dict[str, threading.Event] = {}
        self.thread: Optional[threading.Thread] = None


class TTSDispatcher:
    """Per-session serial TTS worker with cancellation."""

    def __init__(self, engine: BaseTTSEngine) -> None:
        self._engine = engine
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    # ── public API ───────────────────────────────────────────────────────────

    def dispatch(
        self,
        *,
        text: str,
        session_id: str,
        utterance_id: str,
        loop: asyncio.AbstractEventLoop,
        send_q: asyncio.Queue,
        voice: Optional[str] = None,
        on_first_chunk: Optional[Callable[[], None]] = None,
    ) -> None:
        """Queue text for synthesis. Returns immediately; the session worker
        synthesizes utterances one at a time, in order.

        on_first_chunk: optional callback invoked (from the TTS worker thread)
        the first time a PCM chunk for this utterance is enqueued — used for
        first-audio latency telemetry.
        """
        text = (text or "").strip()
        if not text:
            return
        cancel = threading.Event()
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is None:
                sess = _Session()
                sess.thread = threading.Thread(
                    target=self._session_worker,
                    args=(session_id, sess),
                    daemon=True,
                    name=f"tts-{session_id[:6]}",
                )
                self._sessions[session_id] = sess
                sess.thread.start()
            sess.cancels[utterance_id] = cancel
            sess.queue.put(_Job(text, voice, utterance_id, cancel, loop, send_q, session_id, on_first_chunk))

    def pending_count(self, session_id: str) -> int:
        """Return the number of utterances queued (not yet synthesized) for a session."""
        with self._lock:
            sess = self._sessions.get(session_id)
            return sess.queue.qsize() if sess else 0

    def cancel_utterance(self, session_id: str, utterance_id: str) -> None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess and utterance_id in sess.cancels:
                sess.cancels[utterance_id].set()

    def cancel_session(self, session_id: str) -> None:
        """Cancel every utterance for a session, drain its queue, stop its worker."""
        with self._lock:
            sess = self._sessions.pop(session_id, None)
        if sess is None:
            return
        for ev in sess.cancels.values():
            ev.set()
        _drain(sess.queue)
        sess.queue.put(_STOP)   # wake the worker so it can exit

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for sess in sessions:
            for ev in sess.cancels.values():
                ev.set()
            _drain(sess.queue)
            sess.queue.put(_STOP)

    # ── worker ───────────────────────────────────────────────────────────────

    def _session_worker(self, session_id: str, sess: _Session) -> None:
        """Drain one session's queue, synthesizing utterances serially."""
        while True:
            job = sess.queue.get()
            if job is _STOP:
                return
            queue_depth = sess.queue.qsize()
            try:
                self._synthesize(job, queue_depth)
            except Exception as exc:  # noqa: BLE001 — never let the worker die
                _log.warning("[TTS] utterance %s crashed: %s", job.utterance_id, exc)
            finally:
                sess.cancels.pop(job.utterance_id, None)

    def _synthesize(self, job: _Job, queue_depth: int = 0) -> None:
        if job.cancel.is_set():
            return

        job.loop.call_soon_threadsafe(job.send_q.put_nowait, {
            "type": "tts_start",
            "utterance_id": job.utterance_id,
            "sample_rate": self._engine.sample_rate,
            "voice": job.voice or "",
        })

        chunks_sent = 0
        t0 = time.monotonic()
        try:
            for chunk in self._engine.synthesize_stream(job.text, job.voice or ""):
                if job.cancel.is_set():
                    break
                job.loop.call_soon_threadsafe(job.send_q.put_nowait, chunk)
                if chunks_sent == 0 and job.on_first_chunk is not None:
                    job.on_first_chunk()
                chunks_sent += 1
        except Exception as exc:  # noqa: BLE001 — surface to client
            _log.warning("[TTS] utterance %s failed: %s", job.utterance_id, exc)
            job.loop.call_soon_threadsafe(job.send_q.put_nowait, {
                "type": "tts_error",
                "utterance_id": job.utterance_id,
                "msg": str(exc),
            })
            return

        synth_ms = round((time.monotonic() - t0) * 1000)
        _log.info("[TTS] sid=%s u=%s synth_ms=%d chunks=%d queue_depth=%d words=%d",
                  job.session_id[:8] if job.session_id else "-",
                  job.utterance_id, synth_ms, chunks_sent, queue_depth,
                  len(job.text.split()))

        event = "tts_cancel" if job.cancel.is_set() else "tts_end"
        payload = {"type": event, "utterance_id": job.utterance_id}
        if event == "tts_end":
            payload["chunks"] = chunks_sent
        job.loop.call_soon_threadsafe(job.send_q.put_nowait, payload)


def _drain(q: "queue.Queue") -> None:
    """Remove all pending items from a queue without blocking."""
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass
