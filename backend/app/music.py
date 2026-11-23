"""Nhạc nền cho video hội thoại: vài bản tự tạo sẵn và nhạc người dùng tải lên.

Bản có sẵn được tổng hợp bằng numpy ở lần dùng đầu (không phụ thuộc file nhạc có bản quyền) và
lặp liền mạch: tiếng ồn tạo bằng FFT nên tự tuần hoàn, nốt nhạc có tần số là bội của 1/độ dài.
Nhạc tải lên được đổi sang AAC mono 48 kHz và chuẩn hoá về -20 LUFS, nên thanh âm lượng cho
cùng một cảm giác với mọi bài. Khi trộn, nhạc tự nhỏ đi lúc có giọng đọc (sidechain).
"""
import json
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import soundfile as sf

from .config import DATA_DIR

SR = 48_000
MUSIC_DIR = DATA_DIR / "music"
LIBRARY = MUSIC_DIR / "library.json"
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
MIN_SECONDS = 5
_lock = threading.Lock()

# ── bản tự tạo ─────────────────────────────────────────────────────────────


def _shaped_noise(n: int, rng: np.random.Generator, lo: float, hi: float, tilt: float) -> np.ndarray:
    """Tiếng ồn lọc dải [lo, hi] Hz, nghiêng phổ 1/f^tilt; tạo trong miền tần số nên lặp liền mạch."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    shape = np.where((f > lo) & (f < hi), 1.0, 0.0) / np.maximum(f, 1.0) ** tilt
    shape *= np.clip((f - lo * 0.7) / (lo * 0.3 + 1), 0, 1) * np.clip((hi * 1.3 - f) / (hi * 0.3), 0, 1)
    return np.fft.irfft(spec * shape, n)


def _norm(x: np.ndarray, rms_db: float = -24.0) -> np.ndarray:
    x = x - x.mean()
    rms = np.sqrt(np.mean(x ** 2)) or 1.0
    x = x * (10 ** (rms_db / 20) / rms)
    peak = np.abs(x).max()
    return (x / peak * 0.89 if peak > 0.89 else x).astype(np.float32)


def _periodic(n: int, cycles: List[tuple]) -> np.ndarray:
    """Đường cong chậm, tuần hoàn đúng `n` mẫu: tổng các sin với số chu kỳ nguyên."""
    t = np.arange(n) / n
    return sum(a * np.sin(2 * np.pi * k * t + ph) for k, a, ph in cycles)


def rain(seconds: int = 60, seed: int = 7) -> np.ndarray:
    """Mưa nhẹ: nền rì rào + hạt mưa lách tách + từng cơn to nhỏ."""
    n = seconds * SR
    rng = np.random.default_rng(seed)
    bed = _shaped_noise(n, rng, 250, 9000, 0.35)
    gust = 1 + 0.25 * _periodic(n, [(3, 1, 0.3), (7, 0.5, 1.9)])
    drops = np.zeros(n)
    k = np.arange(int(0.012 * SR))
    for pos in rng.integers(0, n, seconds * 9):
        tick = rng.standard_normal(len(k)) * np.exp(-k / (0.0025 * SR)) * rng.uniform(0.2, 1.0)
        idx = (pos + k) % n          # quấn vòng: hạt mưa cuối bài nối sang đầu bài
        drops[idx] += tick
    drops = np.fft.irfft(np.fft.rfft(drops) * (np.fft.rfftfreq(n, 1 / SR) > 1500), n)
    return _norm(bed * gust + drops * 0.3)


def waves(seconds: int = 64, seed: int = 11) -> np.ndarray:
    """Sóng biển: tiếng ồn trầm dâng lên rút xuống chừng 8 giây một nhịp."""
    n = seconds * SR
    rng = np.random.default_rng(seed)
    low = _shaped_noise(n, rng, 60, 1800, 0.6)
    hiss = _shaped_noise(n, rng, 1500, 9000, 0.2)
    t = np.arange(n) / n
    swell = np.sin(np.pi * (seconds // 8) * t + 0.4 * np.sin(2 * np.pi * 3 * t)) ** 2
    return _norm(low * (0.25 + swell) + hiss * 0.3 * swell ** 2)


def pad(seconds: int = 64) -> np.ndarray:
    """Nền êm: bốn hợp âm ngân dài (Cmaj9 → Am9 → Fmaj9 → G6), chuyển mềm, lặp mỗi `seconds` giây."""
    n = seconds * SR
    t = np.arange(n) / SR
    chords = [  # nốt MIDI
        [48, 55, 59, 62, 64], [45, 52, 55, 59, 60], [41, 48, 52, 55, 57], [43, 50, 55, 57, 59],
    ]
    seg = seconds / len(chords)
    out = np.zeros(n)
    for i, notes in enumerate(chords):
        # cửa sổ cosin quanh đoạn của hợp âm, đo theo vòng tròn để hợp âm cuối hoà vào hợp âm đầu
        centre = (i + 0.5) * seg
        d = np.abs((t - centre + seconds / 2) % seconds - seconds / 2)
        env = np.clip((seg / 2 + 1.5 - d) / 3.0, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        for m in notes:
            f0 = 440 * 2 ** ((m - 69) / 12)
            for mult, amp in ((1, 1.0), (2, 0.25), (3, 0.08)):
                for det in (-0.0018, 0.0018):        # hai dây lệch nhẹ cho dày tiếng
                    f = round(f0 * mult * (1 + det) * seconds) / seconds   # bội của 1/seconds: lặp liền mạch
                    out += env * amp * np.sin(2 * np.pi * f * t)
    shimmer = 1 + 0.08 * _periodic(n, [(5, 1, 0.0), (11, 0.5, 2.0)])
    return _norm(out * shimmer, -23.0)


BUILTIN = {   # id → (tên, hàm tạo)
    "builtin-pad": ("Nền êm (piano pad)", pad),
    "builtin-rain": ("Mưa nhẹ", rain),
    "builtin-waves": ("Sóng biển", waves),
}

# ── thư viện ───────────────────────────────────────────────────────────────


def _load() -> Dict[str, dict]:
    try:
        return json.loads(LIBRARY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, dict]) -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _valid_id(music_id: str) -> bool:
    return music_id in BUILTIN or re.fullmatch(r"[0-9a-f]{12}", music_id) is not None


def path(music_id: str) -> Optional[Path]:
    """File nhạc của `music_id` (bản có sẵn được tạo ở lần gọi đầu); None nếu không có."""
    if not _valid_id(music_id):
        return None
    if music_id in BUILTIN:
        p = MUSIC_DIR / f"{music_id}.wav"
        with _lock:
            if not p.exists():
                MUSIC_DIR.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".part.wav")
                sf.write(str(tmp), BUILTIN[music_id][1](), SR, subtype="PCM_16")
                tmp.rename(p)
        return p
    p = MUSIC_DIR / f"{music_id}.m4a"
    return p if p.exists() else None


def name(music_id: str) -> str:
    if music_id in BUILTIN:
        return BUILTIN[music_id][0]
    return _load().get(music_id, {}).get("name", music_id)


def list_music() -> List[dict]:
    out = [{"id": k, "name": v[0], "builtin": True, "duration": None} for k, v in BUILTIN.items()]
    for k, v in sorted(_load().items(), key=lambda kv: -kv[1].get("added", 0)):
        out.append({"id": k, "name": v["name"], "builtin": False, "duration": v.get("duration")})
    return out


def _probe_seconds(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def add(src: Path, title: str) -> dict:
    """Nhập một file nhạc (mp3, m4a, wav, cả video): chỉ lấy tiếng, mono 48 kHz, -20 LUFS."""
    import time

    music_id = uuid.uuid4().hex[:12]
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    dst = MUSIC_DIR / f"{music_id}.m4a"
    proc = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR),
                           "-af", "loudnorm=I=-20:TP=-2:LRA=11", "-c:a", "aac", "-b:a", "160k", str(dst)],
                          capture_output=True)
    if proc.returncode or not dst.exists():
        dst.unlink(missing_ok=True)
        raise ValueError("Không đọc được file nhạc này.")
    seconds = _probe_seconds(dst)
    if seconds < MIN_SECONDS:
        dst.unlink(missing_ok=True)
        raise ValueError(f"Bản nhạc cần dài ít nhất {MIN_SECONDS} giây.")
    with _lock:
        data = _load()
        data[music_id] = {"name": title, "duration": round(seconds, 1), "added": time.time()}
        _save(data)
    return {"id": music_id, "name": title, "builtin": False, "duration": round(seconds, 1)}


def remove(music_id: str) -> None:
    if music_id in BUILTIN or not _valid_id(music_id):
        raise KeyError(music_id)
    with _lock:
        data = _load()
        if music_id not in data:
            raise KeyError(music_id)
        data.pop(music_id)
        _save(data)
    (MUSIC_DIR / f"{music_id}.m4a").unlink(missing_ok=True)


# ── trộn vào video ─────────────────────────────────────────────────────────


def mix(video: Path, music: Path, volume: float, total_s: float, mp4_out: Path, mp3_out: Path,
        on_progress: Optional[Callable[[float], None]] = None) -> None:
    """Trộn nhạc (lặp hết video) dưới giọng đọc; hình chép nguyên, tiếng encode lại một lần cho cả MP4 và MP3.

    `volume` 0–1 là độ to so với mức chuẩn của nhạc (-20 LUFS). Nhạc vào dần 2 giây, ra dần 4 giây
    cuối, và tự nhỏ đi khi có giọng (sidechain) để không lấn tiếng đọc.
    """
    fade_out = max(0.0, total_s - 4)
    graph = (f"[1:a]aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=mono,volume={volume:.3f},"
             f"afade=t=in:d=2,afade=t=out:st={fade_out:.3f}:d=4[m];"
             "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,asplit=2[v][sc];"
             "[m][sc]sidechaincompress=threshold=0.02:ratio=5:attack=40:release=700[duck];"
             "[v][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,asplit=2[a1][a2]")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
           "-filter_complex", graph,
           "-map", "0:v", "-map", "[a1]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
           str(mp4_out),
           "-map", "[a2]", "-b:a", "128k", str(mp3_out),
           "-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if on_progress and line.startswith("out_time_us=") and line[12:].strip().isdigit():
            on_progress(min(1.0, int(line[12:]) / 1e6 / max(total_s, 1)))
    err = proc.stderr.read()
    if proc.wait():
        raise RuntimeError(f"Không trộn được nhạc nền: {err.strip()[-300:]}")
