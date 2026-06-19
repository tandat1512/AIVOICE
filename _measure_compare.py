"""Việc 4: compare _measure_v1.json vs _measure_v2.json.

Reports:
  (a) mid-clause cut-rate: how many of the pause_mid_* boundaries produced an
      is_final commit in v1 vs v2.
  (b) lock latency: for each pause_boundary_* marker, time from "speech ends"
      (marker) to the matching is_final commit, v1 vs v2.
  (c) the s4 (>_MAX_SPEECH_S, no-pause) segment texts for both modes, to
      inspect where the force-cut happened.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent

v1 = json.loads((ROOT / "_measure_v1.json").read_text(encoding="utf-8"))
v2 = json.loads((ROOT / "_measure_v2.json").read_text(encoding="utf-8"))

# Window after a marker within which a commit is attributed to that boundary.
WINDOW_S = 1.2


def commit_near(events, marker_t):
    cands = [e for e in events if marker_t - 0.05 <= e["t"] <= marker_t + WINDOW_S]
    if not cands:
        return None
    return min(cands, key=lambda e: e["t"])


for label, data in (("v1", v1), ("v2", v2)):
    print(f"\n=== {label} ===")
    print(f"total_audio_s = {data['total_audio_s']:.2f}")
    for e in data["events"]:
        print(f"  t={e['t']:6.3f}s  silence_ms={e['silence_ms']:4d}  text={e['text']!r}")

print("\n--- (a) mid-clause cut rate ---")
mid_labels = [k for k in v1["markers_s"] if k.startswith("pause_mid")]
for label in mid_labels:
    m1 = v1["markers_s"][label]
    m2 = v2["markers_s"][label]
    c1 = commit_near(v1["events"], m1)
    c2 = commit_near(v2["events"], m2)
    suffix1 = f" (t={c1['t']:.3f})" if c1 else ""
    suffix2 = f" (t={c2['t']:.3f})" if c2 else ""
    print(f"  {label}: v1 {'CUT' if c1 else 'no cut'}{suffix1}"
          f"  |  v2 {'CUT' if c2 else 'no cut'}{suffix2}")

n_mid = len(mid_labels)
v1_cuts = sum(1 for label in mid_labels if commit_near(v1["events"], v1["markers_s"][label]))
v2_cuts = sum(1 for label in mid_labels if commit_near(v2["events"], v2["markers_s"][label]))
print(f"  mid-clause cut rate: v1 {v1_cuts}/{n_mid} = {v1_cuts/n_mid:.0%}"
      f"   v2 {v2_cuts}/{n_mid} = {v2_cuts/n_mid:.0%}")

print("\n--- (b) lock latency at sentence-boundary pauses ---")
boundary_labels = [k for k in v1["markers_s"] if k.startswith("pause_boundary")]
deltas = []
for label in boundary_labels:
    m1 = v1["markers_s"][label]
    m2 = v2["markers_s"][label]
    c1 = commit_near(v1["events"], m1)
    c2 = commit_near(v2["events"], m2)
    lat1 = (c1["t"] - m1) * 1000 if c1 else None
    lat2 = (c2["t"] - m2) * 1000 if c2 else None
    str1 = f"{lat1:.0f}ms" if lat1 is not None else "n/a"
    str2 = f"{lat2:.0f}ms" if lat2 is not None else "n/a"
    if lat1 is not None and lat2 is not None:
        deltas.append(lat2 - lat1)
    delta_str = f"{lat2 - lat1:+.0f}ms" if lat1 is not None and lat2 is not None else "n/a"
    print(f"  {label}: v1 lock_latency={str1}   v2 lock_latency={str2}  delta={delta_str}")

if deltas:
    print(f"  avg lock-latency increase (v2 - v1): {sum(deltas)/len(deltas):.0f}ms over {len(deltas)} boundaries")

print("\n--- (c) s4 (>_MAX_SPEECH_S, no-pause) segment texts ---")
s4_start = v1["markers_s"]["pause_boundary_3"]
s4_end = v1["markers_s"]["pause_boundary_4"]
for label, data in (("v1", v1), ("v2", v2)):
    segs = [e for e in data["events"] if s4_start <= e["t"] <= s4_end + WINDOW_S]
    print(f"  {label}: {len(segs)} segment(s)")
    for e in segs:
        print(f"    t={e['t']:.3f}s silence_ms={e['silence_ms']} text={e['text']!r}")
