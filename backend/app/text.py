"""Chuẩn bị văn bản trước khi đưa vào mô hình: từ điển phát âm, thẻ nghỉ, chia đoạn."""
import re
from dataclasses import dataclass
from typing import Dict, List, Union

# Thẻ cảm xúc VieNeu v3 Turbo hiểu được; giữ nguyên trong văn bản.
EMOTION_TAGS = ["cười", "thở dài", "hắng giọng"]

PAUSE_RE = re.compile(r"\[\s*nghỉ\s+(\d+(?:[.,]\d+)?)\s*(ms|s)\s*\]", re.IGNORECASE)
MAX_PAUSE_S = 10.0

# Độ dài tối đa một đoạn gửi vào mô hình; mô hình tự chia nhỏ tiếp bên trong.
SEGMENT_CHARS = 400
PARAGRAPH_GAP_S = 0.45


@dataclass
class Pause:
    seconds: float


Segment = Union[str, Pause]


def apply_dictionary(text: str, dictionary: Dict[str, str]) -> str:
    # Từ dài thay trước để "TP.HCM" không bị "TP" ăn mất.
    for word in sorted(dictionary, key=len, reverse=True):
        reading = dictionary[word]
        if not word.strip():
            continue
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", reading, text)
    return text


def _split_long(paragraph: str) -> List[str]:
    if len(paragraph) <= SEGMENT_CHARS:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?…])\s+", paragraph)
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > SEGMENT_CHARS:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def to_segments(text: str, dictionary: Dict[str, str]) -> List[Segment]:
    """Tách văn bản thành các đoạn đọc và khoảng nghỉ, theo đúng thứ tự."""
    text = apply_dictionary(text, dictionary)
    segments: List[Segment] = []
    pos = 0
    for m in PAUSE_RE.finditer(text):
        segments.extend(_text_segments(text[pos:m.start()]))
        value = float(m.group(1).replace(",", "."))
        seconds = value / 1000 if m.group(2).lower() == "ms" else value
        segments.append(Pause(min(seconds, MAX_PAUSE_S)))
        pos = m.end()
    segments.extend(_text_segments(text[pos:]))
    return segments


def _text_segments(chunk: str) -> List[Segment]:
    out: List[Segment] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", chunk) if p.strip()]
    for i, p in enumerate(paragraphs):
        if i:
            out.append(Pause(PARAGRAPH_GAP_S))
        out.extend(_split_long(p))
    return out


def spoken_length(text: str) -> int:
    return len(PAUSE_RE.sub("", text).strip())
