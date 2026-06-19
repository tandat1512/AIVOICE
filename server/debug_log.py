"""Structured debug logger for the AIVOICE pipeline.

Enable with DEBUG_LOG=1 environment variable.
Format: [HH:MM:SS.mmm][COMPONENT][sid=xxxx] EVENT | key=value ...

Observability log (olog): enable with LOG_OBS=1 environment variable.
Format: [TAG][sid=xxxx] key=value ... — TAG is one of CFG/SEG/RES.
"""
from __future__ import annotations

import logging
import os
import time

_enabled = os.environ.get("DEBUG_LOG", "0") == "1"
_obs_enabled = os.environ.get("LOG_OBS", "0") == "1"

# Configure only our logger. Do not force root DEBUG because python-multipart
# and other libraries become extremely noisy during uploads.
if _enabled:
    logging.getLogger("aivoice.debug").setLevel(logging.DEBUG)
    logging.getLogger("multipart").setLevel(logging.WARNING)
    logging.getLogger("python_multipart").setLevel(logging.WARNING)

_log = logging.getLogger("aivoice.debug")

# olog() goes through logging (not print) because plain print() from the
# NLLB translation worker threads doesn't reliably reach captured stdout
# (ctranslate2 fiddles with stdio fds during translate_stream), whereas
# logging.StreamHandler output from those same threads does.
_obs_log = logging.getLogger("aivoice.obs")
_obs_log.propagate = False
if _obs_enabled:
    _obs_log.setLevel(logging.INFO)
    _obs_handler = logging.StreamHandler()
    _obs_handler.setFormatter(logging.Formatter("%(message)s"))
    _obs_log.addHandler(_obs_handler)


def dlog(component: str, event: str, sid: str = "-", **kv) -> None:
    """Emit one structured log line. No-op when DEBUG_LOG != 1."""
    if not _enabled:
        return
    ms = int(time.time() * 1000) % 1000
    ts = time.strftime("%H:%M:%S") + f".{ms:03d}"
    pairs = "  ".join(f"{k}={v}" for k, v in kv.items())
    msg = f"[{ts}][{component}][sid={sid}] {event}"
    if pairs:
        msg += f" | {pairs}"
    print(msg, flush=True)


def is_enabled() -> bool:
    return _enabled


def olog(tag: str, sid: str = "-", **kv) -> None:
    """Emit one [TAG][sid=xxxx] key=value line. No-op when LOG_OBS != 1."""
    if not _obs_enabled:
        return
    pairs = " ".join(f"{k}={v}" for k, v in kv.items())
    msg = f"[{tag}][sid={sid}]"
    if pairs:
        msg += f" {pairs}"
    _obs_log.info(msg)


def obs_enabled() -> bool:
    return _obs_enabled
