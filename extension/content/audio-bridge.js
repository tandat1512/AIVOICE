// SmartGen audio bridge — content script.
// Handles mic/tab audio capture (PCM worklet → service worker → WS server)
// and TTS playback (WS audio chunks → StreamingAudioPlayer → speakers).

// ── Inline PCM worklet (same algorithm as web/worklets/pcm-worklet.js) ────────

const _PCM_WORKLET_CODE = `
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.acc = 0;
    this.prev = 0;
    this.outBuf = new Int16Array(320);
    this.outIdx = 0;
    this.a = 0.35;
    this.lp = 0;
  }
  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.lp = this.a * ch[i] + (1 - this.a) * this.lp;
      this.acc += 1 / this.ratio;
      while (this.acc >= 1) {
        this.acc -= 1;
        const frac = this.acc;
        const s = this.prev * frac + this.lp * (1 - frac);
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
registerProcessor('pcm-worklet', PCMWorklet);
`;

// ── StreamingAudioPlayer (ported from web/audio-player.js) ───────────────────

class StreamingAudioPlayer {
  constructor(audioContext, sampleRate = 24000) {
    this._ctx = audioContext;
    this._sampleRate = sampleRate;
    this._nextPlayTime = 0;
    this._queued = [];
    this._lastChunkTime = null;

    this._gainNode = audioContext.createGain();
    this._gainNode.connect(audioContext.destination);
  }

  enqueueChunk(utteranceId, arrayBuffer) {
    const buffered = Math.max(0, this._nextPlayTime - this._ctx.currentTime);
    if (buffered > 3) return;

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buf = this._ctx.createBuffer(1, float32.length, this._sampleRate);
    buf.copyToChannel(float32, 0);

    const source = this._ctx.createBufferSource();
    source.buffer = buf;
    source.connect(this._gainNode);

    const startAt = Math.max(this._ctx.currentTime + 0.020, this._nextPlayTime);
    source.start(startAt);
    this._nextPlayTime = startAt + buf.duration;

    const entry = { utteranceId, source, endTime: this._nextPlayTime };
    this._queued.push(entry);
    source.onended = () => {
      const idx = this._queued.indexOf(entry);
      if (idx !== -1) this._queued.splice(idx, 1);
    };
    this._lastChunkTime = performance.now();
  }

  cancel(utteranceId) {
    const toStop = this._queued.filter(e => e.utteranceId === utteranceId);
    if (!toStop.length) return;

    const now = this._ctx.currentTime;
    this._gainNode.gain.cancelScheduledValues(now);
    this._gainNode.gain.setValueAtTime(this._gainNode.gain.value, now);
    this._gainNode.gain.linearRampToValueAtTime(0, now + 0.030);

    for (const e of toStop) {
      try { e.source.stop(now + 0.035); } catch (_) {}
    }

    setTimeout(() => {
      const t = this._ctx.currentTime;
      this._gainNode.gain.cancelScheduledValues(t);
      this._gainNode.gain.setValueAtTime(0, t);
      this._gainNode.gain.linearRampToValueAtTime(1, t + 0.020);
      this._nextPlayTime = 0;
    }, 60);
  }

  setMuted(muted) {
    const now = this._ctx.currentTime;
    this._gainNode.gain.cancelScheduledValues(now);
    this._gainNode.gain.setValueAtTime(this._gainNode.gain.value, now);
    this._gainNode.gain.linearRampToValueAtTime(muted ? 0 : 1, now + 0.020);
  }

  setVolume(vol) {
    const now = this._ctx.currentTime;
    this._gainNode.gain.cancelScheduledValues(now);
    this._gainNode.gain.setValueAtTime(this._gainNode.gain.value, now);
    this._gainNode.gain.linearRampToValueAtTime(vol, now + 0.020);
  }
}

// ── AudioBridge — top-level bridge between capture, port, and playback ────────

class AudioBridge {
  constructor() {
    this._stream = null;
    this._ctx = null;
    this._workletNode = null;
    this._player = null;
    this._currentUtteranceId = null;
    this._recording = false;
    this._port = null;

    this._connectPort();
  }

  _connectPort() {
    this._port = chrome.runtime.connect({ name: 'smartgen' });
    this._port.onMessage.addListener(msg => this._handlePortMsg(msg));
    this._port.onDisconnect.addListener(() => {
      // SW disconnected — try to reconnect after a short delay
      setTimeout(() => this._connectPort(), 1000);
    });
  }

  async start(mode, config) {
    if (this._recording) return;

    // Create AudioContext on user gesture
    this._ctx = new AudioContext({ sampleRate: 48000 });

    // Load inline PCM worklet as a blob URL
    const blob = new Blob([_PCM_WORKLET_CODE], { type: 'application/javascript' });
    const workletUrl = URL.createObjectURL(blob);
    try {
      await this._ctx.audioWorklet.addModule(workletUrl);
    } catch (err) {
      URL.revokeObjectURL(workletUrl);
      throw new Error(`AudioWorklet failed to load (CSP or browser restriction): ${err.message}`);
    }
    URL.revokeObjectURL(workletUrl);

    // Create player (TTS playback)
    this._player = new StreamingAudioPlayer(this._ctx, 24000);

    // Apply stored volume
    chrome.storage.sync.get({ volume: 1.0 }, ({ volume }) => {
      this._player?.setVolume(volume);
    });

    // Capture audio stream
    try {
      if (mode === 'mic') {
        this._stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            sampleRate: 48000,
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      } else {
        // Tab audio: user picks which tab/window to share
        this._stream = await navigator.mediaDevices.getDisplayMedia({
          audio: true,
          video: { width: 1, height: 1, frameRate: 1 },
        });
      }
    } catch (err) {
      this._ctx.close();
      this._ctx = null;
      throw err;
    }

    // Wire stream → worklet → SW port
    const source = this._ctx.createMediaStreamSource(this._stream);
    this._workletNode = new AudioWorkletNode(this._ctx, 'pcm-worklet');
    this._workletNode.port.onmessage = ev => {
      this._port.postMessage({ type: 'pcm', buffer: ev.data });
    };
    source.connect(this._workletNode);

    // Send config to server via SW
    this._port.postMessage({
      type: 'ext_config',
      srcLang: config.srcLang || 'vi',
      tgtLang: config.tgtLang || 'en',
    });

    this._recording = true;
    this._dispatchStatus('recording');
  }

  stop() {
    if (!this._recording) return;

    this._port.postMessage({ type: 'ext_stop' });
    this._stopCapture();
    this._recording = false;
    this._dispatchStatus('ready');
  }

  _stopCapture() {
    this._workletNode?.disconnect();
    this._workletNode = null;

    if (this._stream) {
      for (const track of this._stream.getTracks()) track.stop();
      this._stream = null;
    }

    this._ctx?.close();
    this._ctx = null;
    this._player = null;
  }

  _handlePortMsg(msg) {
    switch (msg.type) {
      case 'audio_chunk':
        if (this._player && this._currentUtteranceId) {
          this._player.enqueueChunk(this._currentUtteranceId, msg.buffer);
        }
        break;
      case 'tts_start':
        this._currentUtteranceId = msg.utterance_id;
        break;
      case 'tts_end':
        this._currentUtteranceId = null;
        break;
      case 'tts_cancel':
        this._player?.cancel(msg.utterance_id);
        break;
      case 'ws_status':
        this._dispatchStatus(msg.connected ? 'ready' : 'connecting');
        break;
    }

    // Forward all port messages as DOM events for meet-overlay.js
    document.dispatchEvent(new CustomEvent('smartgen:msg', { detail: msg }));
  }

  _dispatchStatus(status) {
    document.dispatchEvent(new CustomEvent('smartgen:status', { detail: { status } }));
  }

  isRecording() { return this._recording; }

}

// Single bridge instance shared with meet-overlay.js (same content script scope)
window._sgBridge = new AudioBridge();
