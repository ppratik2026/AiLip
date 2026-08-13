#!/usr/bin/env bash
# AiLip — Full GPU Setup Script
# Installs: LatentSync + VideoReTalking + CodeFormer + Real-ESRGAN + Webapp
#
# Usage:
#   bash setup.sh                    # Full install (CUDA 11.8)
#   bash setup.sh --cpu              # CPU-only (testing, no CUDA)
#   bash setup.sh --webapp-only      # Webapp deps only (skip model downloads)
#   bash setup.sh --skip-latentsync  # Skip LatentSync (use VideoReTalking only)
#
# Requirements: conda or mamba, git, curl
# GPU:  NVIDIA 4+ GB VRAM (8+ GB recommended for LatentSync)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$SCRIPT_DIR/vendor"
ENV_NAME="ailip"

# ── Parse flags ───────────────────────────────────────────────────────────────
CPU_ONLY=false
WEBAPP_ONLY=false
SKIP_LATENTSYNC=false
SKIP_VRT=false
SKIP_CF=false
SKIP_ESRGAN=false

for arg in "$@"; do
  case "$arg" in
    --cpu)               CPU_ONLY=true ;;
    --webapp-only)       WEBAPP_ONLY=true ;;
    --skip-latentsync)   SKIP_LATENTSYNC=true ;;
    --skip-vrt)          SKIP_VRT=true ;;
    --skip-cf)           SKIP_CF=true ;;
    --skip-esrgan)       SKIP_ESRGAN=true ;;
    --help|-h)
      echo "Usage: bash setup.sh [OPTIONS]"
      echo "  --cpu               CPU-only PyTorch (no CUDA)"
      echo "  --webapp-only       Install webapp deps, skip model downloads"
      echo "  --skip-latentsync   Skip LatentSync (VideoReTalking will be used)"
      echo "  --skip-vrt          Skip VideoReTalking"
      echo "  --skip-cf           Skip CodeFormer"
      echo "  --skip-esrgan       Skip Real-ESRGAN"
      exit 0
      ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()    { echo -e "\n${BOLD}${BLUE}▶ $*${NC}"; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        AiLip — GPU Setup                             ║${NC}"
echo -e "${BOLD}║  LatentSync + VideoReTalking + CodeFormer + ESRGAN   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ── System prerequisites ──────────────────────────────────────────────────────
step "System prerequisites"

command -v git  >/dev/null 2>&1 || error "git not found. Run: sudo apt install git"
command -v curl >/dev/null 2>&1 || error "curl not found. Run: sudo apt install curl"
info "git  ✓"

# ffmpeg: try to install if missing
if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg not found — attempting install..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y ffmpeg 2>/dev/null || error "ffmpeg install failed. Run: sudo apt install ffmpeg"
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y ffmpeg 2>/dev/null || error "ffmpeg install failed"
  else
    error "ffmpeg required. Install it manually then re-run setup.sh"
  fi
fi
info "ffmpeg ✓  ($(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3))"

# Build tools for some Python packages
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get install -y build-essential cmake python3-dev 2>/dev/null || true
fi

# ── Conda / Mamba ─────────────────────────────────────────────────────────────
step "Conda environment: $ENV_NAME"

CONDA_CMD=""
if command -v mamba >/dev/null 2>&1; then CONDA_CMD="mamba"
elif command -v conda >/dev/null 2>&1; then CONDA_CMD="conda"
else
  error "conda or mamba required.\nInstall Miniconda: https://docs.conda.io/en/latest/miniconda.html"
fi
info "Using: $CONDA_CMD"

CONDA_BASE=$($CONDA_CMD info --base 2>/dev/null || echo "")

# Find conda.sh — path varies by OS/image (Vast.ai, RunPod, local conda, miniforge, etc.)
_find_conda_sh() {
  local candidates=(
    "$CONDA_BASE/etc/profile.d/conda.sh"
    "/opt/conda/etc/profile.d/conda.sh"
    "/opt/miniforge3/etc/profile.d/conda.sh"
    "/opt/mamba/etc/profile.d/conda.sh"
    "$HOME/miniconda3/etc/profile.d/conda.sh"
    "$HOME/miniforge3/etc/profile.d/conda.sh"
    "$HOME/anaconda3/etc/profile.d/conda.sh"
  )
  for p in "${candidates[@]}"; do
    [[ -f "$p" ]] && echo "$p" && return 0
  done
  # Last resort: find it
  find /opt /root /home /usr -maxdepth 6 -name "conda.sh" -path "*/profile.d/*" 2>/dev/null | head -1
}

CONDA_SH=$(_find_conda_sh)
if [[ -z "$CONDA_SH" ]]; then
  # conda may already be initialised in this shell (Vast.ai/RunPod base images)
  warn "conda.sh not found — assuming conda is already active in this shell."
else
  # shellcheck disable=SC1090
  source "$CONDA_SH"
fi

if conda env list | grep -qE "^${ENV_NAME}\s"; then
  warn "Conda env '${ENV_NAME}' already exists — reusing."
else
  info "Creating conda env (Python 3.10)..."
  $CONDA_CMD create -y -n "$ENV_NAME" python=3.10
fi
conda activate "$ENV_NAME"
info "Activated: $ENV_NAME ($(python --version))"

# ── PyTorch ───────────────────────────────────────────────────────────────────
step "PyTorch"

if $CPU_ONLY; then
  info "Installing PyTorch CPU-only..."
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu -q
else
  info "Installing PyTorch + CUDA 11.8..."
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -q
fi

python -c "
import torch
print(f'  PyTorch {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU: {torch.cuda.get_device_name(0)}')
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f'  VRAM: {vram:.1f} GB  →  auto model: {\"LatentSync\" if vram >= 8 else \"VideoReTalking\"}')
"

# ── Core Python packages ──────────────────────────────────────────────────────
step "Core Python packages"

pip install -q \
  numpy \
  scipy \
  "opencv-python>=4.8" \
  "pillow>=10.0" \
  "imageio>=2.31" \
  "imageio-ffmpeg>=0.4.9" \
  "tqdm>=4.65" \
  einops \
  "omegaconf>=2.3" \
  pyyaml \
  "huggingface_hub>=0.20" \
  "accelerate>=0.26" \
  "diffusers>=0.25" \
  "transformers>=4.37" \
  "basicsr>=1.4.2" \
  "facexlib>=0.3.0" \
  "gfpgan>=1.3.8" \
  "realesrgan>=0.3.0" \
  "openai-whisper>=20231117" \
  "flask>=3.0" \
  gunicorn \
  gtts \
  pyttsx3

info "Core packages installed ✓"

mkdir -p "$VENDOR_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

if $WEBAPP_ONLY; then
  info "Webapp-only mode: skipping model downloads."
else

# ── LatentSync ────────────────────────────────────────────────────────────────
if ! $SKIP_LATENTSYNC; then
  step "LatentSync (ByteDance)"
  LSYNC_DIR="$VENDOR_DIR/LatentSync"

  if [[ -d "$LSYNC_DIR/.git" ]]; then
    warn "Already cloned — pulling latest..."
    git -C "$LSYNC_DIR" pull --ff-only 2>/dev/null || warn "Pull failed (network?) — using existing"
  else
    info "Cloning LatentSync..."
    git clone https://github.com/bytedance/LatentSync.git "$LSYNC_DIR"
  fi

  if [[ -f "$LSYNC_DIR/requirements.txt" ]]; then
    info "Installing LatentSync requirements..."
    pip install -r "$LSYNC_DIR/requirements.txt" -q 2>/dev/null || warn "Some LatentSync deps failed"
  fi

  LSYNC_CKPT="$LSYNC_DIR/checkpoints/latentsync_unet.pt"
  if [[ -f "$LSYNC_CKPT" ]]; then
    warn "LatentSync checkpoint already present."
  else
    info "Downloading LatentSync checkpoints from HuggingFace (~2 GB)..."
    python - << PYEOF
from huggingface_hub import snapshot_download
import os
snapshot_download(
    repo_id="ByteDance/LatentSync",
    local_dir="$LSYNC_DIR/checkpoints",
    ignore_patterns=["*.md", "*.txt", ".gitattributes"],
)
print("  LatentSync checkpoints downloaded.")
PYEOF
  fi

  # Copy whisper tiny model into LatentSync checkpoints if needed
  python - << 'PYEOF'
import os, shutil, pathlib, subprocess, sys
ckpt_dir = os.environ.get("LSYNC_CKPT_DIR", "")
tiny_dst  = pathlib.Path(ckpt_dir) / "whisper" / "tiny.pt" if ckpt_dir else None

if tiny_dst and not tiny_dst.exists():
    # Try to find it in whisper's cache
    cache = pathlib.Path.home() / ".cache" / "whisper" / "tiny.pt"
    if not cache.exists():
        try:
            import whisper
            whisper.load_model("tiny")   # downloads to cache
        except Exception as e:
            print(f"  whisper download: {e}")
    if cache.exists():
        tiny_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cache, tiny_dst)
        print(f"  Copied whisper/tiny.pt → {tiny_dst}")
    else:
        print("  whisper/tiny.pt will be downloaded on first run.")
else:
    print("  whisper/tiny.pt already present.")
PYEOF

  info "LatentSync ready ✓  ($LSYNC_DIR)"
fi  # SKIP_LATENTSYNC

# ── VideoReTalking ────────────────────────────────────────────────────────────
if ! $SKIP_VRT; then
  step "VideoReTalking (OpenTalker)"
  VRT_DIR="$VENDOR_DIR/video-retalking"

  if [[ -d "$VRT_DIR/.git" ]]; then
    warn "Already cloned — skipping."
  else
    info "Cloning VideoReTalking..."
    git clone https://github.com/OpenTalker/video-retalking.git "$VRT_DIR"
  fi

  if [[ -f "$VRT_DIR/requirements.txt" ]]; then
    info "Installing VideoReTalking requirements..."
    pip install -r "$VRT_DIR/requirements.txt" -q 2>/dev/null || warn "Some VRT deps failed"
  fi

  VRT_CKPT_DIR="$VRT_DIR/checkpoints"
  mkdir -p "$VRT_CKPT_DIR"

  if [[ -f "$VRT_CKPT_DIR/30_net_gen.pth" ]]; then
    warn "VideoReTalking checkpoints already present."
  else
    info "Downloading VideoReTalking checkpoints from HuggingFace..."
    python - << 'PYEOF' || {
      warn "VideoReTalking checkpoint download failed (repo may be private/moved). VRT will be unavailable; LatentSync will be used."
      SKIP_VRT=true
    }
import sys
from huggingface_hub import snapshot_download
try:
    snapshot_download(
        repo_id="vinthony/video-retalking",
        local_dir="$VRT_CKPT_DIR",
        ignore_patterns=["*.md"],
    )
    print("  VideoReTalking checkpoints downloaded.")
except Exception as e:
    print(f"  Download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
  fi
  if ! $SKIP_VRT; then
    info "VideoReTalking ready ✓"
  fi
fi  # SKIP_VRT

# ── CodeFormer ────────────────────────────────────────────────────────────────
if ! $SKIP_CF; then
  step "CodeFormer (sczhou)"
  CF_DIR="$VENDOR_DIR/CodeFormer"

  if [[ -d "$CF_DIR/.git" ]]; then
    warn "Already cloned — skipping."
  else
    info "Cloning CodeFormer..."
    git clone https://github.com/sczhou/CodeFormer.git "$CF_DIR"
  fi

  if [[ -f "$CF_DIR/requirements.txt" ]]; then
    info "Installing CodeFormer requirements..."
    pip install -r "$CF_DIR/requirements.txt" -q 2>/dev/null || true
  fi

  # Install CodeFormer as editable package for proper imports
  (cd "$CF_DIR" && pip install -e . -q 2>/dev/null) || true

  mkdir -p "$CF_DIR/weights/CodeFormer"
  CF_CKPT="$CF_DIR/weights/CodeFormer/codeformer.pth"
  if [[ -f "$CF_CKPT" ]]; then
    warn "CodeFormer weights already present."
  else
    info "Downloading CodeFormer weights (~370 MB)..."
    curl -L --progress-bar \
      "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth" \
      -o "$CF_CKPT"
  fi

  # Download facelib detection models used by CodeFormer
  info "Downloading facelib detection models..."
  python - << PYEOF
import os, sys
sys.path.insert(0, "$CF_DIR")
try:
    from basicsr.utils.download_util import load_file_from_url
    weights_dir = "$CF_DIR/weights/facelib"
    os.makedirs(weights_dir, exist_ok=True)
    models = {
        "detection_Retinaface_resnet50.pth":
          "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/detection_Retinaface_resnet50.pth",
        "parsing_parsenet.pth":
          "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/parsing_parsenet.pth",
    }
    for fname, url in models.items():
        fpath = os.path.join(weights_dir, fname)
        if not os.path.exists(fpath):
            load_file_from_url(url=url, model_dir=weights_dir, progress=True)
            print(f"  Downloaded: {fname}")
        else:
            print(f"  Already exists: {fname}")
except Exception as e:
    print(f"  Warning: facelib download failed ({e}) — will retry on first run")
PYEOF

  info "CodeFormer ready ✓  ($CF_DIR)"
fi  # SKIP_CF

# ── Real-ESRGAN ───────────────────────────────────────────────────────────────
if ! $SKIP_ESRGAN; then
  step "Real-ESRGAN (xinntao)"
  RESRGAN_DIR="$VENDOR_DIR/Real-ESRGAN"

  if [[ -d "$RESRGAN_DIR/.git" ]]; then
    warn "Already cloned — skipping."
  else
    info "Cloning Real-ESRGAN..."
    git clone https://github.com/xinntao/Real-ESRGAN.git "$RESRGAN_DIR"
  fi

  if [[ -f "$RESRGAN_DIR/requirements.txt" ]]; then
    pip install -r "$RESRGAN_DIR/requirements.txt" -q 2>/dev/null || true
  fi
  (cd "$RESRGAN_DIR" && pip install -e . -q 2>/dev/null) || pip install realesrgan -q || warn "Real-ESRGAN pip install failed"

  mkdir -p "$RESRGAN_DIR/weights"
  ESRGAN_CKPT="$RESRGAN_DIR/weights/RealESRGAN_x4plus.pth"
  if [[ -f "$ESRGAN_CKPT" ]]; then
    warn "RealESRGAN_x4plus.pth already present."
  else
    info "Downloading RealESRGAN_x4plus weights (~67 MB)..."
    curl -L --progress-bar \
      "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
      -o "$ESRGAN_CKPT"
  fi
  info "Real-ESRGAN ready ✓  ($RESRGAN_DIR)"
fi  # SKIP_ESRGAN

fi  # WEBAPP_ONLY

# ── Generate start_webapp.sh ──────────────────────────────────────────────────
step "Generating start_webapp.sh"

cat > "$SCRIPT_DIR/start_webapp.sh" << 'STARTEOF'
#!/usr/bin/env bash
# AiLip — Start Webapp (GPU Production Mode)
# Auto-generated by setup.sh — safe to re-run setup.sh to regenerate.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${PORT:-5000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"      # keep 1 — GPU is shared, threading handles concurrency

# Activate conda env
CONDA_BASE="$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")"
_CONDA_SH=""
for _p in "$CONDA_BASE/etc/profile.d/conda.sh" /opt/conda/etc/profile.d/conda.sh /opt/miniforge3/etc/profile.d/conda.sh "$HOME/miniconda3/etc/profile.d/conda.sh"; do
  [[ -f "$_p" ]] && _CONDA_SH="$_p" && break
done
[[ -n "$_CONDA_SH" ]] && source "$_CONDA_SH" || true
conda activate ailip

# Make vendor modules importable
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/vendor/LatentSync:${PYTHONPATH:-}"

echo ""
echo "  AiLip GPU Webapp"
echo "  Host    : $HOST:$PORT"
echo "  Workers : $WORKERS"
echo "  Open    : http://localhost:$PORT"
echo ""

cd "$SCRIPT_DIR/webapp"
exec gunicorn \
  -w "$WORKERS" \
  -b "$HOST:$PORT" \
  --timeout 3600 \
  --keep-alive 5 \
  --log-level info \
  --access-logfile - \
  --error-logfile - \
  app:app
STARTEOF

chmod +x "$SCRIPT_DIR/start_webapp.sh"
info "Created: start_webapp.sh ✓"

# ── Verification ──────────────────────────────────────────────────────────────
step "Verifying installation"

python - << 'PYEOF'
import importlib, sys

checks = [
    ("torch",       "PyTorch"),
    ("cv2",         "OpenCV"),
    ("PIL",         "Pillow"),
    ("basicsr",     "BasicSR"),
    ("realesrgan",  "Real-ESRGAN"),
    ("flask",       "Flask"),
    ("gtts",        "gTTS"),
    ("whisper",     "Whisper"),
]

ok = True
for mod, name in checks:
    try:
        importlib.import_module(mod)
        print(f"  ✓  {name}")
    except ImportError:
        print(f"  ✗  {name}  ← MISSING")
        ok = False

try:
    import torch
    print(f"\n  PyTorch  : {torch.__version__}")
    print(f"  CUDA     : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        vram = p.total_memory / 1024**3
        print(f"  GPU      : {p.name}")
        print(f"  VRAM     : {vram:.1f} GB")
        model = "LatentSync" if vram >= 8 else "VideoReTalking"
        print(f"  Auto model → {model}")
except Exception as e:
    print(f"  GPU check error: {e}")

sys.exit(0 if ok else 1)
PYEOF

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN} Setup complete!${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Start the webapp:"
echo "    bash start_webapp.sh"
echo "    # open http://localhost:5000"
echo ""
echo "  Or CLI pipeline:"
echo "    conda activate ailip"
echo "    python pipeline.py --source face.jpg --audio speech.wav --output out.mp4"
echo ""
echo "  For demo mode (no GPU):"
echo "    cd webapp && python run_demo.py"
echo ""
