import json
import logging
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Literal, Optional

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine as eng, english, shadow, store, text as textproc, youtube
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


@app.get("/api/english/voices/{voice}/preview")
def english_preview(voice: str):
    _require_ready()
    if not english.has_voice(voice):
        raise HTTPException(404, "Không có giọng này.")
    path = engine.preview_path(voice)
    if path.exists():
        return FileResponse(path, media_type="audio/wav")

    def run(job):
        if not path.exists():
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
def list_shadow():
    return store.list_shadow()


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
    return {"draft": youtube.draft(lesson, timeline), "uploads": store.list_youtube(item_id)}


class PublishRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=5000)
    tags: List[str] = []
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: Optional[datetime] = None
    account: Optional[str] = None


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
                             req.account, progress)
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
    if not store.get_shadow(item_id) or not (path := shadow.lesson_dir(item_id) / name).exists():
        raise HTTPException(404, "Không tìm thấy bài luyện.")
    filename = f"tit-shadowing-{item_id}{path.suffix}" if download else None
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
