"""Tải file mô hình ONNX về thư mục riêng thay vì cache Hugging Face.

onnxruntime >= 1.31 từ chối file `.data` đi kèm `.onnx` khi chúng là symlink trỏ sang
các blob khác nhau trong cache HF ("External data path escapes model directory").
Tải bằng `local_dir` cho ra file thật nằm cạnh nhau nên vượt qua kiểm tra đó.
"""
from pathlib import Path
from typing import List, Optional

from huggingface_hub import hf_hub_download

from .config import MODELS_DIR


def fetch_local(repo: str, files: List[str], subfolder: Optional[str]) -> Path:
    local_dir = MODELS_DIR / repo.replace("/", "__")
    last = None
    for fn in files:
        try:
            last = hf_hub_download(repo, fn, subfolder=subfolder or None, local_dir=local_dir)
        except Exception:
            if fn.endswith(".json"):
                continue
            raise
    return Path(last).parent


def install() -> None:
    from vieneu._v3_turbo_engine.onnx_runtime_lite import OnnxV3LiteEngine

    OnnxV3LiteEngine._fetch = staticmethod(fetch_local)
