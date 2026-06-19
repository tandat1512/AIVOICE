# Generator State — Iteration 003

## What Changed This Iteration (3 evaluator fixes)

### Fix 1 — Synapse fires a TRAVELING packet (Originality)
- popup + overlay: replaced the full-path opacity wipe with a real traveling dash.
- `stroke-dasharray: "14 <pathLen>"` so only a short 14px bright packet is visible.
- `stroke-dashoffset` animates `pathLen → -14` over 620ms (popup) / 600ms (overlay), so the packet enters at the left node and exits past the right node.
- Added a faint 40px trailing dash (`#fireTrail` / `#oTrail`) at 25% opacity, delayed ~100ms, for momentum.
- On arrival (~82% of travel) the EN node pulses: `#dotR` / `#oNodeR` scale 1→1.6→1 over 180ms plus a halo glow flash. Reads as "a signal crossed left→right."

### Fix 2 — Panel differentiation + SVG geometry (Design Quality)
- Radii retuned: `--r-lg` 18→16, `--r-xl` 26→20. Distinct values now used per surface.
- Primary `.panel.source`: cyan-tinted border `rgba(0,229,255,0.25)`, inset cyan left-edge glow `inset 3px 0 0 rgba(0,229,255,0.4)`, `--r-xl` radius, heavier padding/shadow.
- Secondary `.panel`: lighter `1px solid rgba(255,255,255,0.06)`, `--r-md` radius, receding.
- Inner controls (`.seg`, `select`) use `--r-sm` (8px); transcript area uses `--r-lg` (16px). Four distinct radius tiers.
- Bridge SVG: `preserveAspectRatio` switched to `xMidYMid meet` with explicit `width="330" height="132"` matching the viewBox 1:1 — node circles render perfectly round (no ellipse distortion). CSS sizes the svg to 330x132 fixed.
- Start core moved from `top: 38%` to `top: 50%` — now sits exactly on the wire's vertical midpoint (wire crosses SVG center 165,66 = 50%).

### Fix 3 — Real overlay state + transcript tag (Functionality + Craft)
- Overlay `buildConfigMessage()` no longer hardcodes strings. Added a shared `state` object (src/tgt/stt/source/translate_model/voice/muted/speed) that the WS config reads from.
- Overlay hydrates `state` from `chrome.storage.local` (`sgConfig`) with a live `storage.onChanged` listener; mute writes back to state and pushes live config.
- Popup now persists its config to `chrome.storage.local.sgConfig` on every change, completing the popup→overlay session sync round-trip (gracefully no-ops without the extension API).
- Transcript tag: removed brittle `position: sticky; float: right; margin: -10px`. Container already `position: relative`; added `padding-top: 24px`; tag is now `position: absolute; top: 8px; right: 8px` with its own glass chip — never overlaps the token reveal text.

## Preserved (untouched working features)
- Layered glass, aurora drift blobs, temporal-echo token reveal, start-core charge glow + pulse rings, animated mute icon, custom thin cyan scrollbars, reduced-motion guard.

## Dev Server
- Static extension HTML — open `extension/popup.html` and `extension/overlay.html` directly. Demo loops run without a backend; WS falls back gracefully.
