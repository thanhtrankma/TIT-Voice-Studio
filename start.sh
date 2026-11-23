#!/usr/bin/env bash
# Chạy TIT Voice Studio bằng một lệnh: ./start.sh
#   - cài thư viện nếu còn thiếu, build lại giao diện khi code giao diện đổi,
#   - chạy backend (phục vụ luôn giao diện) ở http://localhost:8765 rồi tự mở trình duyệt.
# ./start.sh --dev  chạy thêm Vite (http://localhost:5173) để sửa giao diện có tải lại nóng.
# Ctrl+C để tắt. Đổi cổng: PORT=9000 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
DEV=0
[[ "${1:-}" == "--dev" ]] && DEV=1

need() { command -v "$1" >/dev/null || { echo "Thiếu $1 — cài bằng: $2" >&2; exit 1; }; }
need uv "brew install uv"
need npm "brew install node"
need ffmpeg "brew install ffmpeg"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Cổng $PORT đang có chương trình khác chạy (có thể là chính TIT Voice Studio)." >&2
  echo "Tắt nó đi, hoặc chọn cổng khác: PORT=9000 ./start.sh" >&2
  exit 1
fi

# thư viện giao diện: cài khi chưa có hoặc package-lock.json mới hơn lần cài trước
if [[ ! -f frontend/node_modules/.package-lock.json || frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]]; then
  echo "▸ Cài thư viện giao diện…"
  npm --prefix frontend install --no-audit --no-fund
fi
echo "▸ Chuẩn bị backend…"
uv sync --directory backend --quiet

wait_and_open() {   # đợi server trả lời rồi mở trình duyệt
  for _ in $(seq 1 120); do
    if curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      echo "▸ TIT Voice Studio đang chạy: $1  (Ctrl+C để tắt)"
      open "$1" 2>/dev/null || true
      return
    fi
    sleep 0.5
  done
  echo "Backend chưa trả lời sau 60 giây, xem log ở trên." >&2
}

if [[ $DEV == 1 ]]; then
  uv run --directory backend uvicorn app.main:app --port "$PORT" --reload &
  BACKEND=$!
  trap 'kill $BACKEND 2>/dev/null' EXIT
  wait_and_open "http://localhost:5173" &
  npm --prefix frontend run dev -- --port 5173 --strictPort
else
  # build lại giao diện nếu chưa có bản build hoặc có file giao diện mới hơn bản build
  dist=frontend/dist/index.html
  if [[ ! -f $dist ]] || [[ -n "$(find frontend/src frontend/public frontend/index.html frontend/vite.config.ts \
      frontend/package.json frontend/package-lock.json -newer "$dist" -print -quit)" ]]; then
    echo "▸ Build giao diện…"
    npm --prefix frontend run build
  fi
  wait_and_open "http://localhost:$PORT" &
  exec uv run --directory backend uvicorn app.main:app --port "$PORT"
fi
