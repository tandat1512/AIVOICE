"""GD1 verification: stream test_audio_en.pcm over /ws (en->vi, whisper_en)
against the running server (LOG_OBS=1) and print received events. The
server's own stdout (separate process) is where [CFG]/[SEG]/[RES] lines
appear.
"""
import asyncio
import json
import sys
import time

import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WS_URL = "ws://localhost:8000/ws"
PCM_FILE = "test_audio_en.pcm"
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS / 1000)
TAIL_WAIT_S = 12


async def receiver(ws, t0):
    async for msg in ws:
        t = round(time.monotonic() - t0, 3)
        if isinstance(msg, (bytes, bytearray)):
            continue
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            continue
        ty = data.get("type")
        if ty == "sync":
            print(f"[{t:6.2f}] SYNC committed={data.get('committed','')!r} interim={data.get('interim','')!r}", flush=True)
        elif ty == "translation_update":
            for c in data.get("delta", {}).get("committed", []):
                print(f"[{t:6.2f}] TRANSLATION committed_chunk={c}", flush=True)
        elif ty == "latency":
            print(f"[{t:6.2f}] LATENCY {data}", flush=True)
        else:
            print(f"[{t:6.2f}] {ty}: {data}", flush=True)


async def main():
    t0 = time.monotonic()
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "config", "src": "en", "tgt": "vi", "backend": "whisper_en"}))
        recv_task = asyncio.create_task(receiver(ws, t0))

        with open(PCM_FILE, "rb") as f:
            data = f.read()

        print(f"[verify] streaming {len(data)/SAMPLE_RATE/BYTES_PER_SAMPLE:.2f}s of audio ...", flush=True)
        for i in range(0, len(data), CHUNK_BYTES):
            await ws.send(data[i:i + CHUNK_BYTES])
            await asyncio.sleep(CHUNK_MS / 1000)

        print("[verify] audio done, waiting for trailing translations ...", flush=True)
        await asyncio.sleep(TAIL_WAIT_S)
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass
    print("[verify] done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
