import json
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Literal, Optional

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chinese, dialogue, engine as eng, english, music, shadow, store, text as textproc, thumbnail, youtube
from .config import PRECISION, ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

app = FastAPI(title="TIT Voice Studio", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store.init()
engine = eng.Engine()

MAX_CHARS = 50_000
CONSENT_SENTENCE = "Tôi đồng ý cho phép tạo bản sao giọng nói của chính tôi để sử dụng trong TIT Voice Studio."


def _require_ready() -> None:
    if engine.load_error:
        raise HTTPException(503, f"Mô hình lỗi: {engine.load_error}")
    if not engine.ready.is_set():
        raise HTTPException(503, "Mô hình đang khởi động, thử lại sau giây lát.")


@app.get("/api/health")
def health():
    return {
        "status": "error" if engine.load_error else ("ready" if engine.ready.is_set() else "loading"),
        "error": engine.load_error,
        "engine": "VieNeu-TTS v3 Turbo",
        "precision": PRECISION,
        "sample_rate": eng.SAMPLE_RATE,
        "emotion_tags": textproc.EMOTION_TAGS,
        "consent_sentence": CONSENT_SENTENCE,
    }


# ── giọng đọc ──────────────────────────────────────────────────────────────
@app.get("/api/voices")
def voices():
    _require_ready()
    return engine.voices()


@app.get("/api/voices/{voice}/preview")
def voice_preview(voice: str):
    """Trả file nghe thử nếu đã có; chưa có thì xếp hàng tạo và trả job."""
    _require_ready()
    if not engine.has_voice(voice):
        raise HTTPException(404, "Không có giọng này.")
    path = engine.preview_path(voice)
    if path.exists():
        return FileResponse(path, media_type="audio/wav")

    def run(job):
        if not path.exists():
            eng.write_wav(engine.synthesize(job, eng.PREVIEW_TEXT, voice, 1.0), path)
        return {"url": f"/api/voices/{voice}/preview"}

    job = engine.submit("preview", run)
    return {"job_id": job.id}


@app.post("/api/voices/clone")
async def clone_voice(
    name: str = Form(...),
    gender: str = Form("other"),
    consent: bool = Form(...),
    audio: UploadFile = File(...),
):
    _require_ready()
    name = name.strip()
    if not consent:
        raise HTTPException(400, "Cần xác nhận đây là giọng của chính bạn.")
    if not name or len(name) > 40:
        raise HTTPException(400, "Tên giọng phải từ 1 đến 40 ký tự.")
    if engine.has_voice(name):
        raise HTTPException(409, "Tên giọng đã tồn tại.")

    tmp = Path(tempfile.mkdtemp())
    src = tmp / f"upload{Path(audio.filename or 'rec.webm').suffix}"
    src.write_bytes(await audio.read())
    try:
        wav = eng.to_wav_48k(src, tmp / "reference.wav")
        seconds = sf.info(str(wav)).duration
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(400, "Không đọc được file ghi âm.")
    if not 3 <= seconds <= 20:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(400, f"Bản thu cần dài 3–20 giây (hiện {seconds:.1f} giây).")

    def run(job):
        try:
            return engine.clone_voice(name, wav, gender)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    job = engine.submit("clone", run)
    return {"job_id": job.id}


@app.delete("/api/voices/{voice}")
def delete_voice(voice: str):
    _require_ready()
    try:
        engine.delete_voice(voice)
    except KeyError:
        raise HTTPException(404, "Chỉ xoá được giọng nhân bản.")
    return {"ok": True}


# ── tạo giọng nói ──────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    text: str
    voice: str
    speed: float = Field(1.0, ge=0.5, le=2.0)


@app.post("/api/tts")
def tts(req: TTSRequest):
    _require_ready()
    text = req.text.strip()
    if not textproc.spoken_length(text):
        raise HTTPException(400, "Hãy nhập văn bản cần đọc.")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Tối đa {MAX_CHARS:,} ký tự mỗi lần.")
    if not engine.has_voice(req.voice):
        raise HTTPException(404, "Không có giọng này.")

    def run(job):
        audio = engine.synthesize(job, text, req.voice, req.speed)
        duration = eng.write_wav(audio, eng.history_wav(job.id))
        return store.add_history(job.id, text, req.voice, req.speed, duration, textproc.spoken_length(text))

    job = engine.submit("tts", run)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = engine.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy job.")
    ahead = sum(1 for j in engine.jobs.values() if j.status == "queued" and j.created < job.created)
    return {"id": job.id, "kind": job.kind, "status": job.status, "progress": round(job.progress, 3),
            "stage": job.stage, "error": job.error, "result": job.result, "queue_position": ahead}


# ── lịch sử ────────────────────────────────────────────────────────────────
@app.get("/api/history")
def history():
    return store.list_history()


@app.get("/api/history/{item_id}/audio")
def history_audio(item_id: str, format: str = "wav", download: bool = False):
    wav = eng.history_wav(item_id)
    if not store.get_history(item_id) or not wav.exists():
        raise HTTPException(404, "Không tìm thấy bản ghi.")
    path, media = (eng.to_mp3(wav), "audio/mpeg") if format == "mp3" else (wav, "audio/wav")
    filename = f"tit-voice-{item_id}{path.suffix}" if download else None
    return FileResponse(path, media_type=media, filename=filename)


@app.delete("/api/history/{item_id}")
def delete_history(item_id: str):
    store.delete_history(item_id)
    for suffix in (".wav", ".mp3"):
        eng.history_wav(item_id).with_suffix(suffix).unlink(missing_ok=True)
    return {"ok": True}


# ── luyện Shadowing ────────────────────────────────────────────────────────
def _download_stage(job):
    def progress(done, total):
        job.stage = f"Đang tải giọng bản xứ lần đầu ({done / 1e6:.0f}/{total / 1e6:.0f} MB)…"
        job.progress = done / total
    return progress


@app.get("/api/english")
def english_status():
    """Giọng tiếng Anh bản xứ (Kokoro): danh sách giọng và model đã tải chưa."""
    return english.status()


@app.get("/api/chinese")
def chinese_status():
    """Giọng tiếng Trung (Kokoro, dùng chung model với giọng tiếng Anh bản xứ)."""
    return chinese.status()


@app.get("/api/english/voices/{voice}/preview")
def english_preview(voice: str):
    """Nghe thử giọng Kokoro, cả tiếng Anh lẫn tiếng Trung."""
    _require_ready()
    zh = chinese.has_voice(voice)
    if not (zh or english.has_voice(voice)):
        raise HTTPException(404, "Không có giọng này.")
    path = engine.preview_path(voice)
    if path.exists():
        return FileResponse(path, media_type="audio/wav")

    def run(job):
        if not path.exists():
            if zh:
                audio = chinese.synthesize(chinese.PREVIEW_TEXT, voice, on_download=_download_stage(job))
            else:
                audio, _ = english.synthesize(english.PREVIEW_TEXT, voice, _download_stage(job))
            eng.write_wav(eng.normalize_loudness(audio), path)
        return {"url": f"/api/english/voices/{voice}/preview"}

    job = engine.submit("preview", run)
    return {"job_id": job.id}


class ShadowRequest(BaseModel):
    text: str
    voice: str
    title: str = Field("", max_length=80)
    repeats: int = Field(1, ge=1, le=3)
    slow_speed: float = Field(0.8, ge=0.6, le=1.0)
    gap_factor: float = Field(1.3, ge=0.8, le=2.5)
    full_run: bool = True
    aspect: Literal["16:9", "9:16"] = "16:9"


SHADOW_FILES = {
    "video": ("lesson.mp4", "video/mp4"),
    "audio": ("lesson.mp3", "audio/mpeg"),
    "srt": ("lesson.srt", "application/x-subrip"),
    "timeline": ("timeline.json", "application/json"),
}


@app.post("/api/shadow")
def create_shadow(req: ShadowRequest):
    _require_ready()
    lines = shadow.parse_lesson(req.text)
    if not lines:
        raise HTTPException(400, "Hãy nhập ít nhất một câu tiếng Anh.")
    if len(lines) > shadow.MAX_LINES:
        raise HTTPException(400, f"Tối đa {shadow.MAX_LINES} câu mỗi bài (hiện {len(lines)}).")
    for i, line in enumerate(lines, 1):
        if len(line.en) > shadow.MAX_LINE_CHARS:
            raise HTTPException(400, f"Câu {i} dài quá {shadow.MAX_LINE_CHARS} ký tự, hãy tách nhỏ.")
    native = english.is_native(req.voice)
    if not (english.has_voice(req.voice) if native else engine.has_voice(req.voice)):
        raise HTTPException(404, "Không có giọng này.")
    voice_label = english.label(req.voice) if native else req.voice
    settings = shadow.Settings(**req.model_dump(exclude={"text", "voice"}), voice=voice_label)

    def speak(job):   # luồng mô hình: 0 → 0.85
        def progress(p):
            job.stage = None
            job.progress = p * 0.85
        return shadow.synthesize_lines(engine.tts, lines, req.voice, progress, _download_stage(job))

    def render(job, spoken):   # luồng dựng: 0.85 → 1
        def progress(p):
            job.progress = 0.85 + p * 0.15
        clips, timings = spoken
        meta = shadow.build(job.id, lines, clips, settings, progress, timings)
        return store.add_shadow(job.id, meta["title"], voice_label, len(lines), meta["duration"], req.aspect)

    job = engine.submit("shadow", speak, then=render)
    return {"job_id": job.id, "lines": len(lines)}


@app.get("/api/shadow")
def list_shadow(kind: Literal["shadow", "dialogue"] = "shadow"):
    return store.list_shadow(kind)


# ── video hội thoại tiếng Trung ────────────────────────────────────────────
class DialogueRequest(BaseModel):
    text: str
    voice_a: str
    voice_b: str
    vi_voice: Optional[str] = None      # giọng VieNeu đọc nghĩa tiếng Việt; None = không đọc
    title: str = Field("", max_length=80)
    repeats: int = Field(2, ge=1, le=5)
    speed: float = Field(1.0, ge=0.6, le=1.2)
    speed2: Optional[float] = Field(None, ge=0.5, le=1.2)   # tốc độ lần đọc thứ 2; None = như lần 1
    pause: float = Field(1.0, ge=0.3, le=4.0)
    loops: int = Field(1, ge=1, le=dialogue.MAX_LOOPS)
    show_en: bool = True
    intro: bool = True
    music: Optional[str] = None         # id nhạc nền trong /api/music; None = không có nhạc
    music_volume: float = Field(0.4, ge=0.05, le=1.0)


@app.post("/api/dialogue")
def create_dialogue(req: DialogueRequest):
    _require_ready()
    utts = dialogue.parse_dialogue(req.text)
    if not utts:
        raise HTTPException(400, "Hãy nhập ít nhất một câu tiếng Trung.")
    if len(utts) > dialogue.MAX_LINES:
        raise HTTPException(400, f"Tối đa {dialogue.MAX_LINES} câu mỗi bài (hiện {len(utts)}).")
    for i, u in enumerate(utts, 1):
        if len(u.zh) > dialogue.MAX_ZH_CHARS:
            raise HTTPException(400, f"Câu {i} dài quá {dialogue.MAX_ZH_CHARS} chữ, hãy tách nhỏ.")
        if max(len(u.vi), len(u.en)) > dialogue.MAX_TEXT_CHARS:
            raise HTTPException(400, f"Nghĩa của câu {i} dài quá {dialogue.MAX_TEXT_CHARS} ký tự.")
        if not chinese.has_hanzi(u.zh):
            raise HTTPException(400, f"Câu {i} (“{u.zh}”) không có chữ Hán để đọc.")
    for v in (req.voice_a, req.voice_b):
        if not chinese.has_voice(v):
            raise HTTPException(404, "Không có giọng tiếng Trung này.")
    if req.vi_voice and not engine.has_voice(req.vi_voice):
        raise HTTPException(404, "Không có giọng tiếng Việt này.")
    if req.music and req.music not in {m["id"] for m in music.list_music()}:
        raise HTTPException(404, "Không có bản nhạc này.")
    labels = (chinese.label(req.voice_a), chinese.label(req.voice_b))
    settings = dialogue.Settings(**req.model_dump(exclude={"text", "voice_a", "voice_b", "vi_voice", "music"}),
                                 voice_a=labels[0], voice_b=labels[1], vi_voice=req.vi_voice or "",
                                 music=music.name(req.music) if req.music else "")
    voice_label = labels[0] if labels[0] == labels[1] else f"{labels[0]} & {labels[1]}"

    def speak(job):   # luồng mô hình: 0 → 0.7
        def progress(p):
            job.stage = None
            job.progress = p * 0.7

        def speak_vi(text):   # job giả: engine.synthesize tự ghi tiến độ của riêng nó
            return engine.synthesize(SimpleNamespace(progress=0.0), text, req.vi_voice, 1.0)

        return dialogue.synthesize(utts, (req.voice_a, req.voice_b), req.speed, speak_vi if req.vi_voice else None,
                                   progress, _download_stage(job), dialogue.second_speed(settings),
                                   dialogue.intro_text(req.title) if req.intro else "")

    def render(job, spoken):   # luồng dựng: 0.7 → 1
        def progress(p):
            job.progress = 0.7 + p * 0.3
        zh, zh2, vi, intro = spoken
        meta = dialogue.build(job.id, utts, zh, vi, settings, progress, zh2, intro,
                              music.path(req.music) if req.music else None)
        return store.add_shadow(job.id, meta["title"], voice_label, len(utts), meta["duration"], "16:9", "dialogue")

    job = engine.submit("dialogue", speak, then=render)
    return {"job_id": job.id, "lines": len(utts)}


# ── nhạc nền ───────────────────────────────────────────────────────────────
@app.get("/api/music")
def list_music():
    return music.list_music()


@app.post("/api/music")
async def add_music(file: UploadFile = File(...), name: str = Form("")):
    data = await file.read(music.MAX_UPLOAD_BYTES + 1)
    if len(data) > music.MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File nhạc tối đa {music.MAX_UPLOAD_BYTES // 2**20} MB.")
    title = (name.strip() or Path(file.filename or "Nhạc của tôi").stem)[:60]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"upload{Path(file.filename or '').suffix[:8]}"
        src.write_bytes(data)
        try:
            return music.add(src, title)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/music/{music_id}/audio")
def music_audio(music_id: str):
    p = music.path(music_id)
    if not p:
        raise HTTPException(404, "Không có bản nhạc này.")
    return FileResponse(p, media_type="audio/wav" if p.suffix == ".wav" else "audio/mp4")


@app.delete("/api/music/{music_id}")
def delete_music(music_id: str):
    try:
        music.remove(music_id)
    except KeyError:
        raise HTTPException(404, "Không xoá được bản nhạc này.")
    return {"ok": True}


@app.delete("/api/shadow/{item_id}")
def delete_shadow(item_id: str):
    if not store.get_shadow(item_id):
        raise HTTPException(404, "Không tìm thấy bài luyện.")
    store.delete_shadow(item_id)
    shutil.rmtree(shadow.lesson_dir(item_id), ignore_errors=True)
    return {"ok": True}


# ── đăng YouTube ───────────────────────────────────────────────────────────
@app.get("/api/youtube")
def youtube_status():
    return youtube.status()


@app.post("/api/youtube/client-secret")
async def youtube_client_secret(file: UploadFile = File(...)):
    try:
        youtube.save_client_secret(await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return youtube.status()


@app.post("/api/youtube/login")
def youtube_login():
    """Mở trang đăng nhập Google trên máy chạy backend; giao diện hỏi lại /api/youtube."""
    try:
        youtube.start_login()
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    return youtube.status()


@app.put("/api/youtube/accounts/{account_id}/active")
def youtube_set_active(account_id: str):
    try:
        youtube.set_active(account_id)
    except KeyError:
        raise HTTPException(404, "Không có tài khoản này.")
    return youtube.status()


@app.delete("/api/youtube/accounts/{account_id}")
def youtube_remove(account_id: str):
    try:
        youtube.remove_account(account_id)
    except KeyError:
        raise HTTPException(404, "Không có tài khoản này.")
    return youtube.status()


def _lesson(item_id: str) -> tuple:
    lesson = store.get_shadow(item_id)
    path = shadow.lesson_dir(item_id) / "timeline.json" if lesson else None
    if not lesson or not path.exists():
        raise HTTPException(404, "Không tìm thấy bài luyện.")
    return lesson, json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/shadow/{item_id}/youtube")
def shadow_youtube(item_id: str):
    """Nội dung gợi ý để đăng, kèm các lần đã đăng bài này."""
    lesson, timeline = _lesson(item_id)
    themes = {name: [c1, c2] for name, (c1, c2, *_rest) in thumbnail.THEMES.items()}
    key = "zh" if timeline.get("kind") == "dialogue" else "en"
    return {"draft": youtube.draft(lesson, timeline), "uploads": store.list_youtube(item_id), "themes": themes,
            "sentences": [line[key] for line in timeline["lines"]]}


class ThumbnailOptions(BaseModel):
    theme: Literal[tuple(thumbnail.THEMES)] = thumbnail.DEFAULT_THEME
    headline: str = Field("", max_length=40)
    quote: str = Field("", max_length=90)

    def render_kwargs(self) -> dict:
        return {"theme": self.theme, "headline": self.headline.strip() or None, "quote": self.quote.strip() or None}


@app.post("/api/shadow/{item_id}/thumbnail")
def shadow_thumbnail(item_id: str, opts: ThumbnailOptions):
    """Xem trước ảnh bìa YouTube (JPEG 1280×720)."""
    lesson, timeline = _lesson(item_id)
    with tempfile.TemporaryDirectory() as tmp:
        jpg = thumbnail.render(lesson, timeline, Path(tmp) / "thumb.jpg", **opts.render_kwargs())
        return Response(jpg.read_bytes(), media_type="image/jpeg")


class PublishRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=5000)
    tags: List[str] = []
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: Optional[datetime] = None
    account: Optional[str] = None
    thumbnail: ThumbnailOptions = ThumbnailOptions()


@app.post("/api/shadow/{item_id}/youtube")
def publish_shadow(item_id: str, req: PublishRequest):
    lesson, _ = _lesson(item_id)
    if "<" in req.title + req.description or ">" in req.title + req.description:
        raise HTTPException(400, "YouTube không nhận ký tự < và > trong tiêu đề và mô tả.")
    publish_at = req.publish_at
    if publish_at:
        publish_at = publish_at if publish_at.tzinfo else publish_at.astimezone()   # không ghi múi giờ: giờ máy
        if publish_at < datetime.now().astimezone() + timedelta(minutes=15):
            raise HTTPException(400, "Giờ công khai phải sau lúc này ít nhất 15 phút.")
    status = youtube.status()
    if not status["client_secret"] or not status["accounts"]:
        raise HTTPException(400, "Chưa kết nối tài khoản YouTube.")
    if req.account and req.account not in {a["id"] for a in status["accounts"]}:
        raise HTTPException(404, "Không có tài khoản này.")
    tags = [t.strip() for t in req.tags if t.strip()]

    def run(job):
        def progress(p):
            job.progress = p
        rec = youtube.upload(lesson, req.title.strip(), req.description, tags, req.privacy, publish_at,
                             req.account, progress, req.thumbnail.render_kwargs())
        row = store.add_youtube(item_id, rec["video_id"], rec["url"], rec["title"], rec["privacy"],
                                rec["publish_at"], rec["account"])
        return {**row, "note": rec["note"]}

    job = engine.submit_io("youtube", run)
    return {"job_id": job.id}


# Khai báo sau các route /api/shadow/{id}/youtube để không bắt nhầm chúng.
@app.get("/api/shadow/{item_id}/{kind}")
def shadow_file(item_id: str, kind: str, download: bool = False):
    if kind not in SHADOW_FILES:
        raise HTTPException(404, "Không có loại file này.")
    name, media = SHADOW_FILES[kind]
    lesson = store.get_shadow(item_id)
    if not lesson or not (path := shadow.lesson_dir(item_id) / name).exists():
        raise HTTPException(404, "Không tìm thấy bài luyện.")
    prefix = "tit-hoithoai" if lesson["kind"] == "dialogue" else "tit-shadowing"
    filename = f"{prefix}-{item_id}{path.suffix}" if download else None
    return FileResponse(path, media_type=media, filename=filename)


# ── từ điển phát âm ────────────────────────────────────────────────────────
class DictionaryBody(BaseModel):
    entries: Dict[str, str]


@app.get("/api/dictionary")
def get_dictionary():
    return store.load_dictionary()


@app.put("/api/dictionary")
def put_dictionary(body: DictionaryBody):
    return store.save_dictionary(body.entries)


# Bản build giao diện (npm run build) được phục vụ luôn tại "/".
_dist: Optional[Path] = ROOT.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
