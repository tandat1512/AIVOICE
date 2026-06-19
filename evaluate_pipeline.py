import asyncio
import json
import time
import sys
import os
import websockets

# Force utf-8 for Windows console
sys.stdout.reconfigure(encoding='utf-8')

class DeepMindEvaluator:
    def __init__(self):
        self.t0 = time.time()
        self.log_file = open("deepmind_eval.log", "w", encoding="utf-8")
        
        self.last_stt_word_count = 0
        self.last_word_time = 0
        
        self.sentence_dispatch_time = None
        self.trans_first_token_time = None
        
        self.total_words_emitted = 0
        self.total_commas = 0
        self.total_periods = 0
        self.translation_latencies = []
        
        self.current_stt_committed = ""

    def log(self, msg):
        ms_elapsed = int((time.time() - self.t0) * 1000)
        line = f"[{ms_elapsed:06d}ms] {msg}"
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def process_sync(self, committed_text):
        if not committed_text:
            return
            
        words = committed_text.split()
        
        # Calculate speed of new words appearing
        if len(words) > self.last_stt_word_count:
            now = time.time()
            if self.last_word_time > 0:
                speed_ms = int((now - self.last_word_time) * 1000)
                # Only log word-by-word if it's not a huge jump (to avoid spamming on first burst)
                if len(words) - self.last_stt_word_count == 1:
                    self.log(f"[STT_EMIT] Word '{words[-1]}' appeared (+{speed_ms}ms since last word)")
            self.last_word_time = now
            self.last_stt_word_count = len(words)
            self.total_words_emitted = len(words)
        
        # Check for punctuation
        if committed_text != self.current_stt_committed:
            if committed_text.endswith(",") and not self.current_stt_committed.endswith(","):
                self.log(f"[PUNCTUATION] Comma (,) auto-inserted -> \"{committed_text}\"")
                self.total_commas += 1
            if committed_text.endswith(".") and not self.current_stt_committed.endswith("."):
                self.log(f"[PUNCTUATION] Period (.) auto-inserted -> \"{committed_text}\"")
                self.total_periods += 1
                self.sentence_dispatch_time = time.time() # Sentence is committed, translation should start
                self.trans_first_token_time = None
                self.log(f"[ROUTER] Sentence dispatched for translation.")
            
            self.current_stt_committed = committed_text


    def process_translation_stream(self, token):
        if self.sentence_dispatch_time and not self.trans_first_token_time:
            now = time.time()
            self.trans_first_token_time = now
            latency = int((now - self.sentence_dispatch_time) * 1000)
            self.translation_latencies.append(latency)
            self.log(f"[TRANSLATION_PARALLEL] First token '{token}' arrived! Latency: {latency}ms")


async def run_evaluation():
    uri = "ws://127.0.0.1:8000/ws"
    try:
        with open("test_audio.pcm", "rb") as f:
            audio_data = f.read()
    except FileNotFoundError:
        print("test_audio.pcm not found. Please ensure it was extracted.")
        return

    evaluator = DeepMindEvaluator()
    evaluator.log("Starting DeepMind-level STT & Translation Evaluation")

    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps({"type": "config", "src": "vi", "tgt": "en"}))
            evaluator.log("WebSocket connected. Starting 1x real-time audio stream...")

            async def receive_messages():
                while True:
                    try:
                        msg = await websocket.recv()
                        data = json.loads(msg)
                        
                        if data.get("type") == "sync":
                            evaluator.process_sync(data.get("committed", ""))
                            
                        elif data.get("type") == "trans_stream_c":
                            evaluator.process_translation_stream(data.get("token", ""))
                            
                        elif data.get("type") == "translation_update":
                            delta = data.get("delta", {})
                            c = " ".join([c["text"] for c in delta.get("committed", [])])
                            evaluator.log(f"[TRANSLATION_FINAL] Committed text locked in white: \"{c}\"")
                            
                    except websockets.exceptions.ConnectionClosed:
                        evaluator.log("WebSocket connection closed.")
                        break
                    except Exception as e:
                        evaluator.log(f"Error receiving: {e}")
                        break

            recv_task = asyncio.create_task(receive_messages())

            # 16000 Hz * 2 bytes = 32000 bytes/sec
            # 8000 bytes = 250ms
            chunk_size = 8000
            
            # Stream first 45 seconds of audio for a solid test
            max_bytes = 16000 * 2 * 45
            for i in range(0, min(len(audio_data), max_bytes), chunk_size):
                chunk = audio_data[i:i+chunk_size]
                await websocket.send(chunk)
                await asyncio.sleep(0.25) # Exact 1x real-time
                
            evaluator.log("Finished streaming audio. Waiting 15s for final processing...")
            await websocket.send(json.dumps({"type": "stop"}))
            
            await asyncio.sleep(15)
            recv_task.cancel()
            
            # Summary Report
            evaluator.log("\n==================================================")
            evaluator.log("                EVALUATION SUMMARY                ")
            evaluator.log("==================================================")
            evaluator.log(f"Total Words Emitted: {evaluator.total_words_emitted}")
            evaluator.log(f"Total Commas Inserted: {evaluator.total_commas}")
            evaluator.log(f"Total Periods Inserted: {evaluator.total_periods}")
            if evaluator.translation_latencies:
                avg_latency = sum(evaluator.translation_latencies) / len(evaluator.translation_latencies)
                evaluator.log(f"Average Translation Parallel Latency: {avg_latency:.1f}ms")
            else:
                evaluator.log("No translations completed.")
            evaluator.log("==================================================\n")

    except ConnectionRefusedError:
        print("Server not running on port 8000")

asyncio.run(run_evaluation())
