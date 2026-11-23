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


ZH_A, ZH_B = "kokoro:zf_xiaoxiao", "kokoro:zm_yunxi"


@pytest.mark.parametrize(
    "body,status",
    [
        ({"text": "  \n | chỉ có nghĩa", "voice_a": ZH_A, "voice_b": ZH_B}, 400),
        ({"text": "Hello there.", "voice_a": ZH_A, "voice_b": ZH_B}, 400),          # không có chữ Hán
        ({"text": "你好。", "voice_a": "kokoro:af_heart", "voice_b": ZH_B}, 404),   # giọng tiếng Anh
        ({"text": "你好。", "voice_a": ZH_A, "voice_b": ZH_B, "vi_voice": "Không có"}, 404),
        ({"text": "你好。\n" * 301, "voice_a": ZH_A, "voice_b": ZH_B}, 400),
        ({"text": "好" * 81, "voice_a": ZH_A, "voice_b": ZH_B}, 400),
        ({"text": "你好。", "voice_a": ZH_A, "voice_b": ZH_B, "loops": 0}, 422),
        ({"text": "你好。", "voice_a": ZH_A, "voice_b": ZH_B, "speed2": 0.3}, 422),
    ],
)
def test_dialogue_rejects_bad_input(client, body, status):
    assert client.post("/api/dialogue", json=body).status_code == status


def test_chinese_voices_listed(client):
    data = client.get("/api/chinese").json()
    assert len(data["voices"]) == 8 and all(v["accent"] == "zh" for v in data["voices"])


@pytest.mark.skipif(not english.installed(), reason="chưa tải model Kokoro")
def test_dialogue_end_to_end(client):
    r = client.post("/api/dialogue", json={
        "text": "你*抽烟*吗？ | Bạn *hút thuốc* không? | Do you smoke?\n不抽，谢谢。 | Không, cảm ơn.",
        "voice_a": ZH_A, "voice_b": ZH_B, "vi_voice": "Adam", "title": "Hội thoại QA", "repeats": 2, "loops": 2,
        "speed2": 0.7,
    })
    assert r.status_code == 200, r.text
    job = wait_job(client, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    item = job["result"]
    assert item["kind"] == "dialogue" and item["voice"] == "Xiaoxiao & Yunxi" and item["lines"] == 2
    assert any(s["id"] == item["id"] for s in client.get("/api/shadow?kind=dialogue").json())
    assert all(s["id"] != item["id"] for s in client.get("/api/shadow").json())    # tab Shadowing không lẫn

    timeline = client.get(f"/api/shadow/{item['id']}/timeline").json()
    assert timeline["loops"] == 2 and timeline["duration"] == pytest.approx(item["duration"])
    kinds = [s["kind"] for s in timeline["steps"] if s["kind"] != "pause"]
    assert kinds == ["zh", "vi", "zh2", "zh", "vi", "zh2"]   # nghĩa Việt sau lần đầu, lần 2 đọc chậm 0.7x
    reads = {(s["kind"], s["line"]): s["duration"] for s in timeline["steps"] if s["kind"] != "pause"}
    assert all(0.4 < d < 5 for d in reads.values())
    assert all(reads[("zh2", i)] > reads[("zh", i)] * 1.2 for i in (0, 1))   # bản đọc chậm dài hơn thật
    video = client.get(f"/api/shadow/{item['id']}/video?download=true")
    assert video.headers["content-type"] == "video/mp4" and "tit-hoithoai-" in video.headers["content-disposition"]
    yt = client.get(f"/api/shadow/{item['id']}/youtube").json()
    assert yt["sentences"] == ["你抽烟吗？", "不抽，谢谢。"] and "Pinyin" in yt["draft"]["title"]

    preview = client.get(f"/api/english/voices/{ZH_B}/preview")
    if preview.headers["content-type"].startswith("application/json"):
        assert wait_job(client, preview.json()["job_id"])["status"] == "done"
        preview = client.get(f"/api/english/voices/{ZH_B}/preview")
    assert preview.headers["content-type"] == "audio/wav" and len(preview.content) > 50_000
    assert client.delete(f"/api/shadow/{item['id']}").status_code == 200


def test_youtube_publish_flow(client, monkeypatch, tmp_path):
    from datetime import datetime, timedelta

    from app import shadow, store, youtube

    for name, value in [("YT_DIR", tmp_path), ("CLIENT_SECRETS", tmp_path / "client_secret.json"),
                        ("TOKENS_DIR", tmp_path / "tokens"), ("ACCOUNTS_FILE", tmp_path / "accounts.json")]:
        monkeypatch.setattr(youtube, name, value)
    tone = (0.3 * np.sin(np.linspace(0, 2 * np.pi * 330, 48_000))).astype(np.float32)
    shadow.build("abcdef0000cc", [shadow.Line("See you soon.", "Hẹn gặp lại.")], [tone],
                 shadow.Settings(voice="Thử"), lambda p: None)
    store.add_shadow("abcdef0000cc", "Bài YouTube", "Thử", 1, 20.0, "16:9")

    data = client.get("/api/shadow/abcdef0000cc/youtube").json()
    assert data["draft"]["title"] == "Bài YouTube | Luyện nói tiếng Anh Shadowing" and data["uploads"] == []
    assert "See you soon." in data["draft"]["description"]
    assert client.get("/api/shadow/nothere0000/youtube").status_code == 404
    thumb = client.post("/api/shadow/abcdef0000cc/thumbnail", json={"theme": "night", "headline": "Tạm biệt"})
    assert thumb.headers["content-type"] == "image/jpeg" and thumb.content[:2] == b"\xff\xd8"
    assert client.post("/api/shadow/abcdef0000cc/thumbnail", json={"theme": "neon"}).status_code == 422

    body = {"title": "Bài YouTube", "description": "Mô tả", "tags": ["a", " "], "privacy": "unlisted"}
    assert client.post("/api/shadow/abcdef0000cc/youtube", json=body).status_code == 400   # chưa kết nối
    assert client.post("/api/youtube/login").status_code == 400                              # chưa có client secret
    bad = client.post("/api/youtube/client-secret", files={"file": ("c.json", b'{"web": {}}')})
    assert bad.status_code == 400
    ok = client.post("/api/youtube/client-secret", files={"file": ("c.json", b'{"installed": {}}')})
    assert ok.json()["client_secret"] is True
    youtube._save_accounts({"active": "acc", "accounts": {"acc": {"label": "me@example.com"}}})

    assert client.post("/api/shadow/abcdef0000cc/youtube", json={**body, "title": "a < b"}).status_code == 400
    soon = (datetime.now() + timedelta(minutes=5)).isoformat()
    assert client.post("/api/shadow/abcdef0000cc/youtube", json={**body, "publish_at": soon}).status_code == 400
    assert client.post("/api/shadow/abcdef0000cc/youtube", json={**body, "account": "zz"}).status_code == 404

    seen = {}

    def fake_upload(lesson, title, description, tags, privacy, publish_at, account_id, on_progress, thumb):
        seen.update(title=title, tags=tags, privacy=privacy, publish_at=publish_at, lesson=lesson["id"], thumb=thumb)
        on_progress(1.0)
        return {"video_id": "VIDabc", "url": "https://youtu.be/VIDabc", "title": title, "privacy": "private",
                "publish_at": youtube.to_utc(publish_at), "account": "me@example.com", "note": None}

    monkeypatch.setattr(youtube, "upload", fake_upload)
    later = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat()   # giờ máy, không múi giờ
    r = client.post("/api/shadow/abcdef0000cc/youtube", json={**body, "publish_at": later})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert seen["tags"] == ["a"] and seen["lesson"] == "abcdef0000cc" and seen["publish_at"].tzinfo is not None
    assert seen["thumb"] == {"theme": "coral", "headline": None, "quote": None}
    assert job["result"]["url"] == "https://youtu.be/VIDabc"
    lesson = next(s for s in client.get("/api/shadow").json() if s["id"] == "abcdef0000cc")
    assert lesson["youtube_url"] == "https://youtu.be/VIDabc"
    assert client.get("/api/shadow/abcdef0000cc/youtube").json()["uploads"][0]["video_id"] == "VIDabc"
