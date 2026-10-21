import logging
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine as eng, store, text as textproc
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
            "error": job.error, "result": job.result, "queue_position": ahead}


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
