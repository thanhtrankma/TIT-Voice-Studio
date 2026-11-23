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
- **Hội thoại tiếng Trung**: dán lời thoại (mỗi dòng một câu, `中文 | Tiếng Việt | English`, dòng trống mở đoạn mới,
  `*từ khoá*` để tô màu), nhận video 16:9 chia đôi màn hình: người A bên trái, người B bên phải, mỗi bên có chữ Hán,
  pinyin tự tạo, nghĩa tiếng Việt và câu tiếng Anh; bên đang nói sáng lên. Mỗi câu đọc 1–3 lần bằng 8 giọng
  tiếng Trung phổ thông của Kokoro (dùng chung model với giọng tiếng Anh), có thể chen nghĩa tiếng Việt đọc bằng
  VieNeu. Lặp cả bài tới 60 lượt để thành video "ngâm" nhiều giờ (tối đa 11,5 giờ cho vừa giới hạn YouTube).
  Lần đọc thứ 2 có thể đặt tốc độ riêng (chậm 0.6x–0.9x). Mặc định có **intro** vài giây (tên bài, hai giọng,
  số câu; giọng Việt đọc tên bài). **Nhạc nền**: 3 bản tự tạo (nền êm, mưa nhẹ, sóng biển) hoặc tải nhạc của bạn
  lên; nhạc lặp suốt video và tự nhỏ đi khi có giọng đọc.
- **Đăng YouTube** ngay từ bài luyện: tiêu đề, mô tả (kèm mục lục theo câu và lời thoại) điền sẵn, chọn Riêng tư /
  Không công khai / Công khai hoặc hẹn giờ công khai, nhiều tài khoản. Xem mục *Kết nối YouTube* bên dưới.
- **Ảnh bìa YouTube** 1280×720 tự thiết kế: chữ to có viền, bong bóng thoại trích một câu trong bài, 4 tông màu;
  sửa chữ lớn, câu trích và xem trước ngay, tải ảnh về được kể cả khi chưa kết nối YouTube.

## Cài đặt

Cần [uv](https://docs.astral.sh/uv/), Node.js 20+ và ffmpeg.

```bash
brew install uv ffmpeg
cd backend && uv sync
cd ../frontend && npm install
```

Lần chạy đầu tiên tự tải mô hình (~700 MB) vào `backend/data/models`.

## Chạy

Một lệnh ở thư mục gốc dự án:

```bash
./start.sh
```

Lệnh tự cài thư viện còn thiếu, build lại giao diện nếu code giao diện có thay đổi, chạy backend rồi mở
http://localhost:8765. Ctrl+C để tắt. Đổi cổng: `PORT=9000 ./start.sh`.

Khi sửa giao diện, chạy `./start.sh --dev`: thêm Vite có tải lại nóng ở http://localhost:5173, backend tự khởi động lại
khi sửa code Python.

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
| `GET` | `/api/chinese` | Giọng tiếng Trung (`kokoro:z*`), nghe thử qua `/api/english/voices/{id}/preview` |
| `POST` | `/api/dialogue` | `{text, voice_a, voice_b, vi_voice?, title, repeats, speed, pause, loops, show_en}` → `job_id` |
| `GET` `POST` | `/api/music` | Thư viện nhạc nền; tải lên (form: `file`, `name`) |
| `GET` `DELETE` | `/api/music/{id}[/audio]` | Nghe thử hoặc xoá nhạc đã tải lên |
| `GET` | `/api/shadow?kind=shadow\|dialogue` | Danh sách bài luyện hoặc video hội thoại (file, ảnh bìa, đăng YouTube dùng chung các đường dẫn `/api/shadow/{id}/…`) |
| `GET` | `/api/shadow/{id}/video\|audio\|srt\|timeline` | File của bài luyện |
| `GET` | `/api/youtube` | Đã có OAuth client chưa, các tài khoản, trạng thái đăng nhập |
| `POST` | `/api/youtube/client-secret` | Nạp file OAuth client (form: `file`) |
| `POST` | `/api/youtube/login` | Mở trang đăng nhập Google trên máy chạy backend |
| `PUT` `DELETE` | `/api/youtube/accounts/{id}[/active]` | Chọn hoặc gỡ tài khoản |
| `GET` | `/api/shadow/{id}/youtube` | Nội dung gợi ý để đăng và các lần đã đăng |
| `POST` | `/api/shadow/{id}/thumbnail` | `{theme, headline, quote}` → ảnh bìa JPEG xem trước |
| `POST` | `/api/shadow/{id}/youtube` | `{title, description, tags, privacy, publish_at?, account?, thumbnail?}` → `job_id` |
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

### Ảnh đại diện và banner kênh

Thư mục [`branding/`](branding) có sẵn ảnh đại diện 800×800 và banner 2560×1440 cho kênh, đủ 4 tông màu giống ảnh bìa
video. Tên kênh, khẩu hiệu nằm gọn trong vùng 1235×338 ở giữa nên điện thoại vẫn thấy đủ; các câu tiếng Anh trang trí
hai bên chỉ hiện trên máy tính và TV. Tạo lại với tên kênh của bạn:

```bash
cd backend && uv run python -m app.branding --name "Tên kênh" --theme coral
```

Kênh luyện tiếng Trung thêm `--lang zh`: biểu tượng đổi sóng âm thành chữ 中, khẩu hiệu “Luyện nói tiếng Trung bằng
Shadowing”, câu trang trí là chữ Hán kèm pinyin (你叫什么名字？…). Ảnh lưu thành `avatar-zh-<tông>.png`, `banner-zh-<tông>.jpg`.

Tải lên ở YouTube Studio → *Tuỳ chỉnh* (Customization), mục ảnh đại diện và ảnh biểu ngữ.

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

Giọng tiếng Trung không đi qua espeak: chữ Hán chuyển thành âm vị bằng `misaki[zh]` (Apache-2.0), đúng bộ âm vị
Kokoro được huấn luyện (espeak đọc sai thanh). Pinyin hiển thị lấy từ `pypinyin` + dữ liệu CC-CEDICT (thanh nhẹ:
máfan, xièxie), tách từ bằng `jieba`. Chữ Hán vẽ bằng font Hiragino Sans GB có sẵn trên macOS. Video dài chỉ
encode một lượt rồi nối bản sao bằng stream copy; mỗi lượt làm tròn lên bội số 25.600 mẫu để hình và tiếng
không lệch khi nối.

## Sử dụng có trách nhiệm

Chỉ nhân bản giọng của chính bạn. Không dùng giọng tạo ra để giả mạo người khác, lừa đảo hay gây hiểu lầm.
Khi đăng tải công khai, hãy ghi rõ giọng đọc được tạo bằng AI.
