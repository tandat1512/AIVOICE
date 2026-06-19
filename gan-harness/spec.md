# SmartGen Extension — Real-Time Translation UI

## Product Context

SmartGen is a real-time Vietnamese → English translation system. Users run it in the browser while on Google Meet calls or watching YouTube. It:
- Captures tab audio (Google Meet audio, YouTube playback)
- Streams audio to a local WebSocket server (localhost:8000)
- Shows live Vietnamese transcript + English translation side-by-side
- Speaks the translation via TTS

## What to Design

Two deliverables, delivered as self-contained HTML files with embedded CSS + vanilla JS:

### 1. `extension/popup.html` — Extension Popup (360×580px)
The popup that opens when the user clicks the extension icon in Chrome toolbar. Contains:
- Header with logo/name "SmartGen" and a status indicator
- Primary action: Start / Stop translation button (prominent)
- Source audio selector: Mic or Tab audio
- STT model selector (phowhisper / sherpa)
- Translation model selector (Marian 77M / NLLB 600M / NLLB 1.3B)
- TTS voice selector + mute toggle + speed slider
- Language selectors: src (vi/en/zh/ja/ko) and tgt (en/vi/zh/ja/ko)
- Live status: "idle" / "connecting" / "listening" / "translating"
- Mini transcript preview (last 2 lines, truncated)
- Debug toggle (shows/hides latency metrics)

### 2. `extension/overlay.html` — Floating Page Overlay
A floating widget injected into the page (Google Meet or YouTube). Draggable.
- Minimal collapsed state: just a pulsing indicator + one line of live translation
- Expanded state: full transcript + translation panel (like a subtitle card)
- Smooth expand/collapse toggle
- Position: bottom-right of screen by default, draggable anywhere
- Auto-collapses when no speech detected for 3s

## Design Direction

**DO NOT** make a generic material design / shadcn / bootstrap interface.

**Visual language to target:**
- Dark, premium, immersive
- Glassmorphism with real depth (layered blur + translucency, not just one opaque card)
- Bioluminescent accent colors: deep indigo → electric cyan → soft white glow
- Typography: tight, editorial, confident (think Vercel / Linear / Figma UI)
- Micro-animations: waveform pulse during speech, token-by-token text reveal, status transitions
- The overlay should feel like a professional live-caption tool (AI-native, not amateur)

**Interaction quality:**
- Hover states that feel designed
- Start button should feel special (glow, pulse-ring animation when active)
- Translation text animates in word-by-word
- Latency metrics shown as subtle mono-font numbers
- The whole thing should look good screenshotted next to a Google Meet call

## Technical Constraints

- Self-contained HTML: no external CDN dependencies (embed any fonts as base64 or use system fonts with smart fallback)
- CSS custom properties for theming
- Pure vanilla JS (no frameworks)
- The overlay must have `position: fixed` and `z-index: 999999`
- WebSocket connection to `ws://localhost:8000/ws`

## Acceptance Signals

The design succeeds if:
- A senior designer looking at a screenshot would say "this looks like a real product"
- The overlay doesn't look jarring next to a Google Meet call
- The popup feels native to a modern browser extension (not a webpage shrunken to 360px)
- Animations are smooth and purposeful, not gimmicky
