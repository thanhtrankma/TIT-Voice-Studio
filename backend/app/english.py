"""Giọng tiếng Anh bản xứ cho bài luyện Shadowing: Kokoro-82M chạy bằng kokoro-onnx.

VieNeu đọc tiếng Anh theo kiểu người Việt và hay đọc sai câu khó ("The meeting" thành
"Committing"). Kokoro có giọng Mỹ/Anh bản xứ, đọc đúng hơn, và báo lúc phát từng âm vị,
nên tô sáng từng từ khớp thật thay vì ước lượng theo âm tiết.

Model (~190 MB) chỉ tải ở lần dùng đầu. Mọi lời gọi đi qua luồng mô hình của Engine,
nên không cần khoá riêng. espeak-ng (đi kèm espeakng-loader, dùng để chuyển chữ thành
âm vị) theo giấy phép GPL-3.0; Kokoro là Apache-2.0, kokoro-onnx là MIT.
"""
import hashlib
import logging
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np

from . import engine as eng
from .config import MODELS_DIR

log = logging.getLogger("tit.english")

PREFIX = "kokoro:"
SAMPLE_RATE = 24_000
MODEL_DIR = MODELS_DIR / "kokoro"
BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {   # tên file → (sha256, số byte)
    "kokoro-v1.0.fp16.onnx": ("f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96", 163_527_961),
    "voices-v1.0.bin": ("bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", 28_214_398),
}
# Mốc âm vị của Kokoro rơi sau lúc âm thanh bật lên khoảng 30–130 ms (đo bằng năng lượng sau
# khoảng lặng và bằng Whisper), nên tô sáng sớm hơn một chút để khớp lúc nghe thấy từ.
HIGHLIGHT_LEAD_S = 0.08
PREVIEW_TEXT = "Hi there! I'm your English speaking partner. Let's practice together, one sentence at a time."

# Các giọng được đánh giá cao nhất trong bộ voices-v1.0 (Kokoro VOICES.md), chia theo giọng Mỹ/Anh.
_VOICES = [
    ("af_heart", "Heart", "female", "us", True),
    ("af_bella", "Bella", "female", "us", False),
    ("af_sarah", "Sarah", "female", "us", False),
    ("am_michael", "Michael", "male", "us", True),
    ("am_fenrir", "Fenrir", "male", "us", False),
    ("am_puck", "Puck", "male", "us", False),
    ("bf_emma", "Emma", "female", "uk", True),
    ("bf_isabella", "Isabella", "female", "uk", False),
    ("bm_george", "George", "male", "uk", True),
    ("bm_fable", "Fable", "male", "uk", False),
]
ACCENTS = {"us": ("Mỹ", "en-us"), "uk": ("Anh", "en-gb")}

ProgressFn = Callable[[int, int], None]   # (đã tải, tổng) tính bằng byte


def voices() -> List[dict]:
    out = []
    for key, name, gender, accent, featured in _VOICES:
        label = ACCENTS[accent][0]
        out.append({
            "id": PREFIX + key, "name": name, "gender": gender, "region": None, "accent": accent,
            "style": f"Giọng {label}", "description": f"{'Nữ' if gender == 'female' else 'Nam'} · Tiếng Anh-{label}",
            "featured": featured, "custom": False,
        })
    return out


def _find(voice: str) -> Optional[tuple]:
    return next((v for v in _VOICES if PREFIX + v[0] == voice), None)


def is_native(voice: str) -> bool:
    return voice.startswith(PREFIX)


def has_voice(voice: str) -> bool:
    return _find(voice) is not None


def label(voice: str) -> str:
    """Tên hiển thị trên video và trong danh sách bài: "Heart (Mỹ)"."""
    v = _find(voice)
    return f"{v[1]} ({ACCENTS[v[3]][0]})" if v else voice


def installed() -> bool:
    return all((MODEL_DIR / name).exists() for name in FILES)


def status() -> dict:
    missing = sum(size for name, (_, size) in FILES.items() if not (MODEL_DIR / name).exists())
    return {"installed": not missing, "download_mb": round(missing / 1e6), "voices": voices()}


# ── tải model ──────────────────────────────────────────────────────────────


def download(on_progress: Optional[ProgressFn] = None) -> None:
    """Tải file còn thiếu vào MODEL_DIR, kiểm tra sha256 rồi mới đổi tên thành file thật."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    missing = {n: v for n, v in FILES.items() if not (MODEL_DIR / n).exists()}
    total, done = sum(size for _, size in missing.values()), 0
    for name, (sha, _) in missing.items():
        part = MODEL_DIR / f"{name}.part"
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(BASE_URL + name, timeout=60) as res, open(part, "wb") as fp:
                while chunk := res.read(1 << 20):
                    fp.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Không tải được giọng bản xứ ({name}): {e}") from e
        if digest.hexdigest() != sha:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"File {name} tải về bị lỗi (sai mã kiểm tra), hãy thử lại.")
        part.rename(MODEL_DIR / name)
        log.info("Đã tải %s", name)


def _espeak_config():
    """espeak-ng hỏng ("Error processing file … phontab") khi đường dẫn dữ liệu quá dài:
    khi đó chép dữ liệu (~19 MB) sang thư mục model, đường dẫn ngắn hơn."""
    import espeakng_loader
    from kokoro_onnx import EspeakConfig

    data = Path(espeakng_loader.get_data_path())
    if len(str(data)) > 120:
        short = MODEL_DIR / "espeak-ng-data"
        if not short.exists():
            shutil.copytree(data, short)
        data = short
    return EspeakConfig(espeakng_loader.get_library_path(), str(data))


_kokoro = None


def model(on_progress: Optional[ProgressFn] = None):
    global _kokoro
    if _kokoro is None:
        if not installed():
            download(on_progress)
        from kokoro_onnx import Kokoro

        _kokoro = Kokoro(str(MODEL_DIR / "kokoro-v1.0.fp16.onnx"), str(MODEL_DIR / "voices-v1.0.bin"),
                         espeak_config=_espeak_config())
        log.info("Kokoro ready")
    return _kokoro


# ── đọc câu ────────────────────────────────────────────────────────────────


def group_starts(timings) -> List[float]:
    """Gộp mốc âm vị thành lúc bắt đầu từng từ âm vị (các từ cách nhau bằng âm vị " ")."""
    starts, new = [], True
    for t in timings:
        if t.phoneme == " ":
            new = True
        elif new:
            starts.append(t.start)
            new = False
    return starts


def align_words(words: List[str], groups: List[float], count: Callable[[str], int]) -> Optional[List[float]]:
    """Ghép mỗi từ hiển thị với nhóm âm vị của nó.

    Thường espeak giữ nguyên số từ ("3:30", "p.m." vẫn là một nhóm) nên ghép thẳng. Khi lệch
    (số dài đọc thành nhiều từ), đếm số nhóm của từng từ khi đọc riêng; vẫn lệch thì trả None
    để bên gọi quay về ước lượng.
    """
    if not words or not groups:
        return None
    if len(groups) == len(words):
        return list(groups)
    counts = [count(w) for w in words]
    if sum(counts) != len(groups):
        return None
    out, idx = [], 0
    for c in counts:
        out.append(groups[min(idx, len(groups) - 1)])
        idx += c
    return out


def resample(audio: np.ndarray, src: int = SAMPLE_RATE) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(src), "-ac", "1", "-i", "pipe:0",
         "-ar", str(eng.SAMPLE_RATE), "-f", "f32le", "pipe:1"],
        input=audio.astype(np.float32).tobytes(), capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def synthesize(text: str, voice: str, on_download: Optional[ProgressFn] = None) -> Tuple[np.ndarray, Optional[List[float]]]:
    """Đọc một câu, trả audio 48 kHz và lúc bắt đầu từng từ của `text.split()` (giây)."""
    v = _find(voice)
    if not v:
        raise ValueError(f"Không có giọng {voice}.")
    k = model(on_download)
    lang = ACCENTS[v[3]][1]
    audio, sr, timings = k.create_timed(text, voice=v[0], lang=lang)

    def count(word: str) -> int:
        return len(k.tokenizer.phonemize(word, lang).split())

    starts = align_words(text.split(), [max(0.0, t - HIGHLIGHT_LEAD_S) for t in group_starts(timings)], count)
    return resample(np.asarray(audio, dtype=np.float32), sr), starts
