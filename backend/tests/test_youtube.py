"""Kiểm thử đăng YouTube không cần mạng: client YouTube giả, dữ liệu ở thư mục tạm."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import httplib2
import numpy as np
import pytest
from googleapiclient.errors import HttpError
from PIL import Image

os.environ.setdefault("TIT_DATA_DIR", tempfile.mkdtemp(prefix="tit-qa-"))

from app import shadow, store, youtube  # noqa: E402
from app.shadow import Line, Settings  # noqa: E402

DESKTOP = json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s"}}).encode()


@pytest.fixture
def yt_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "YT_DIR", tmp_path)
    monkeypatch.setattr(youtube, "CLIENT_SECRETS", tmp_path / "client_secret.json")
    monkeypatch.setattr(youtube, "TOKENS_DIR", tmp_path / "tokens")
    monkeypatch.setattr(youtube, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    return tmp_path


def test_client_secret_must_be_desktop_app(yt_dir):
    with pytest.raises(ValueError, match="JSON"):
        youtube.save_client_secret(b"not json")
    with pytest.raises(ValueError, match="Desktop app"):
        youtube.save_client_secret(json.dumps({"web": {}}).encode())
    youtube.save_client_secret(DESKTOP)
    assert youtube.status()["client_secret"] and youtube.status()["accounts"] == []


def test_accounts_switch_and_remove(yt_dir):
    youtube._save_accounts({"active": "a", "accounts": {"a": {"label": "a@x.com"}, "b": {"label": "b@x.com"}}})
    (yt_dir / "tokens").mkdir()
    youtube._token_path("a").write_text("{}")
    youtube.set_active("b")
    assert youtube.status()["active"] == "b"
    with pytest.raises(KeyError):
        youtube.set_active("zz")
    youtube.remove_account("b")
    assert youtube.status()["active"] == "a" and [a["id"] for a in youtube.status()["accounts"]] == ["a"]
    youtube.remove_account("a")
    assert youtube.status()["active"] == "" and not youtube._token_path("a").exists()


def test_upload_without_account_asks_to_connect(yt_dir):
    with pytest.raises(youtube.NeedLogin):
        youtube._credentials(None)


def _timeline(n_lines, listen_gap):
    steps, t = [{"kind": "intro", "line": -1, "start": 0.0, "duration": 3.0}], 3.0
    for i in range(n_lines):
        steps.append({"kind": "listen", "line": i, "start": t, "duration": 2.0})
        t += listen_gap
    steps.append({"kind": "full", "line": 0, "start": t, "duration": 2.0})
    lines = [{"en": f"Sentence <{i}> number {i}.", "vi": f"Câu {i}"} for i in range(n_lines)]
    return {"duration": t + 20, "lines": lines, "steps": steps, "settings": {"full_run": True}}


def test_chapters_follow_youtube_rules():
    marks = youtube.chapters(_timeline(3, 12.0))
    assert marks[0] == "0:00 Câu 1: Sentence 0 number 0." and marks[1].startswith("0:15 Câu 2")
    assert marks[-1] == "0:39 Shadowing liền mạch" and all("<" not in m for m in marks)
    assert youtube.chapters(_timeline(3, 6.0)) == []      # đoạn dưới 10 giây → YouTube không nhận
    assert youtube.chapters(_timeline(1, 2.0)) == []


def test_draft_is_within_youtube_limits():
    lesson = {"id": "abcdef000001", "title": "Giao tiếp " * 20, "lines": 200, "voice": "Heart (Mỹ)", "aspect": "16:9"}
    tl = _timeline(200, 12.0)
    tl["lines"] = [{"en": "A fairly long English sentence for practice. " * 3, "vi": "Một câu dịch khá dài."}] * 200
    d = youtube.draft(lesson, tl)
    assert len(d["title"]) <= 100 and len(d["description"]) <= 5000
    assert "Giọng đọc được tạo bằng AI" in d["description"] and "<" not in d["description"]
    short = youtube.draft({**lesson, "title": "Du lịch", "lines": 3}, _timeline(3, 12.0))
    assert short["title"] == "Du lịch | Luyện nói tiếng Anh Shadowing"
    assert "1. Sentence 0 number 0.\n   Câu 0" in short["description"] and "Mục lục:" in short["description"]


class FakeRequest:
    def __init__(self, failures):
        self.failures, self.calls = list(failures), 0

    def next_chunk(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        if self.calls < 4:
            return type("S", (), {"progress": lambda s, c=self.calls: c / 4})(), None
        return None, {"id": "VID123"}


class FakeService:
    def __init__(self, failures=(), thumb_error=None):
        self.request, self.thumb_error = FakeRequest(failures), thumb_error
        self.body, self.thumb = None, None

    def videos(self):
        svc = self

        class V:
            def insert(self, part, body, media_body):
                svc.body = body
                return svc.request
        return V()

    def thumbnails(self):
        svc = self

        class T:
            def set(self, videoId, media_body):
                svc.thumb = media_body._filename

                class E:
                    def execute(self):
                        if svc.thumb_error:
                            raise svc.thumb_error
                return E()
        return T()


def _http_error(status, reason=b""):
    return HttpError(httplib2.Response({"status": status}), reason)


@pytest.fixture
def lesson(monkeypatch):
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)
    lesson_id = "abcdef0000aa"
    tone = (0.3 * np.sin(np.linspace(0, 2 * np.pi * 220 * 1.5, int(shadow.SR * 1.5)))).astype(np.float32)
    shadow.build(lesson_id, [Line("Hello there.")], [tone], Settings(voice="Thử", slow_speed=1.0, full_run=False),
                 lambda p: None)
    return {"id": lesson_id, "title": "Bài thử", "lines": 1, "voice": "Thử", "aspect": "16:9"}


def test_upload_retries_and_sets_thumbnail(lesson):
    svc = FakeService(failures=[_http_error(503), OSError("mất mạng")])
    progress = []
    when = datetime.now(timezone.utc) + timedelta(days=1)
    rec = youtube.upload(lesson, "Tiêu đề", "Mô tả", ["a" * 100] * 6, "public", when, "me@x.com",
                         progress.append, service=svc)
    assert rec["url"] == "https://youtu.be/VID123" and rec["privacy"] == "private" and rec["note"] is None
    status = svc.body["status"]
    assert status["publishAt"] == youtube.to_utc(when) and status["containsSyntheticMedia"] is True
    assert len(",".join(svc.body["snippet"]["tags"])) <= 480 and svc.body["snippet"]["categoryId"] == "27"
    assert progress == sorted(progress) and progress[-1] == 1.0
    with Image.open(svc.thumb) as img:
        assert img.size == (1280, 720)


def test_upload_reports_limits_and_thumbnail_problems(lesson):
    with pytest.raises(youtube.UploadLimitExceeded):
        youtube.upload(lesson, "T", "", [], "private", None, None, lambda p: None,
                       service=FakeService(failures=[_http_error(400, b'{"reason": "uploadLimitExceeded"}')]))
    with pytest.raises(HttpError):
        youtube.upload(lesson, "T", "", [], "private", None, None, lambda p: None,
                       service=FakeService(failures=[_http_error(503)] * (youtube.MAX_RETRIES + 1)))
    rec = youtube.upload(lesson, "T", "", [], "unlisted", None, None, lambda p: None,
                         service=FakeService(thumb_error=_http_error(403)))
    assert rec["privacy"] == "unlisted" and "xác minh" in rec["note"]


def test_store_links_latest_upload_to_lesson():
    store.init()
    store.add_shadow("abcdef0000bb", "Bài", "Heart (Mỹ)", 2, 30.0, "16:9")
    store.add_youtube("abcdef0000bb", "V1", "https://youtu.be/V1", "Bài", "private", None, "me@x.com")
    store.add_youtube("abcdef0000bb", "V2", "https://youtu.be/V2", "Bài", "public", None, "me@x.com")
    assert store.get_shadow("abcdef0000bb")["youtube_url"] == "https://youtu.be/V2"
    assert [u["video_id"] for u in store.list_youtube("abcdef0000bb")] == ["V2", "V1"]
