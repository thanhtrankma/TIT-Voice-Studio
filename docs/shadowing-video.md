# Nghiên cứu: tool tạo video Shadowing English trong TIT Voice Studio

Ngày 27/10/2026. Mục tiêu: thêm một tab mới trên giao diện. Người dùng dán bài tiếng Anh (có thể kèm bản dịch),
chọn giọng có sẵn hoặc giọng nhân bản, rồi nhận về video MP4 để luyện nghe và nói theo. Mọi thứ chạy trên máy như phần còn lại của app.

## 1. Đã kiểm chứng gì (đo thật trên máy này)

### VieNeu-TTS v3 Turbo đọc tiếng Anh được không?

Model card ghi v3 Turbo được huấn luyện trên khoảng 10.000 giờ dữ liệu Anh–Việt và hỗ trợ trộn hai thứ tiếng
(code-switching). Bộ G2P `sea-g2p` xử lý cả hai ngôn ngữ. Tài liệu cũng ghi rõ v3 Nano đọc tiếng Anh kém hơn hẳn,
nên **chỉ dùng v3 Turbo** (app đang dùng bản này).

Cách thử: gọi `/api/tts` với 5 câu hội thoại tiếng Anh, rồi cho Whisper `small.en` nghe lại và tính tỷ lệ sai từ (WER).

| Giọng | Văn bản thường (55 từ) | Thời gian tạo | Thời lượng audio |
|---|---|---|---|
| Adam (Nam · Nam) | **WER 0%** | 9,2 s | 15,3 s |
| Ngọc Huyền (Nữ · Bắc) | **WER 0%** | 11,1 s | 18,7 s |
| Mai Anh (Nữ · Bắc · tin tức) | **WER 0%** | 9,1 s | 18,1 s |

Câu khó (giờ, ngày, tiền, phần trăm, số điện thoại, *thoroughly*, *Worcester*): số và ký hiệu được đọc bằng
tiếng Anh, không bị đọc thành tiếng Việt. Whisper nghe ra đúng "3:30 p.m.", "$25", "15%", "555-0123" và "Worcester".
Lỗi duy nhất là "**9 a.m.**" ở cuối bài bị nuốt âm ở cả hai giọng.
→ Nên có bước chuẩn hoá tiếng Anh nhỏ trước khi đọc (`9 a.m.` → `nine A M`, `27th` → `twenty-seventh`).

Tốc độ: hệ số thời gian thực khoảng 0,6 trên CPU fp32. Bài 2 phút cần khoảng 70 giây để tạo giọng.

> WER chỉ cho biết **nghe có rõ chữ không**. Nó không đo **giọng có chuẩn bản xứ không**. Các giọng có sẵn là
> giọng người Việt, nên tiếng Anh có thể mang chút ngữ điệu Việt. Cần nghe trực tiếp trước khi chốt giọng mặc định
> cho bài học. Nếu cần giọng chuẩn hơn, người dùng có thể nhân bản giọng của chính họ khi đọc tiếng Anh (tab Nhân bản giọng).

### Dựng video

- ffmpeg Homebrew 9.0.2 trên máy **không có** `drawtext`, `subtitles` hay `libass`, nên không đốt chữ lên video
  bằng ffmpeg được. Bắt người dùng cài lại ffmpeg thì phiền.
- Cách thay thế đã thử thành công: **Pillow vẽ khung hình, ffmpeg chỉ ghép**. Pillow 12.3 đã có sẵn trong
  `backend/.venv`, không cần thêm phụ thuộc. Mỗi "trạng thái" (đổi từ được tô sáng, mỗi nhịp đếm ngược) là một ảnh PNG,
  ghép bằng concat demuxer có `duration`, mã hoá `libx264 -tune stillimage` (hoặc `h264_videotoolbox`).
- Bản mẫu 3 câu, video 55,6 giây, 1280×720: **vẽ 3,5 s + encode 2,6 s**. Phần dựng video gần như không tốn thời
  gian so với phần tạo giọng.
- Font Arial hệ thống hiển thị đủ dấu tiếng Việt. Bản chính thức nên đóng gói Be Vietnam Pro bản TTF
  (giấy phép OFL) cho đồng bộ với giao diện. `@fontsource` chỉ có woff/woff2.

Script mẫu đang nằm ngoài repo (thư mục scratchpad của phiên làm việc). Khi làm thật sẽ viết lại thành `backend/app/shadow.py`.

## 2. Định dạng bài học

Các app hiện có (RecEcho, ShadowEcho, Shadowing Player, SpeakFox…) đều dựa trên video YouTube có sẵn: dừng sau mỗi
câu, cho người học nói rồi so sánh. Điểm khác của tool này: **tự tạo nội dung** từ bất kỳ văn bản nào, và **cùng một
mô hình đọc được cả Anh lẫn Việt**. Như vậy video có thể đọc luôn nghĩa tiếng Việt mà không cần thêm engine nào.

Mỗi câu chạy theo một "mẫu luyện" có thể chỉnh:

```
[Nghe 1x] → [Đến lượt bạn: im lặng ≈ 1,3 × độ dài câu] → [Nghe chậm 0.8x] → [Đến lượt bạn] → (lặp N lần)
```

Cuối bài thêm một lượt **Shadowing liền mạch**: đọc cả bài không nghỉ để người học nói đè theo. Đây mới là shadowing
đúng nghĩa. Các bước trên là "nghe và nhắc lại".

Các chế độ nên có (theo thứ tự ưu tiên):

1. **Nghe và nhắc lại**: như trên. Đây là MVP.
2. **Shadowing liền mạch**: chỉ lượt đọc cả bài, có tô sáng từng từ.
3. **Chia cụm (back-chaining)** cho câu dài: luyện từ cuối câu ngược về đầu, ví dụ *"a cup of tea"* →
   *"rather have a cup of tea"* → cả câu. Cách chia cụm có thể tự động theo dấu phẩy và độ dài.
4. **Hội thoại nhập vai**: hai giọng A/B (nam/nữ). Khi luyện vai A thì lời A bị tắt tiếng, chỉ hiện chữ.
5. **Nghe nghĩa**: đọc câu tiếng Việt bằng giọng Việt trước hoặc sau câu tiếng Anh.

Khung hình (đã có trong bản mẫu): nhãn bước (Nghe / Nghe chậm / Đến lượt bạn), câu tiếng Anh tô sáng theo từng từ,
bản dịch, thanh đếm ngược trong lượt nói, thanh tiến độ cả bài, "Câu x/y", và dòng **"Giọng đọc AI · TIT Voice Studio"**
theo mục Sử dụng có trách nhiệm trong README. Sau này có thể thêm phiên âm IPA.

Xuất ra:
- MP4 16:9 (YouTube) hoặc 9:16 (Shorts/TikTok)
- MP3 chỉ có tiếng (nghe khi đi đường)
- SRT phụ đề
- JSON dòng thời gian, để trình luyện trong app dùng lại

## 3. Mốc thời gian từng từ (để tô sáng kiểu karaoke)

| Cách | Độ chính xác | Chi phí | Ghi chú |
|---|---|---|---|
| Tạo giọng **từng câu một** | Biên câu chính xác tuyệt đối | Không | Đằng nào cũng phải làm để chèn khoảng nghỉ |
| Chia thời lượng câu theo số âm tiết hoặc ký tự | Khá ổn với câu ngắn | Không | Đủ cho MVP |
| faster-whisper `base.en`/`small.en`, bật `word_timestamps` | Tốt (đã thử, lệch khoảng ±50 ms) | +75–250 MB model, khoảng 3 s cho 18 s audio | Tiện làm luôn **cổng QA**: câu nào WER > 0 thì tạo lại |
| Forced alignment (MMS, torchaudio) | Tốt nhất | Kéo theo torch, rất nặng | Không đáng |

Đề xuất: MVP dùng hai cách đầu. Bản sau thêm faster-whisper làm tuỳ chọn: vừa lấy mốc từ chính xác, vừa tự phát hiện
câu bị đọc sai hoặc thiếu từ để tạo lại. Model tự hồi quy đôi khi bỏ chữ, và bước QA này bắt được lỗi đó.

## 4. Kiến trúc đề xuất (khớp với code hiện tại)

### Backend

- `app/shadow.py`:
  - phân tích bài học: mỗi dòng một câu, `English | Tiếng Việt`, có thể ghi `A:`/`B:` cho hội thoại
  - chuẩn hoá tiếng Anh
  - lập dòng thời gian
  - ghép audio, dùng lại `change_speed` (atempo, giữ cao độ) và `normalize_loudness`
  - vẽ khung hình bằng Pillow, gọi ffmpeg, ghi SRT
- Tạo giọng: gọi `engine.tts.infer(câu, voice=…)` cho **từng câu**. Bản chậm lấy từ atempo của chính audio đó,
  **không tạo lại giọng**.
  Không đi qua `textproc.to_segments`, vì hàm này áp từ điển phát âm tiếng Việt và có thể làm hỏng từ tiếng Anh.
  Sau này nếu cần thì làm từ điển riêng cho tiếng Anh.
- API theo đúng kiểu job hiện có:
  - `POST /api/shadow` nhận `{lines, voice, voice_vi?, pattern: {repeats, slow_speed, gap_factor, full_run}, aspect}` và trả `job_id`
  - `GET /api/shadow/{id}/video|audio|srt|timeline`
  - Tiến độ chia đôi: 0–0,85 cho tạo giọng, 0,85–1 cho dựng video.
- Lưu trữ: `data/shadow/{id}/`, thêm bảng `shadow_lessons` trong `studio.db` (hoặc thêm cột `kind` cho history).
- Lưu ý hàng đợi: `Engine` có đúng một luồng worker. Phần encode video nên đẩy sang `ThreadPoolExecutor` riêng,
  để bài dài không chặn các yêu cầu TTS hay nghe thử khác.

### Frontend

- Thêm tab **"Luyện Shadowing"** trong `App.tsx` (icon `Repeat` hoặc `Clapperboard` của lucide), trang `pages/ShadowPage.tsx`:
  - Cột trái gồm:
    - ô soạn bài (mỗi dòng một câu, có nút "Thêm bản dịch")
    - chọn giọng (dùng lại `VoiceLibrary`)
    - mẫu luyện: số lần lặp, tốc độ chậm, hệ số khoảng nghỉ, có hoặc không có lượt liền mạch
    - khung hình 16:9 / 9:16
  - Cột phải gồm:
    - danh sách câu, mỗi câu có thời lượng và nút nghe thử
    - thanh tiến độ
    - trình phát video, các nút tải MP4 / MP3 / SRT
- Giai đoạn 2, **trình luyện trong app**: phát theo dòng thời gian JSON, bật micro trong lượt "Đến lượt bạn"
  (`MediaRecorder` đã dùng ở tab Nhân bản giọng), rồi nghe lại xen kẽ *mẫu → giọng mình*.

## 5. Lộ trình

| Giai đoạn | Nội dung | Phụ thuộc mới |
|---|---|---|
| **MVP** | Tab mới, chế độ Nghe và nhắc lại + lượt liền mạch, 1 giọng, bản dịch nhập tay, MP4/MP3/SRT, tô sáng từ theo ước lượng | Không (Pillow có sẵn, cần thêm 1 file font TTF) |
| v2 | faster-whisper: mốc từ chính xác + cổng QA tự tạo lại câu lỗi; hội thoại 2 giọng; chia cụm; đọc nghĩa tiếng Việt; khung 9:16 | `faster-whisper` (tuỳ chọn) |
| v3 | Trình luyện trong app: ghi âm, so sánh, chấm điểm phát âm bằng Whisper; IPA; mẫu bài có sẵn (giao tiếp, IELTS) | `eng_to_ipa`/CMUdict |

Dịch tự động (Anh → Việt) không có trong VieNeu. Nếu muốn có thì phải gọi LLM hoặc dùng mô hình dịch cục bộ
(ví dụ NLLB hay EnViT5, nặng vài trăm MB). Nên để tuỳ chọn, MVP chỉ dùng bản dịch nhập tay.

## 6. Trạng thái MVP (27/10/2026)

Đã làm: `backend/app/shadow.py`, các route `/api/shadow*`, tab **Luyện Shadowing** (`frontend/src/pages/ShadowPage.tsx`).
Phần dựng video chạy ở luồng riêng (`Engine.submit(..., then=...)`).

Đo trên bài mẫu 5 câu, giọng Adam:
- tạo giọng khoảng 6 s, dựng video 1080p khoảng 10 s, video dài 1:26
- Whisper nghe đúng 5/5 câu
- tô sáng ước lượng lệch trung bình 89 ms, tối đa 286 ms so với mốc từ của Whisper

Câu có giờ ở cuối, đo 6 lần mỗi cách viết với giọng Ngọc Huyền:
- `9 a.m.` để nguyên: đọc đúng **0/6**
- `nine A M` (cách `normalize_en` đang dùng): đọc đúng **4/6**

Hạ `temperature` xuống 0.5 hay 0.3 **không** làm ổn định hơn, nên giữ mặc định 0.8.
Lỗi còn lại là lỗi lấy mẫu ngẫu nhiên: thỉnh thoảng đọc sai cụm đầu câu ("The meeting" → "Committing"),
hoặc lảm nhảm thêm đuôi sau câu ngắn. Cổng QA bằng Whisper ở v2 là cách sửa đúng.

### Giọng bản xứ Kokoro (27/10/2026)

`backend/app/english.py` chạy Kokoro-82M qua kokoro-onnx. Giọng có id dạng `kokoro:af_heart`, đi cùng route
`/api/shadow` với giọng VieNeu. Tab Luyện Shadowing mặc định chọn nhóm "Bản xứ Mỹ/Anh".

- **Model**: fp16, 164 MB, cộng gói giọng 28 MB. Tải ở lần dùng đầu; job hiện "Đang tải giọng bản xứ lần đầu…".
- **Tốc độ**: RTF khoảng 0,3 trên CPU, nhanh gấp đôi VieNeu. Bài mẫu 5 câu đọc xong khoảng 3 giây.
- **Đọc đúng**: câu khó ("The meeting starts at 3:30 p.m.", "call me before 9 a.m.") đúng 24/24 lần (2 giọng × 6 lần × 2 câu),
  không cần `normalize_en`. Kokoro đọc nguyên văn để mốc khớp với từ hiển thị.
- **Mốc từ**: `create_timed` trả mốc từng âm vị; `group_starts` gộp thành từ (tách ở âm vị khoảng trắng).
  Khi espeak đọc một từ thành nhiều từ (ví dụ "1,250"), `align_words` đếm số nhóm khi đọc riêng từng từ; vẫn lệch
  thì quay về ước lượng. `timeline.json` ghi `word_timing: measured | estimated`.
- **Độ sớm 80 ms**: mốc âm vị rơi sau lúc âm thanh bật lên khoảng 30–130 ms, nên tô sáng sớm 80 ms
  (`HIGHLIGHT_LEAD_S`).

Độ lệch so với mốc từ của Whisper, cùng một audio, 7 câu × (nghe + nghe chậm). Bỏ câu "3:30 p.m." vì Whisper tách sai
thành "3" ".30pm".

| Giọng | Mốc đo thật (TB / trung vị) | Ước lượng theo âm tiết (TB / trung vị) |
|---|---|---|
| Heart (Mỹ) | 50 / 38 ms | 146 / 134 ms |
| George (Anh) | 89 / 58 ms | 236 / 227 ms |

## 7. Rủi ro

- **Ngữ điệu**: giọng VieNeu đọc rõ (WER 0%) nhưng chưa "bản xứ"; đã có Kokoro thay. Vẫn cần ghi rõ trong video
  rằng đây là giọng AI.
- **Giấy phép espeak-ng (GPL-3.0)** đi kèm Kokoro: xem lại nếu phát hành hay bán ứng dụng.
- **Số, viết tắt, giờ** ở cuối câu có thể bị nuốt âm. Đã gặp với `9 a.m.`. Cần chuẩn hoá trước và thêm test.
- **Model ảo giác** với câu quá ngắn: VieNeu tự gộp chunk dưới khoảng 10 ký tự. Khi tạo từng câu riêng, những câu như
  *"Yes."* hay *"OK!"* có thể đọc sai. Nên gộp với câu bên cạnh khi tạo giọng, hoặc kiểm tra bằng QA.
- **Thời gian tạo** bài dài trên CPU (hệ số 0,6). Bài 10 phút tốn khoảng 6 phút. Có thể bật `TIT_PRECISION=int8`
  để nhanh gấp khoảng 3 lần, chất lượng giảm nhẹ.

## Tham khảo

- [VieNeu-TTS (GitHub)](https://github.com/pnnbao97/VieNeu-TTS) · [Model card v3 Turbo](https://huggingface.co/ngoctham/VieNeu-TTS-v3-Turbo) · [Bài giới thiệu v3 Turbo](https://alphasignal.ai/news/open-source-vieneu-tts-v3-turbo-runs-48-khz-vietnamese-speech-on-cpus)
- Các tool shadowing tham khảo: [RecEcho](https://chromewebstore.google.com/detail/noefpifnpmfmdeaoejjbdegbpjhedhib), [ShadowEcho](https://chromewebstore.google.com/detail/fcjnmenfbppibcdhoobcpjnfpklimlpc), [Shadowing Player](https://apps.apple.com/app/id6514319878), [SpeakFox](https://mwm.ai/apps/speakfox-shadowing-english/6760902968)
- [Nghiên cứu về shadowing với video có phụ đề (PSLLT)](https://iastatedigitalpress.com/psllt/article/15330/galley/13735/view)
