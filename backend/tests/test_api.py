"""Kiểm thử tích hợp: chạy mô hình thật, dữ liệu ghi vào thư mục tạm."""
import io
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("TIT_DATA_DIR", tempfile.mkdtemp(prefix="tit-qa-"))
os.environ.setdefault("TIT_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "data" / "models"))

from fastapi.testclient import TestClient  # noqa: E402

from app import english  # noqa: E402
from app.main import app, engine  # noqa: E402

VOICE = "Trúc Ly"


@pytest.fixture(scope="module")
def client():
    c = TestClient(app)
    assert engine.ready.wait(180), engine.load_error
    return c


def wait_job(client, job_id, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def synth(client, text, voice=VOICE, speed=1.0):
    r = client.post("/api/tts", json={"text": text, "voice": voice, "speed": speed})
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    return job["result"]


def wav_of(client, item_id):
    r = client.get(f"/api/history/{item_id}/audio")
    assert r.status_code == 200
    return sf.read(io.BytesIO(r.content))


def test_health(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ready" and h["sample_rate"] == 48000


def test_voices(client):
    voices = client.get("/api/voices").json()
    assert len(voices) >= 25
    assert {"north", "central", "south"} <= {v["region"] for v in voices}
    assert {v["gender"] for v in voices} >= {"male", "female"}


@pytest.mark.parametrize(
    "body,status",
    [
        ({"text": "   ", "voice": VOICE}, 400),
        ({"text": "[nghỉ 2s]", "voice": VOICE}, 400),
        ({"text": "Xin chào", "voice": "Không có"}, 404),
        ({"text": "Xin chào", "voice": VOICE, "speed": 5}, 422),
        ({"text": "a" * 50_001, "voice": VOICE}, 400),
    ],
)
def test_tts_rejects_bad_input(client, body, status):
    assert client.post("/api/tts", json=body).status_code == status


def test_tts_produces_48k_wav_and_history(client):
    item = synth(client, "Xin chào, đây là bài kiểm tra chất lượng.")
    audio, sr = wav_of(client, item["id"])
    assert sr == 48000 and audio.ndim == 1
    assert abs(len(audio) / sr - item["duration"]) < 0.05
    assert 1.0 < item["duration"] < 10
    assert np.abs(audio).max() > 0.05, "audio gần như im lặng"
    assert np.abs(audio).max() <= 1.0
    assert any(h["id"] == item["id"] for h in client.get("/api/history").json())


def test_pause_tag_adds_silence(client):
    plain = synth(client, "Một hai ba. Bốn năm sáu.")
    paused = synth(client, "Một hai ba. [nghỉ 3s] Bốn năm sáu.")
    assert paused["duration"] - plain["duration"] > 2.3


def test_speed_changes_duration(client):
    text = "Hôm nay trời đẹp, chúng ta cùng đi dạo công viên nhé."
    slow = synth(client, text, speed=1.0)
    fast = synth(client, text, speed=1.5)
    assert fast["duration"] < slow["duration"] * 0.8


def test_mp3_download(client):
    item = synth(client, "Tải về dạng MP3.")
    r = client.get(f"/api/history/{item['id']}/audio?format=mp3&download=true")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content[:3] == b"ID3" or r.content[0] == 0xFF


def test_delete_history_removes_file(client):
    item = synth(client, "Bản này sẽ bị xoá.")
    assert client.delete(f"/api/history/{item['id']}").status_code == 200
    assert client.get(f"/api/history/{item['id']}/audio").status_code == 404


def test_dictionary_roundtrip(client):
    saved = client.put("/api/dictionary", json={"entries": {" KTX ": "ký túc xá", "": "bỏ"}}).json()
    assert saved == {"KTX": "ký túc xá"}
    assert client.get("/api/dictionary").json() == saved


def test_preview_generates_then_serves_file(client):
    r = client.get(f"/api/voices/{VOICE}/preview")
    if r.headers["content-type"].startswith("application/json"):
        assert wait_job(client, r.json()["job_id"])["status"] == "done"
        r = client.get(f"/api/voices/{VOICE}/preview")
    assert r.headers["content-type"] == "audio/wav" and len(r.content) > 10_000
    assert client.get("/api/voices/Không có/preview").status_code == 404


def _tone(seconds):
    buf = io.BytesIO()
    t = np.linspace(0, seconds, int(16000 * seconds), endpoint=False)
    sf.write(buf, 0.3 * np.sin(2 * np.pi * 220 * t), 16000, format="WAV")
    return buf.getvalue()


def test_clone_requires_consent_and_length(client):
    no_consent = client.post("/api/voices/clone", data={"name": "X", "consent": "false"},
                             files={"audio": ("a.wav", _tone(5), "audio/wav")})
    assert no_consent.status_code == 400
    too_short = client.post("/api/voices/clone", data={"name": "X", "consent": "true"},
                            files={"audio": ("a.wav", _tone(1), "audio/wav")})
    assert too_short.status_code == 400
    taken = client.post("/api/voices/clone", data={"name": VOICE, "consent": "true"},
                        files={"audio": ("a.wav", _tone(5), "audio/wav")})
    assert taken.status_code == 409


def test_clone_and_delete_custom_voice(client):
    # Dùng một bản do chính mô hình tạo làm giọng tham chiếu.
    ref = synth(client, "Tôi đồng ý cho phép tạo bản sao giọng nói của chính tôi để sử dụng.")
    wav = client.get(f"/api/history/{ref['id']}/audio").content
    r = client.post("/api/voices/clone", data={"name": "Giọng QA", "gender": "female", "consent": "true"},
                    files={"audio": ("ref.wav", wav, "audio/wav")})
    assert r.status_code == 200, r.text
    assert wait_job(client, r.json()["job_id"])["status"] == "done"
    voices = {v["id"]: v for v in client.get("/api/voices").json()}
    assert voices["Giọng QA"]["custom"] is True
    synth(client, "Giọng nhân bản đọc thử.", voice="Giọng QA")
    assert client.delete("/api/voices/Giọng QA").status_code == 200
    assert client.delete(f"/api/voices/{VOICE}").status_code == 404


def test_clone_rejects_unreadable_audio(client):
    r = client.post("/api/voices/clone", data={"name": "Hỏng", "consent": "true"},
                    files={"audio": ("rec.webm", b"not audio", "audio/webm")})
    assert r.status_code == 400


def test_output_is_loudness_normalized(client):
    import subprocess, re
    item = synth(client, "Độ to của giọng đọc cần ổn định, gần với các nền tảng trực tuyến.")
    wav = Path(os.environ["TIT_DATA_DIR"]) / "history" / f"{item['id']}.wav"
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    assert -17.5 < lufs < -14.5


@pytest.mark.parametrize(
    "body,status",
    [
        ({"text": "  \n | chỉ có nghĩa", "voice": VOICE}, 400),
        ({"text": "Hello.", "voice": "Không có"}, 404),
        ({"text": "Hello.", "voice": "kokoro:zz_nobody"}, 404),
        ({"text": "\n".join(["Hello there."] * 81), "voice": VOICE}, 400),
        ({"text": "word " * 70, "voice": VOICE}, 400),
        ({"text": "Hello.", "voice": VOICE, "aspect": "4:3"}, 422),
    ],
)
def test_shadow_rejects_bad_input(client, body, status):
    assert client.post("/api/shadow", json=body).status_code == status


def test_shadow_lesson_end_to_end(client):
    r = client.post("/api/shadow", json={
        "text": "Good morning, how are you? | Chào buổi sáng, bạn khoẻ không?\nI'd rather have a cup of tea.",
        "voice": "Adam", "title": "Bài QA", "slow_speed": 0.8,
    })
    assert r.status_code == 200, r.text
    assert r.json()["lines"] == 2
    job = wait_job(client, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    item = job["result"]
    assert item["title"] == "Bài QA" and item["lines"] == 2 and item["duration"] > 10
    assert any(s["id"] == item["id"] for s in client.get("/api/shadow").json())

    video = client.get(f"/api/shadow/{item['id']}/video")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and len(video.content) > 50_000
    mp3 = client.get(f"/api/shadow/{item['id']}/audio?download=true")
    assert mp3.headers["content-type"] == "audio/mpeg" and "attachment" in mp3.headers["content-disposition"]
    timeline = client.get(f"/api/shadow/{item['id']}/timeline").json()
    listens = [s for s in timeline["steps"] if s["kind"] == "listen"]
    assert len(listens) == 2 and all(0.5 < s["duration"] < 6 for s in listens)
    assert client.get(f"/api/shadow/{item['id']}/secret").status_code == 404

    assert client.delete(f"/api/shadow/{item['id']}").status_code == 200
    assert client.get(f"/api/shadow/{item['id']}/video").status_code == 404
    assert client.delete("/api/shadow/nothere").status_code == 404
    assert client.delete("/api/shadow/..%2Fhistory").status_code in (404, 405)


def test_english_voices_listed(client):
    data = client.get("/api/english").json()
    assert len(data["voices"]) >= 8 and all(v["id"].startswith("kokoro:") for v in data["voices"])
    assert client.get("/api/english/voices/kokoro:zz_nobody/preview").status_code == 404


@pytest.mark.skipif(not english.installed(), reason="chưa tải model Kokoro")
def test_shadow_lesson_with_native_voice(client):
    r = client.post("/api/shadow", json={
        "text": "The meeting starts at 3:30 p.m. | Cuộc họp bắt đầu lúc 3 giờ 30 chiều.\nPlease call me before 9 a.m.",
        "voice": "kokoro:bf_emma", "slow_speed": 0.8, "full_run": False,
    })
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    item = job["result"]
    assert item["voice"] == "Emma (Anh)"
    timeline = client.get(f"/api/shadow/{item['id']}/timeline").json()
    assert timeline["word_timing"] == "measured" and timeline["settings"]["voice"] == "Emma (Anh)"
    for st in timeline["steps"]:
        if st["kind"] in ("listen", "slow"):
            n = len(timeline["lines"][st["line"]]["en"].split())
            assert len(st["words"]) == n and st["words"] == sorted(st["words"]) and st["words"][-1] < st["duration"]

    preview = client.get("/api/english/voices/kokoro:bf_emma/preview")
    if preview.headers["content-type"].startswith("application/json"):
        assert wait_job(client, preview.json()["job_id"])["status"] == "done"
        preview = client.get("/api/english/voices/kokoro:bf_emma/preview")
    assert preview.headers["content-type"] == "audio/wav" and len(preview.content) > 50_000
    assert client.delete(f"/api/shadow/{item['id']}").status_code == 200
