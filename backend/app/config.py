import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TIT_DATA_DIR", ROOT / "data"))
MODELS_DIR = Path(os.environ.get("TIT_MODELS_DIR", DATA_DIR / "models"))
HISTORY_DIR = DATA_DIR / "history"
VOICES_FILE = DATA_DIR / "custom-voices.json"
DB_FILE = DATA_DIR / "studio.db"

# "fp32" cho chất lượng tốt nhất, "int8" nhanh hơn ~3 lần mỗi frame.
PRECISION = os.environ.get("TIT_PRECISION", "fp32")

for d in (MODELS_DIR, HISTORY_DIR):
    d.mkdir(parents=True, exist_ok=True)
