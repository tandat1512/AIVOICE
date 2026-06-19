// StreamingAudioPlayer — plays Int16 PCM chunks from TTS WebSocket stream.
// Usage:
//   const player = new StreamingAudioPlayer(audioContext, 24000);
//   player.enqueueChunk(utteranceId, arrayBuffer);  // called per binary WS frame
//   player.cancel(utteranceId);                     // stops and fades on interrupt
//   player.setMuted(true/false);

export class StreamingAudioPlayer {
  constructor(audioContext, sampleRate = 24000) {
    this._ctx = audioContext;
    this._sampleRate = sampleRate;
    this._nextPlayTime = 0;
    this._queued = [];           // {utteranceId, source, endTime}[]
    this._lastChunkTime = null;
    this._playbackRate = 1.0;

    this._gainNode = audioContext.createGain();
    this._gainNode.connect(audioContext.destination);
  }

  setPlaybackRate(rate) {
    this._playbackRate = Math.max(0.5, Math.min(3.0, rate));
  }

  // Convert Int16 PCM → Float32 → AudioBuffer, schedule seamlessly after previous chunk.
  enqueueChunk(utteranceId, arrayBuffer) {
    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buf = this._ctx.createBuffer(1, float32.length, this._sampleRate);
    buf.copyToChannel(float32, 0);

    const source = this._ctx.createBufferSource();
    source.buffer = buf;
    source.playbackRate.value = this._playbackRate;
    source.connect(this._gainNode);

    // 20ms cushion on first chunk; seamless continuity thereafter.
    // Effective duration shrinks as playbackRate increases.
    const startAt = Math.max(this._ctx.currentTime + 0.020, this._nextPlayTime);
    source.start(startAt);
    this._nextPlayTime = startAt + buf.duration / this._playbackRate;

    const entry = { utteranceId, source, endTime: this._nextPlayTime };
    this._queued.push(entry);
    source.onended = () => {
      const idx = this._queued.indexOf(entry);
      if (idx !== -1) this._queued.splice(idx, 1);
    };

    this._lastChunkTime = performance.now();
  }

  // Fade out and stop all sources for utteranceId within ~50 ms.
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

  stats() {
    return {
      queued_chunks: this._queued.length,
      buffer_seconds: Math.round(Math.max(0, this._nextPlayTime - this._ctx.currentTime) * 100) / 100,
      last_chunk_age_ms: this._lastChunkTime ? Math.round(performance.now() - this._lastChunkTime) : null,
    };
  }
}
