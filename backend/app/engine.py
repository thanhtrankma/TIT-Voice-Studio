"""Bọc VieNeu-TTS: nạp mô hình một lần, chạy mọi yêu cầu tuần tự trên một luồng riêng.

Mô hình ONNX không an toàn khi gọi song song, nên mọi việc (tạo giọng, nghe thử,
nhân bản) đi qua một hàng đợi duy nhất. API chỉ tạo job rồi trả về ngay.
Phần việc không cần mô hình (dựng video) chạy tiếp ở một luồng riêng để hàng đợi đi tiếp;
việc mạng chạy lâu (đăng YouTube) có luồng riêng nữa để không giữ chân việc dựng.
"""
import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import soundfile as sf

from . import model_files, store, text as textproc
from .config import DATA_DIR, HISTORY_DIR, PRECISION, VOICES_FILE

log = logging.getLogger("tit.engine")

SAMPLE_RATE = 48_000
TARGET_LUFS = -16
PREVIEW_DIR = DATA_DIR / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_TEXT = "Xin chào, đây là giọng đọc của tôi. Rất vui được đồng hành cùng bạn hôm nay."

REGIONS = {"Bắc": "north", "Trung": "central", "Nam": "south"}


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"   # queued | running | done | error
    progress: float = 0.0
    stage: Optional[str] = None   # mô tả bước đang chạy khi khác bước thường (vd. đang tải model)
    error: Optional[str] = None
    result: Optional[dict] = None
    created: float = field(default_factory=time.time)


class Engine:
    def __init__(self) -> None:
        self.tts = None
        self.ready = threading.Event()
        self.load_error: Optional[str] = None
        self.jobs: Dict[str, Job] = {}
        self._queue: "queue.Queue[tuple[Job, Callable[[Job], Any], Optional[Callable[[Job, Any], dict]]]]" = queue.Queue()
        self._post = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
        self._io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload")
        self._custom: Dict[str, dict] = {}
        threading.Thread(target=self._run, daemon=True, name="tts-worker").start()

    # ── vòng đời ────────────────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            model_files.install()
            from vieneu import Vieneu

            self.tts = Vieneu(precision=PRECISION)
            self._load_custom_voices()
            self.ready.set()
            log.info("VieNeu ready (%s)", PRECISION)
        except Exception as e:   # để /health báo lỗi thay vì sập server
            log.exception("Không nạp được mô hình")
            self.load_error = str(e)
            return
        while True:
            job, fn, then = self._queue.get()
            job.status = "running"
            if not then:
                self._finish(job, fn)
                continue
            try:
                first = fn(job)
            except Exception as e:
                self._fail(job, e)
                continue
            self._post.submit(self._finish, job, lambda j, r=first, then=then: then(j, r))

    @staticmethod
    def _finish(job: Job, fn: Callable[[Job], Any]) -> None:
        try:
            job.result = fn(job)
            job.progress = 1.0
            job.status = "done"
        except Exception as e:
            Engine._fail(job, e)

    @staticmethod
    def _fail(job: Job, e: Exception) -> None:
        log.exception("Job %s lỗi", job.id, exc_info=e)
        job.error = str(e)
        job.status = "error"

    def submit(self, kind: str, fn: Callable[[Job], Any], then: Optional[Callable[[Job, Any], dict]] = None) -> Job:
        """`then` (nếu có) nhận kết quả của `fn` và chạy ở luồng dựng, không giữ luồng mô hình."""
        job = self._new_job(kind)
        self._queue.put((job, fn, then))
        return job

    def submit_io(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        """Việc không cần mô hình mà chờ mạng lâu (đăng YouTube): chạy lần lượt ở luồng riêng."""
        job = self._new_job(kind)

        def run() -> None:
            job.status = "running"
            self._finish(job, fn)

        self._io.submit(run)
        return job

    def _new_job(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        self.jobs[job.id] = job
        self._prune_jobs()
        return job

    def _prune_jobs(self) -> None:
        cutoff = time.time() - 3600
        for jid in [j.id for j in self.jobs.values() if j.created < cutoff and j.status in ("done", "error")]:
            self.jobs.pop(jid, None)

    # ── giọng đọc ───────────────────────────────────────────────────────────
    def voices(self) -> List[dict]:
        if not self.tts:
            return []
        out = []
        from vieneu.v3turbo import sorted_voices

        for name, v in sorted_voices(self.tts._preset_voices):
            parts = [p.strip() for p in (v.get("description") or "").split("·")]
            region = REGIONS.get(parts[1]) if len(parts) > 1 else None
            style = parts[2] if len(parts) > 2 else ""
            out.append({
                "id": name,
                "name": name,
                "gender": v.get("gender") or "",
                "region": region,
                "style": style,
                "description": v.get("description") or "",
                "featured": v.get("featured") is not None,
                "custom": name in self._custom,
            })
        return out

    def has_voice(self, name: str) -> bool:
        return bool(self.tts and self.tts.resolve_voice_name(name))

    def _load_custom_voices(self) -> None:
        if not VOICES_FILE.exists():
            return
        data = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
        for name, v in data.items():
            self._custom[name] = v
            self.tts._preset_voices[name] = {
                "description": v.get("description", ""),
                "gender": v.get("gender", ""),
                "style": self.tts.default_style,
                "featured": None,
                "aliases": [],
                "speaker_emb": np.asarray(v["speaker_emb"], dtype=np.float32),
                "codes": None if v.get("codes") is None else np.asarray(v["codes"], dtype=np.int64),
            }

    def _save_custom_voices(self) -> None:
        VOICES_FILE.write_text(json.dumps(self._custom, ensure_ascii=False), encoding="utf-8")

    def clone_voice(self, name: str, ref_path: Path, gender: str) -> dict:
        region_label = "Giọng nhân bản"
        gender_label = {"male": "Nam", "female": "Nữ"}.get(gender, "Khác")
        description = f"{gender_label} · {region_label}"
        self.tts.add_voice(name, str(ref_path), description=description, gender=gender)
        v = self.tts._preset_voices[name]
        self._custom[name] = {
            "description": description,
            "gender": gender,
            "speaker_emb": np.asarray(v["speaker_emb"]).reshape(-1).round(6).tolist(),
            "codes": None if v.get("codes") is None else np.asarray(v["codes"], dtype=int).tolist(),
        }
        self._save_custom_voices()
        (PREVIEW_DIR / f"{_safe(name)}.wav").unlink(missing_ok=True)
        return {"id": name}

    def delete_voice(self, name: str) -> None:
        if name not in self._custom:
            raise KeyError(name)
        self._custom.pop(name)
        self.tts.remove_voice(name)
        self._save_custom_voices()
        (PREVIEW_DIR / f"{_safe(name)}.wav").unlink(missing_ok=True)

    # ── tạo giọng ───────────────────────────────────────────────────────────
    def synthesize(self, job: Job, text: str, voice: str, speed: float) -> np.ndarray:
        segments = textproc.to_segments(text, store.load_dictionary())
        spoken = [s for s in segments if isinstance(s, str)]
        if not spoken:
            raise ValueError("Văn bản không có nội dung để đọc.")
        parts: List[np.ndarray] = []
        done = 0
        for seg in segments:
            if isinstance(seg, textproc.Pause):
                parts.append(np.zeros(int(seg.seconds * SAMPLE_RATE), dtype=np.float32))
                continue
            audio = self.tts.infer(seg, voice=voice)
            parts.append(np.asarray(audio, dtype=np.float32))
            done += 1
            job.progress = done / len(spoken) * 0.95
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        if abs(speed - 1.0) > 0.01:
            audio = change_speed(audio, speed)
        return normalize_loudness(audio)

    def preview_path(self, voice: str) -> Path:
        return PREVIEW_DIR / f"{_safe(voice)}.wav"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)


def change_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    """Đổi tốc độ, giữ cao độ, bằng bộ lọc atempo của ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-filter:a", f"atempo={speed:.3f}", "-f", "f32le", "pipe:1"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _ffmpeg_f32(audio: np.ndarray, filt: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-filter:a", filt, "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    )


def normalize_loudness(audio: np.ndarray) -> np.ndarray:
    """Đưa độ to về TARGET_LUFS (chuẩn EBU R128, hai lượt, tăng giảm tuyến tính).

    Mô hình ra khoảng -19.5 LUFS, nhỏ hơn hẳn các nền tảng online (~-15). Bản quá ngắn
    (dưới 0.4 giây) không đo được nên giữ nguyên.
    """
    if len(audio) < SAMPLE_RATE * 0.4:
        return audio
    target = f"I={TARGET_LUFS}:TP=-1.5:LRA=11"
    log_text = _ffmpeg_f32(audio, f"loudnorm={target}:print_format=json").stderr.decode()
    measured = json.loads(log_text[log_text.rindex("{"):log_text.rindex("}") + 1])
    if measured["input_i"] in ("-inf", "inf"):
        return audio
    second = (f"loudnorm={target}:linear=true:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
              f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
              f":offset={measured['target_offset']}")
    return np.frombuffer(_ffmpeg_f32(audio, second).stdout, dtype=np.float32)


def write_wav(audio: np.ndarray, path: Path) -> float:
    sf.write(str(path), audio, SAMPLE_RATE, subtype="PCM_16")
    return len(audio) / SAMPLE_RATE


def to_mp3(wav: Path) -> Path:
    mp3 = wav.with_suffix(".mp3")
    if not mp3.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "192k", str(mp3)], check=True)
    return mp3


def to_wav_48k(src: Path, dst: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "48000", str(dst)], check=True)
    return dst


def history_wav(item_id: str) -> Path:
    return HISTORY_DIR / f"{item_id}.wav"
