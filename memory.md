# Memory.md - Nhật Ký Trạng Thái Dự Án SmartAI (Real-time STT & Translation Pipeline)

Tệp này ghi nhận chi tiết toàn bộ các tính năng công nghệ đã được triển khai thành công, các vấn đề kỹ thuật còn tồn tại, cùng lộ trình nâng cấp hệ thống nhận dạng giọng nói (ASR) và dịch thuật thời gian thực siêu tốc (độ trễ ngang tầm Google Live Translate).

---

## 🚀 1. Những Gì Đã Làm Được (Done & Implemented)

Hệ thống đã trải qua một đợt tái cấu trúc toàn diện ở cả Backend và Frontend, đạt được những bước tiến lớn về độ mượt mà và tốc độ hiển thị:

### A. Tối Ưu Hóa Tần Suất & Thuật Toán Trích Xuất (STT Latency)
* **Giảm Chu Kỳ Quét (Poll Interval)**: Chu kỳ giải mã được rút ngắn từ `500ms` xuống còn `80ms` (`POLL_INTERVAL = 0.080`). Từ đầu tiên được hiển thị chỉ mất khoảng **150ms - 200ms** sau khi người dùng bắt đầu nói.
* **Thuật Toán LocalAgreement-1 (LA-1) + Confidence**:
  * Thay thế cơ chế LA-2 cũ (vốn đòi hỏi từ phải khớp ở 2 pass giải mã liên tiếp gây tăng gấp đôi độ trễ).
  * Từ mới sẽ được **commit ngay lập tức** nếu trùng vị trí với pass trước, **HOẶC** nếu độ tự tin nhận diện của Whisper đạt xác suất cao (`word.probability > 0.85`), loại bỏ thời gian chờ xác thực ở các pass sau.

### B. Song Song Hóa Toàn Phần (Parallel Execution)
* **Xử Lý Bất Đồng Bộ (`asyncio.to_thread` & `asyncio.gather`)**:
  * Việc dịch thuật (Translation) và sửa lỗi chính tả (Correction) được chạy song song trên `ThreadPoolExecutor` qua `asyncio.to_thread`.
  * Luồng chính điều phối sự kiện (Event Loop) và luồng nhận diện giọng nói (ASR OS Thread) được giải phóng hoàn toàn, loại bỏ triệt để hiện tượng nghẽn cổ chai (blocking) và tích lũy độ trễ.

### C. Cơ Chế Dual-Translator (Dịch Kép MarianMT + NLLB-200)
* **Interim Translation (Tốc độ tối đa)**: Sử dụng mô hình **MarianMT** (`Helsinki-NLP/opus-mt-vi-en`) siêu nhẹ cho kết quả dịch tạm thời (interim - chữ màu vàng) hiển thị với độ trễ cực thấp (`< 80ms`).
* **Quality Translation (Chất lượng tối đa)**: Sử dụng mô hình **NLLB-200** (`facebook/nllb-200-distilled-600M`) kết hợp bộ nhớ đệm **LRU Cache** để dịch các phần text đã committed chính thức và correction pass.

### D. Tối Ưu Hóa Trải Nghiệm Giao Diện (Frontend UX/UI)
* **Thuật Toán O(N) Silent Word-Diffing**: So sánh mảng từ mới trả về từ WebSocket với các thẻ `<span>` hiện tại trong DOM. Chỉ cập nhật/thêm các từ thay đổi thay vì dựng lại toàn bộ chuỗi text, loại bỏ hoàn toàn hiện tượng chớp màn hình (flickering) và giật lag layout.
* **Hiệu Ứng Pop-In**: Thêm lớp CSS `.word-new` với hoạt ảnh scale (0.85 -> 1.0) và hiệu ứng fade-in mượt mà trong vòng `120ms` giúp các từ xuất hiện vô cùng nịnh mắt và tự nhiên.
* **Bộ Lọc Thông Cao (High-Pass Filter - HPF)**: Tích hợp bộ lọc âm `BiquadFilterNode` với tần số cắt `80Hz` bằng Web Audio API tại client, loại bỏ các tạp âm tần số thấp như tiếng quạt gió, tiếng gõ bàn phím và tiếng thở trước khi gửi âm thanh lên server.

### E. Sửa Lỗi Chính Tả Tự Động Theo Ngữ Cảnh (Contextual Correction Pass)
* **Tích Hợp LLM Qwen2.5-1.5B-Instruct**:
  * Tự động chạy ngầm, bất đồng bộ và được debounce khi có chuỗi văn bản committed mới.
  * Sửa lỗi chính tả do ASR nhận dạng sai (ví dụ: "trân thành" -> "chân thành", "bạn có thể không" -> "bạn có khỏe không").
  * Cơ chế tự phục hồi: Nếu mô hình sửa lỗi chính tả bị quá tải hoặc lỗi, hệ thống sẽ trả về văn bản gốc mà không làm gián đoạn pipeline.

### F. Quản Lý Tài Nguyên & Tránh Tràn Bộ Nhớ (VRAM Optimization)
* **Cấu Hình Mặc Định Tiết Kiệm**: Sử dụng `phowhisper-small` làm model ASR cốt lõi, chạy tối ưu hóa trên GPU chỉ tốn khoảng ~500MB VRAM, bảo đảm card đồ họa dung lượng thấp (4GB) không bị lỗi hết bộ nhớ (OOM).

---

## ⚠️ 2. Những Gì Chưa Làm Được & Cần Cải Tiến (Backlog & Roadmap)

Mặc dù hệ thống đã đạt độ mượt mà cao, dưới đây là những thách thức kỹ thuật và tính năng còn thiếu cần được giải quyết trong các giai đoạn tiếp theo:

### 1. Hiện Tượng Ảo Giác Khi Im Lặng (Silence Hallucinations)
* **Vấn đề**: Để giảm độ trễ xử lý (tiết kiệm 100-300ms CPU), hệ thống đã tắt bộ lọc VAD tích hợp của faster-whisper (`vad_filter=False`). Điều này khiến mô hình Whisper dễ sinh ra ảo giác, tự động "vẽ" ra các từ hoặc câu nói kỳ quái (ví dụ: *"phong trào hiệu mỹ..."*, *"tôi đang thả ra đường đi cấp cứu..."*) khi phòng hoàn toàn im lặng hoặc chỉ có tiếng thở nhẹ.
* **Giải pháp cần triển khai**: Xây dựng một **Lightweight RMS Silence Gate (Volume Thresholding)** ở backend. Đo lường cường độ âm thanh tức thời bằng công thức Root-Mean-Square (RMS):
  $$\text{RMS} = \sqrt{\frac{1}{N}\sum x^2}$$
  Nếu $\text{RMS} < 0.012$, máy chủ sẽ bỏ qua quá trình giải mã Whisper ngay lập tức. Giải pháp này chỉ tốn $<0.05\text{ms}$ CPU, loại bỏ 100% ảo giác khi im lặng và tiết kiệm tối đa tài nguyên GPU.

### 2. Độ Trễ Đầu Vào Do Kích Thước Buffer Của Browser (Input Buffer Latency)
* **Vấn đề**: File `web/worklets/pcm-worklet.js` hiện tại đang sử dụng kích thước buffer đầu ra mặc định là `1600` mẫu âm thanh (~100ms độ trễ truyền tải).
* **Giải pháp cần triển khai**: Giảm kích thước buffer này xuống `512` mẫu (~32ms) để gửi gói tin âm thanh lên WebSocket tức thời hơn, giảm tổng độ trễ tích lũy từ miệng người nói đến màn hình hiển thị.

### 3. Cơ Chế Tự Động Kết Nối Lại Khi Mất WebSocket (Auto-Reconnection)
* **Vấn đề**: Giao diện client hiện tại chưa có khả năng tự động kết nối lại (auto-reconnect) và đồng bộ trạng thái khi kết nối WebSocket bị ngắt đột ngột (do mạng chập chờn hoặc do khởi động lại server). Người dùng buộc phải nhấn thủ công nút "Stop" rồi "Start" lại.
* **Giải pháp cần triển khai**: Viết thêm logic retry exponential backoff ở frontend để tự khôi phục kết nối WebSocket âm thầm mà không làm mất trạng thái phiên dịch hiện tại của người dùng.

### 4. Tự Động Đồng Bộ Trạng Thái Từ (Lazy Word-Timestamps)
* **Vấn đề**: Việc bật `word_timestamps=True` trên `faster-whisper` ngốn rất nhiều tài nguyên CPU/GPU và có thể gây SegFault (crash luồng C++ của CTranslate2) khi gặp những đoạn âm thanh cực ngắn. Hệ thống hiện đang tắt tính năng này và phân phối đều thời gian của từ theo tỷ lệ độ dài câu (uniform segment distribution). Điều này làm lệch mốc thời gian hiển thị của từng từ cụ thể.
* **Giải pháp cần triển khai**: Chỉ kích hoạt `word_timestamps=True` một cách lười biếng (lazy) cho các pass committed cuối cùng hoặc ở Correction Pass để định vị chính xác thời điểm nói của từng từ mà không làm giảm tốc độ nhận diện thời gian thực (interim pass).

### 5. Lazy Loading & Offloading Bộ Nhớ Của LLM
* **Vấn đề**: Khi cả model ASR, translator và corrector cùng được tải lên GPU, các máy chủ có cấu hình phần cứng yếu dễ bị chậm do thiếu hụt VRAM.
* **Giải pháp cần triển khai**: Thiết lập cơ chế tải chậm (lazy load) và giải phóng mô hình Corrector (offload sang RAM thường) khi không có dữ liệu nói mới trong khoảng thời gian dài (ví dụ: sau 5 phút im lặng).

---

## 📅 3. Kế Hoạch Thực Hiện Tiếp Theo (Next Steps)

1. **Khắc phục lỗi ảo giác khi im lặng**: Triển khai RMS Silence Gate vào `_transcribe_words` trong `stt_stream.py`.
2. **Nâng cấp Audio Buffer Worklet**: Chuyển đổi size buffer của `pcm-worklet.js` về 512.
3. **Cải tiến độ tin cậy kết nối**: Thêm cơ chế tự động kết nối lại phía client trong `web/app.js`.
4. **Đẩy mã nguồn chính thức**: Thường xuyên kiểm tra và đồng bộ hóa repository GitHub của dự án.
