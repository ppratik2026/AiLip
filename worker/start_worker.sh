#!/usr/bin/env bash
# AiLip — GPU Worker Startup (GPU Server / RunPod / Vast.ai)
#
# Usage:
#   export WORKER_API_KEY="your-secret-key"
#   bash start_worker.sh
#
# Optional env vars:
#   PORT=8000            (default: 8000)
#   WORKER_API_KEY=...   (if blank, API is open — only safe on private networks)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

PORT="${PORT:-8000}"

echo ""
echo "  AiLip GPU Worker"
echo "  Port : $PORT"
echo "  Key  : ${WORKER_API_KEY:+SET ✓}${WORKER_API_KEY:-NOT SET (open access)}"
echo ""

# Activate conda env if available
if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
  # shellcheck disable=SC1091
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  conda activate ailip 2>/dev/null || true
fi

export PYTHONPATH="$ROOT_DIR:$ROOT_DIR/vendor/LatentSync:${PYTHONPATH:-}"

cd "$SCRIPT_DIR"
exec python worker_api.py --port "$PORT"
