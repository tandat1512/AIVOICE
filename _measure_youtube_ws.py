from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import av
import numpy as np
import websockets
from av.audio.resampler import AudioResampler


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "_measure_cache"
YOUTUBE_URL = "https://www.youtube.com/watch?v=6drAJkT6h-E&t=42s"


def stream_url(page_url: str) -> str:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--js-runtimes",
        "node",
        "--no-progress",
        "--no-playlist",
        "-f",
        "ba[ext=m4a]/ba",
        "-g",
        page_url,
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, encoding="utf-8")
    for line in proc.stdout.splitlines():
        if line.startswith("http"):
            return line
    raise RuntimeError("yt-dlp did not return an audio stream URL")


def soft_limit(samples: np.ndarray) -> np.ndarray:
    samples = samples * 1.5
    abs_samples = np.abs(samples)
    limited = samples.copy()
    over = abs_samples > 0.85
    limited[over] = np.sign(samples[over]) * (
        0.85 + 0.15 * np.tanh((abs_samples[over] - 0.85) / 0.15)
    )
    return np.clip(limited, -1.0, 1.0)


def decode_pcm16(url: str, start_s: float, duration_s: float) -> np.ndarray:
    container = av.open(url)
    stream = container.streams.audio[0]
    resampler = AudioResampler(format="flt", layout="mono", rate=16000)
    container.seek(int(start_s * av.time_base))

    chunks: list[np.ndarray] = []
    target_samples = int(duration_s * 16000)
    collected = 0
    for packet in container.demux(stream):
        for frame in packet.decode():
            if frame.pts is not None and frame.time_base is not None:
                frame_t = float(frame.pts * frame.time_base)
                if frame_t + float((frame.samples or 0) * frame.time_base) < start_s:
                    continue
            for out in resampler.resample(frame):
                arr = out.to_ndarray().astype(np.float32).reshape(-1)
                if not arr.size:
                    continue
                chunks.append(arr)
                collected += arr.size
                if collected >= target_samples:
                    audio = np.concatenate(chunks)[:target_samples]
                    audio = soft_limit(audio)
                    return (audio * 32767.0).astype(np.int16)
    raise RuntimeError(f"decoded only {collected / 16000:.1f}s from stream")


async def run_measure(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    events_path = OUT_DIR / "youtube_ws_events.jsonl"
    tts_path = OUT_DIR / "youtube_ws_tts.pcm"
    for path in (events_path, tts_path):
        path.unlink(missing_ok=True)

    print(f"[measure] resolving YouTube audio URL: {args.url}", flush=True)
    direct = stream_url(args.url)
    print(f"[measure] decoding start={args.start_s:.1f}s duration={args.duration_s:.1f}s", flush=True)
    pcm = decode_pcm16(direct, args.start_s, args.duration_s)
    print(f"[measure] decoded samples={pcm.size} seconds={pcm.size / 16000:.1f}", flush=True)

    async with websockets.connect(args.ws, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "config",
            "src": "vi",
            "tgt": "en",
            "backend": "phowhisper",
            "translate_model": "nllb-600m",
            "voice": "",
            "vad": 500,
        }))

        start = time.perf_counter()
        stop_recv = asyncio.Event()
        text_events = 0
        binary_events = 0
        tts_bytes = 0

        async def recv_loop() -> None:
            nonlocal text_events, binary_events, tts_bytes
            with events_path.open("a", encoding="utf-8") as events, tts_path.open("ab") as tts:
                while not stop_recv.is_set():
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    t = round(time.perf_counter() - start, 3)
                    if isinstance(msg, bytes):
                        binary_events += 1
                        tts_bytes += len(msg)
                        tts.write(msg)
                        events.write(json.dumps({"t": t, "type": "tts_binary", "bytes": len(msg)}) + "\n")
                    else:
                        text_events += 1
                        try:
                            data = json.loads(msg)
                        except json.JSONDecodeError:
                            data = {"type": "raw", "text": msg}
                        data["t"] = t
                        events.write(json.dumps(data, ensure_ascii=False) + "\n")
                    events.flush()

        recv_task = asyncio.create_task(recv_loop())

        frame = 320
        target_next = time.perf_counter()
        sent = 0
        for offset in range(0, pcm.size, frame):
            chunk = pcm[offset:offset + frame]
            if chunk.size < frame:
                break
            await ws.send(chunk.tobytes())
            sent += 1
            target_next += 0.02
            await asyncio.sleep(max(0, target_next - time.perf_counter()))

        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(args.drain_s)
        stop_recv.set()
        await recv_task

    print(
        f"[measure] sent_chunks={sent} text_events={text_events} "
        f"tts_binary_events={binary_events} tts_bytes={tts_bytes}",
        flush=True,
    )
    print(f"[measure] events={events_path}", flush=True)
    print(f"[measure] tts_pcm={tts_path}", flush=True)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=YOUTUBE_URL)
    ap.add_argument("--ws", default="ws://localhost:8000/ws")
    ap.add_argument("--start-s", type=float, default=42.0)
    ap.add_argument("--duration-s", type=float, default=75.0)
    ap.add_argument("--drain-s", type=float, default=12.0)
    return ap.parse_args()


if __name__ == "__main__":
    asyncio.run(run_measure(parse_args()))
