"""GD3: end-to-end measurement against the real running server.

Streams test_audio.pcm (16kHz Int16 mono) over /ws with backend=phowhisper
(Path B / wait_final), recording every WS event with a relative timestamp,
plus CPU% of the server process. Writes raw events to
_measure_e2e_studio.json for the GD3 metrics table.
"""
import asyncio
import json
import time

import psutil
import websockets

WS_URL = "ws://localhost:8000/ws"
PCM_FILE = "test_audio.pcm"
SERVER_PID = 5972
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS / 1000)
TAIL_WAIT_S = 15


async def cpu_sampler(stop: asyncio.Event, samples: list, t0: float) -> None:
    proc = psutil.Process(SERVER_PID)
    proc.cpu_percent(None)  # prime, first call returns 0
    while not stop.is_set():
        await asyncio.sleep(0.5)
        samples.append((round(time.monotonic() - t0, 3), proc.cpu_percent(None)))


async def receiver(ws, events: list, t0: float) -> None:
    async for msg in ws:
        t = round(time.monotonic() - t0, 3)
        if isinstance(msg, (bytes, bytearray)):
            events.append({"t": t, "type": "pcm_bytes", "n": len(msg)})
            continue
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            events.append({"t": t, "type": "raw", "msg": msg})
            continue
        events.append({"t": t, **data})


async def main() -> None:
    events: list = []
    cpu_samples: list = []
    t0 = time.monotonic()
    wall_start = time.strftime("%H:%M:%S")

    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "config", "src": "vi", "tgt": "en", "backend": "phowhisper",
        }))

        stop = asyncio.Event()
        recv_task = asyncio.create_task(receiver(ws, events, t0))
        cpu_task = asyncio.create_task(cpu_sampler(stop, cpu_samples, t0))

        with open(PCM_FILE, "rb") as f:
            data = f.read()

        for i in range(0, len(data), CHUNK_BYTES):
            await ws.send(data[i:i + CHUNK_BYTES])
            await asyncio.sleep(CHUNK_MS / 1000)

        await asyncio.sleep(TAIL_WAIT_S)
        stop.set()
        recv_task.cancel()
        cpu_task.cancel()
        for t in (recv_task, cpu_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    wall_end = time.strftime("%H:%M:%S")
    out = {
        "wall_start": wall_start,
        "wall_end": wall_end,
        "audio_bytes": len(data),
        "audio_s": len(data) / (SAMPLE_RATE * BYTES_PER_SAMPLE),
        "cpu_samples": cpu_samples,
        "events": events,
    }
    with open("_measure_e2e_studio.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wall_start={wall_start} wall_end={wall_end} events={len(events)} cpu_samples={len(cpu_samples)}")


if __name__ == "__main__":
    asyncio.run(main())
