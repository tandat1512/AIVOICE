// Downsamples the mic stream (typically 44.1/48 kHz, float32) to 16 kHz Int16,
// then forwards binary frames to the main thread for WebSocket send.
//
// Strategy: simple polyphase-free decimation. Mic input goes through a tiny IIR
// low-pass (one-pole) at ~7 kHz to suppress aliasing, then we resample by linear
// interpolation to a fixed 16 kHz output rate.

class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.acc = 0;                  // fractional input index
    this.prev = 0;                  // last input sample (for interp + filter state)
    this.outBuf = new Int16Array(320);  // 20 ms @ 16 kHz (production spec: 20ms chunks)
    this.outIdx = 0;
    // one-pole LPF coefficient: y[n] = a*x[n] + (1-a)*y[n-1]; a~0.35 -> ~6kHz cutoff
    this.a = 0.35;
    this.lp = 0;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.lp = this.a * ch[i] + (1 - this.a) * this.lp;
      // walk fractional input pointer; emit one output sample each time it passes 1
      this.acc += 1 / this.ratio;
      while (this.acc >= 1) {
        this.acc -= 1;
        // linear interp between prev and current LP-filtered sample
        const frac = this.acc; // distance from current sample back toward prev
        const s = this.prev * frac + this.lp * (1 - frac);
        // Soft limiter: pass-through below 0.85, tanh-compress above to avoid
        // hard clipping distortion that ruins Vietnamese tonal features.
        let v;
        const abs = Math.abs(s);
        if (abs <= 0.85) {
          v = s;
        } else {
          const over = (abs - 0.85) / 0.15;
          v = (s > 0 ? 1 : -1) * (0.85 + 0.15 * Math.tanh(over));
        }
        this.outBuf[this.outIdx++] = (v < 0 ? v * 0x8000 : v * 0x7fff) | 0;
        if (this.outIdx === this.outBuf.length) {
          this.port.postMessage(this.outBuf.buffer.slice(0));
          this.outIdx = 0;
        }
      }
      this.prev = this.lp;
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
