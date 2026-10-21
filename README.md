# TIT Voice Studio

Công cụ chuyển văn bản tiếng Việt thành giọng nói, chạy hoàn toàn trên máy. Lõi giọng nói là
[VieNeu-TTS v3 Turbo](https://github.com/pnnbao97/VieNeu-TTS) (Apache-2.0), giao diện lấy cảm hứng từ các studio giọng nói online.

## Tính năng

- 25 giọng có sẵn (Bắc, Trung, Nam), lọc theo giới tính, vùng miền, tìm theo tên; nghe thử từng giọng.
- Ô soạn thảo có **chip cảm xúc**: `[cười]`, `[thở dài]`, `[hắng giọng]` và **thẻ nghỉ** `[nghỉ 1s]`, `[nghỉ 500ms]`.
  Gõ tay hoặc dán văn bản có thẻ cũng tự thành chip.
- Chỉnh tốc độ 0.75x–1.5x (giữ cao độ), xuất WAV 48 kHz hoặc MP3.
- Từ điển phát âm cho từ viết tắt, tên riêng.
- Lịch sử lưu trên máy, nghe lại và tải lại.
- Nhân bản giọng của chính bạn bằng micro (kèm câu đồng ý và xác nhận).

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/), Node.js 20+ và ffmpeg.

```bash
brew install uv ffmpeg
cd backend && uv sync
cd ../frontend && npm install
```

Lần chạy đầu tiên tự tải mô hình (~700 MB) vào `backend/data/models`.

## Chạy

Hai cửa sổ terminal:

```bash
cd backend && uv run uvicorn app.main:app --port 8765
```

```bash
cd frontend && npm run dev
```

Mở http://localhost:5173.

Hoặc build giao diện một lần (`cd frontend && npm run build`) rồi chỉ chạy backend, mở http://localhost:8765.

### Tuỳ chọn

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `TIT_PRECISION` | `fp32` | `int8` nhanh hơn ~3 lần trên CPU, chất lượng có thể giảm nhẹ |
| `TIT_DATA_DIR` | `backend/data` | Nơi lưu mô hình, lịch sử, giọng nhân bản, từ điển |

## API

| Method | Đường dẫn | Việc |
|---|---|---|
| `GET` | `/api/health` | Trạng thái mô hình |
| `GET` | `/api/voices` | Danh sách giọng |
| `GET` | `/api/voices/{id}/preview` | Nghe thử (trả file, hoặc `job_id` nếu đang tạo) |
| `POST` | `/api/tts` | `{text, voice, speed}` → `job_id` |
| `GET` | `/api/jobs/{id}` | Tiến độ và kết quả |
| `GET` | `/api/history/{id}/audio?format=wav\|mp3` | File audio |
| `POST` | `/api/voices/clone` | Nhân bản giọng (form: `name`, `gender`, `consent`, `audio`) |
| `GET` `PUT` | `/api/dictionary` | Từ điển phát âm |

Tài liệu đầy đủ: http://localhost:8765/docs.

## Ghi chú kỹ thuật

onnxruntime ≥ 1.31 từ chối file `.data` của mô hình khi nằm trong cache Hugging Face (symlink tới các blob
khác nhau). `backend/app/model_files.py` tải mô hình về thư mục riêng để tránh lỗi này.

## Sử dụng có trách nhiệm

Chỉ nhân bản giọng của chính bạn. Không dùng giọng tạo ra để giả mạo người khác, lừa đảo hay gây hiểu lầm.
Khi đăng tải công khai, hãy ghi rõ giọng đọc được tạo bằng AI.
