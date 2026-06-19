// Shared WebSocket message type constants.
// Loaded in content scripts (shared global scope) and importable in service worker.

const WS_MSG = Object.freeze({
  // Server → Client JSON
  TTS_START:      'tts_start',
  TTS_END:        'tts_end',
  TTS_CANCEL:     'tts_cancel',
  LATENCY:        'latency',
  SYNC:           'sync',
  COMMIT:         'commit',
  WORD:           'word',
  INTERIM:        'interim',
  TRANS_STREAM_C: 'trans_stream_c',
  TRANS_STREAM_I: 'trans_stream_i',
  CLEAR_TRANS_I:  'clear_trans_i',
  INFO:           'info',
  ERROR:          'error',

  // Client → Server JSON
  CONFIG:         'config',
  STOP:           'stop',

  // Extension internal (content ↔ service-worker port)
  PCM:            'pcm',          // content→SW: raw PCM ArrayBuffer
  AUDIO_CHUNK:    'audio_chunk',  // SW→content: TTS audio ArrayBuffer
  WS_STATUS:      'ws_status',    // SW→content: connection status bool
  EXT_CONFIG:     'ext_config',   // content→SW: forward config to server
  EXT_STOP:       'ext_stop',     // content→SW: forward stop to server
});
