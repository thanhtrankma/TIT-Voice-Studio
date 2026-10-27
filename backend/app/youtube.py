"""Đăng bài luyện Shadowing lên YouTube (YouTube Data API v3).

Làm theo pianotube: OAuth client loại "Desktop app" (client_secret.json), token riêng cho
từng tài khoản, upload resumable có thử lại, `publishAt` để hẹn giờ công khai.

Đăng nhập dùng `run_local_server` ở luồng nền: trình duyệt trên máy mở trang Google, giao
diện hỏi `status()` đến khi có tài khoản. Lúc đăng video không bao giờ mở trình duyệt;
token hỏng thì báo để người dùng kết nối lại.
"""
import hashlib
import json
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from . import shadow
from .config import DATA_DIR

YT_DIR = DATA_DIR / "youtube"
CLIENT_SECRETS = YT_DIR / "client_secret.json"
TOKENS_DIR = YT_DIR / "tokens"
ACCOUNTS_FILE = YT_DIR / "accounts.json"

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
SCOPES = [UPLOAD_SCOPE, "openid", "https://www.googleapis.com/auth/userinfo.email"]
EDUCATION = "27"
LOGIN_TIMEOUT_S = 300
MAX_RETRIES = 8
DESCRIPTION_LIMIT = 4900   # YouTube nhận tối đa 5000 ký tự; chừa chỗ cho ký tự đếm khác nhau


class NeedLogin(RuntimeError):
    """Chưa có tài khoản, hoặc token đã bị thu hồi: phải kết nối lại."""


class UploadLimitExceeded(RuntimeError):
    """Kênh đã hết hạn mức upload trong 24 giờ."""


# ── client secret và tài khoản ─────────────────────────────────────────────


def save_client_secret(raw: bytes) -> None:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("File không phải JSON. Hãy tải đúng file OAuth client từ Google Cloud.")
    if "installed" not in data:
        raise ValueError("Cần OAuth client loại “Desktop app” (file JSON có khoá “installed”).")
    YT_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_SECRETS.write_bytes(raw)


def _load_accounts() -> dict:
    if ACCOUNTS_FILE.exists():
        try:
            return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"active": "", "accounts": {}}


def _save_accounts(data: dict) -> None:
    YT_DIR.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _token_path(account_id: str) -> Path:
    return TOKENS_DIR / (re.sub(r"[^\w-]", "_", account_id) + ".json")


def set_active(account_id: str) -> None:
    data = _load_accounts()
    if account_id not in data["accounts"]:
        raise KeyError(account_id)
    data["active"] = account_id
    _save_accounts(data)


def remove_account(account_id: str) -> None:
    data = _load_accounts()
    if data["accounts"].pop(account_id, None) is None:
        raise KeyError(account_id)
    _token_path(account_id).unlink(missing_ok=True)
    if data["active"] == account_id:
        data["active"] = next(iter(data["accounts"]), "")
    _save_accounts(data)


_login = {"state": "idle", "error": None}   # idle | waiting | error
_login_lock = threading.Lock()


def status() -> dict:
    data = _load_accounts()
    return {
        "client_secret": CLIENT_SECRETS.exists(),
        "accounts": [{"id": k, "label": v["label"]} for k, v in data["accounts"].items()],
        "active": data.get("active", ""),
        "login": dict(_login),
    }


def _identity(creds) -> tuple:
    from googleapiclient.discovery import build

    try:
        info = build("oauth2", "v2", credentials=creds, cache_discovery=False).userinfo().get().execute()
        email = (info.get("email") or "").strip()
        if email:
            return email, "email_" + hashlib.sha256(email.encode()).hexdigest()[:12]
    except Exception:
        pass
    acc = "acc_" + hashlib.sha256(str(creds.refresh_token).encode()).hexdigest()[:12]
    return f"Tài khoản {acc[-6:]}", acc


def _run_login() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=LOGIN_TIMEOUT_S,
                                      prompt="consent", access_type="offline",
                                      success_message="Đã kết nối YouTube. Bạn có thể đóng tab này.")
        if UPLOAD_SCOPE not in set(creds.scopes or []):
            raise PermissionError("Bạn chưa cấp quyền tải video lên YouTube. Kết nối lại và tích đủ quyền.")
        label, acc_id = _identity(creds)
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        _token_path(acc_id).write_text(creds.to_json(), encoding="utf-8")
        data = _load_accounts()
        data["accounts"][acc_id] = {"label": label}
        data["active"] = acc_id
        _save_accounts(data)
        _login.update(state="idle", error=None)
    except Exception as e:
        _login.update(state="error", error=f"Chưa kết nối được: {e}")


def start_login() -> None:
    """Mở trang đăng nhập Google trên máy này; kết quả xem qua `status()`."""
    if not CLIENT_SECRETS.exists():
        raise FileNotFoundError("Chưa có file OAuth client (client_secret.json).")
    with _login_lock:
        if _login["state"] == "waiting":
            return
        _login.update(state="waiting", error=None)
    threading.Thread(target=_run_login, daemon=True, name="youtube-login").start()


def _credentials(account_id: Optional[str]):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    data = _load_accounts()
    account_id = account_id or data.get("active")
    if not account_id or account_id not in data["accounts"]:
        raise NeedLogin("Chưa kết nối tài khoản YouTube nào.")
    path = _token_path(account_id)
    if not path.exists():
        raise NeedLogin("Mất token của tài khoản này, hãy kết nối lại.")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.expired and creds.refresh_token:
        for attempt in range(3):
            try:
                creds.refresh(Request())
                break
            except RefreshError as e:      # bị thu hồi, hoặc app Google còn ở chế độ Testing (token sống 7 ngày)
                raise NeedLogin(f"Phiên đăng nhập YouTube đã hết hạn ({e}). Hãy kết nối lại.") from e
            except Exception:              # mất mạng: thử lại
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise NeedLogin("Phiên đăng nhập YouTube không còn hiệu lực. Hãy kết nối lại.")
    return account_id, data["accounts"][account_id]["label"], creds


# ── nội dung bài đăng ──────────────────────────────────────────────────────


def _clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def _clean(text: str) -> str:
    return text.replace("<", "").replace(">", "")   # YouTube từ chối tiêu đề, mô tả có < >


def chapters(timeline: dict) -> List[str]:
    """Mục lục cho YouTube: mỗi câu một mốc (lấy lượt nghe đầu), cộng lượt liền mạch.

    YouTube chỉ nhận khi mốc đầu là 0:00, có từ 3 mốc và mỗi đoạn dài ít nhất 10 giây;
    không đủ điều kiện thì trả rỗng. Đoạn mở đầu chỉ vài giây nên gộp vào câu 1.
    """
    marks, seen = [], set()
    for st in timeline["steps"]:
        if st["kind"] == "listen" and st["line"] not in seen:
            seen.add(st["line"])
            en = timeline["lines"][st["line"]]["en"]
            marks.append((st["start"], f"Câu {st['line'] + 1}: {en[:60]}"))
        elif st["kind"] == "full" and st["line"] == 0:
            marks.append((st["start"], "Shadowing liền mạch"))
    if marks:
        marks[0] = (0.0, marks[0][1])
    ends = [m[0] for m in marks[1:]] + [timeline["duration"]]
    if len(marks) < 3 or any(end - start < 10 for (start, _), end in zip(marks, ends)):
        return []
    return [f"{_clock(t)} {_clean(label)}" for t, label in marks]


def draft(lesson: dict, timeline: dict) -> dict:
    """Tiêu đề, mô tả, tag gợi ý cho một bài luyện."""
    title = lesson["title"]
    n = lesson["lines"]
    full = timeline["settings"].get("full_run")
    desc = [
        f"Luyện nghe và nói tiếng Anh theo phương pháp Shadowing: {n} câu, giọng {lesson['voice']}.",
        "Cách luyện: nghe câu mẫu, khi thấy “Đến lượt bạn” thì nói to theo; sau đó nghe bản chậm và nói lại."
        + (" Cuối bài nói cùng lúc với giọng đọc." if full else ""),
    ]
    marks = chapters(timeline)
    toc = ["", "Mục lục:", *marks] if marks else []
    script = ["", "Lời thoại:"]
    for i, line in enumerate(timeline["lines"], 1):
        script.append(f"{i}. {line['en']}" + (f"\n   {line['vi']}" if line.get("vi") else ""))
    footer = ["", "Giọng đọc được tạo bằng AI (TIT Voice Studio).",
              "#shadowing #luyennoitienganh #hoctienganh"]

    def size(*parts):
        return len("\n".join(sum(parts, [])))

    # Mô tả tối đa 5000 ký tự: bớt lời thoại từ cuối trước; mục lục mà vẫn quá dài thì bỏ hẳn,
    # vì YouTube chỉ nhận mục lục liền mạch từ 0:00.
    if size(desc, toc, footer) > DESCRIPTION_LIMIT:
        toc = []
    while len(script) > 2 and size(desc, toc, script, footer) > DESCRIPTION_LIMIT:
        script.pop()
    return {
        "title": _clean(f"{title.strip()} | Luyện nói tiếng Anh Shadowing")[:100].strip(),
        "description": _clean("\n".join(desc + toc + (script if len(script) > 2 else []) + footer)),
        "tags": ["shadowing", "English shadowing", "luyện nói tiếng Anh", "luyện nghe tiếng Anh",
                 "học tiếng Anh", "English speaking practice", _clean(title)[:60]],
    }


def thumbnail(lesson: dict, out: Path) -> Path:
    """Ảnh bìa 1280×720 vẽ cùng kiểu trang mở đầu của video."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        canvas = shadow.Canvas("16:9", Path(tmp))
        png = canvas.title_card(lesson["title"], f"Shadowing · {lesson['lines']} câu · Giọng {lesson['voice']}",
                                "Luyện nghe và nói tiếng Anh", 1.0)
        Image.open(png).convert("RGB").resize((1280, 720), Image.LANCZOS).save(out, "JPEG", quality=90)
    return out


def to_utc(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── đăng ───────────────────────────────────────────────────────────────────


def upload(lesson: dict, title: str, description: str, tags: List[str], privacy: str,
           publish_at: Optional[datetime], account_id: Optional[str],
           on_progress: Callable[[float], None], service=None) -> dict:
    """Tải video lên kênh. Có `publish_at` thì để riêng tư và YouTube tự công khai đúng giờ.

    `service` chỉ dùng trong kiểm thử, thay cho client thật của googleapiclient.
    """
    import httplib2
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    folder = shadow.lesson_dir(lesson["id"])
    video = folder / "lesson.mp4"
    if not video.exists():
        raise FileNotFoundError("Không tìm thấy video của bài luyện.")

    if service is None:
        from googleapiclient.discovery import build

        account_id, label, creds = _credentials(account_id)
        service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    else:
        label = account_id or ""

    while len(",".join(tags)) > 480:    # YouTube giới hạn tổng độ dài tag khoảng 500 ký tự
        tags = tags[:-1]
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": True}   # giọng đọc do AI tạo
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = to_utc(publish_at)
    body = {"snippet": {"title": title, "description": description, "tags": tags, "categoryId": EDUCATION,
                        "defaultLanguage": "vi", "defaultAudioLanguage": "en"},
            "status": status}

    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = service.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, retries = None, MAX_RETRIES
    while resp is None:
        try:
            st, resp = req.next_chunk()
            retries = MAX_RETRIES          # tải thêm được một đoạn thì đặt lại số lần thử
            if st:
                on_progress(st.progress() * 0.95)
        except HttpError as e:
            content = e.content or b""
            if b"uploadLimitExceeded" in content:
                raise UploadLimitExceeded(
                    "YouTube báo kênh đã hết hạn mức tải lên trong 24 giờ. Đợi một ngày, hoặc xác minh "
                    "số điện thoại kênh tại youtube.com/verify để tăng hạn mức.") from e
            if b"quotaExceeded" in content:
                raise RuntimeError("Project Google Cloud đã hết quota YouTube API hôm nay (mỗi lần đăng tốn "
                                   "khoảng 1.600 đơn vị trên 10.000). Thử lại vào ngày mai.") from e
            if e.resp.status in (500, 502, 503, 504) and retries:
                retries -= 1
                time.sleep(5 * (MAX_RETRIES - retries))
                continue
            raise
        except (OSError, httplib2.HttpLib2Error):   # mất mạng, máy ngủ dậy chưa có DNS…
            if not retries:
                raise
            retries -= 1
            time.sleep(5 * (MAX_RETRIES - retries))
    vid = resp["id"]

    note = None
    if lesson["aspect"] == "16:9":     # Shorts không đặt ảnh bìa qua API được
        try:
            thumb = thumbnail(lesson, folder / "thumbnail.jpg")
            service.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
        except HttpError as e:
            note = (f"Chưa đặt được ảnh bìa ({e.resp.status}): kênh cần xác minh số điện thoại "
                    "để dùng ảnh bìa tuỳ chỉnh.")
    on_progress(1.0)
    return {"video_id": vid, "url": f"https://youtu.be/{vid}", "title": title,
            "privacy": status["privacyStatus"], "publish_at": status.get("publishAt"),
            "account": label, "note": note}
