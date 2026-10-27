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
- **Luyện Shadowing**: dán bài tiếng Anh (mỗi dòng một câu, `English | Tiếng Việt`), nhận video MP4 16:9 hoặc 9:16
  theo nhịp Nghe → Đến lượt bạn → Nghe chậm → Đến lượt bạn, kèm lượt nói cùng lúc cuối bài, MP3 và phụ đề SRT.
  Mặc định dùng giọng tiếng Anh bản xứ (Kokoro-82M, 10 giọng Mỹ/Anh) và tô sáng theo mốc thời gian thật của từng từ;
  vẫn chọn được giọng VieNeu. Model Kokoro (~192 MB) tự tải ở lần dùng đầu.
  Xem [docs/shadowing-video.md](docs/shadowing-video.md).
- **Đăng YouTube** ngay từ bài luyện: tiêu đề, mô tả (kèm mục lục theo câu và lời thoại) điền sẵn, chọn Riêng tư /
  Không công khai / Công khai hoặc hẹn giờ công khai, ảnh bìa tự tạo, nhiều tài khoản. Xem mục *Kết nối YouTube* bên dưới.

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
| `GET` | `/api/english` | Giọng tiếng Anh bản xứ (`kokoro:*`) và model đã tải chưa |
| `GET` | `/api/english/voices/{id}/preview` | Nghe thử giọng bản xứ |
| `POST` | `/api/shadow` | `{text, voice, title, repeats, slow_speed, gap_factor, full_run, aspect}` → `job_id`; `voice` là giọng VieNeu hoặc `kokoro:*` |
| `GET` | `/api/shadow` | Danh sách bài luyện |
| `GET` | `/api/shadow/{id}/video\|audio\|srt\|timeline` | File của bài luyện |
| `GET` | `/api/youtube` | Đã có OAuth client chưa, các tài khoản, trạng thái đăng nhập |
| `POST` | `/api/youtube/client-secret` | Nạp file OAuth client (form: `file`) |
| `POST` | `/api/youtube/login` | Mở trang đăng nhập Google trên máy chạy backend |
| `PUT` `DELETE` | `/api/youtube/accounts/{id}[/active]` | Chọn hoặc gỡ tài khoản |
| `GET` | `/api/shadow/{id}/youtube` | Nội dung gợi ý để đăng và các lần đã đăng |
| `POST` | `/api/shadow/{id}/youtube` | `{title, description, tags, privacy, publish_at?, account?}` → `job_id` |
| `DELETE` | `/api/shadow/{id}` | Xoá bài luyện |

Tài liệu đầy đủ: http://localhost:8765/docs.

## Kết nối YouTube

Làm một lần (cách làm giống pianotube; dùng lại được OAuth client của pianotube):

1. [Google Cloud Console](https://console.cloud.google.com/): tạo project, bật **YouTube Data API v3**.
2. **OAuth consent screen**: chọn External, thêm email của bạn vào Test users, rồi bấm **Publish app**
   (để token không hết hạn sau 7 ngày).
3. **Credentials → OAuth client ID → Desktop app**, tải file JSON về.
4. Trong tab Luyện Shadowing, mở một bài → **Đăng YouTube** → chọn file JSON đó → **Kết nối tài khoản YouTube**.
   Trình duyệt mở trang đăng nhập Google; cấp quyền tải video lên. Đăng nhập được nhiều tài khoản.

File OAuth client và token nằm trong `backend/data/youtube/` (không đưa lên git).

- Project chưa qua [kiểm duyệt YouTube API](https://support.google.com/youtube/contact/yt_api_form) thì video đăng qua
  API **bị khoá ở chế độ Riêng tư**. Gửi form kiểm duyệt (miễn phí, mất vài tuần) để đăng công khai và hẹn giờ.
- Mỗi lần đăng tốn khoảng 1.600 trên 10.000 đơn vị quota mỗi ngày của project.
- Video được khai báo `containsSyntheticMedia` (giọng đọc AI), danh mục Giáo dục.
- Ảnh bìa tuỳ chỉnh cần kênh đã xác minh số điện thoại; chưa xác minh thì video vẫn đăng, chỉ báo chưa đặt được ảnh bìa.

## Kiểm thử

```bash
cd backend && uv run pytest
```

Bộ kiểm thử chạy mô hình thật (khoảng 30–60 giây), ghi dữ liệu vào thư mục tạm, không đụng vào lịch sử của bạn.

## Ghi chú kỹ thuật

onnxruntime ≥ 1.31 từ chối file `.data` của mô hình khi nằm trong cache Hugging Face (symlink tới các blob
khác nhau). `backend/app/model_files.py` tải mô hình về thư mục riêng để tránh lỗi này.

Mô hình ra khoảng -19.5 LUFS; backend chuẩn hoá mọi bản về -16 LUFS, đỉnh -1.5 dBFS.

Giọng bản xứ chạy bằng [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT), model Kokoro-82M
(Apache-2.0), tải từ GitHub release `model-files-v1.0` vào `backend/data/models/kokoro` và kiểm tra sha256.
Phần chuyển chữ thành âm vị dùng **espeak-ng (GPL-3.0)** qua `espeakng-loader`: dùng cá nhân và nội bộ không sao,
nhưng nếu phát hành hay bán ứng dụng thì cần xem lại điều kiện GPL. espeak-ng lỗi khi đường dẫn dữ liệu quá dài,
nên `app/english.py` chép dữ liệu sang thư mục model khi cần.

## Sử dụng có trách nhiệm

Chỉ nhân bản giọng của chính bạn. Không dùng giọng tạo ra để giả mạo người khác, lừa đảo hay gây hiểu lầm.
Khi đăng tải công khai, hãy ghi rõ giọng đọc được tạo bằng AI.
