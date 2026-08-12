#!/usr/bin/env bash
# AiLip — Environment Setup Script
# Installs all dependencies: LatentSync, VideoReTalking, CodeFormer, Real-ESRGAN
#
# Usage: bash setup.sh [--cpu]  (--cpu skips CUDA packages, for testing only)
#
# Requirements: conda (or mamba), git, curl, ffmpeg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$SCRIPT_DIR/vendor"

CPU_ONLY=false
for arg in "$@"; do
  [[ "$arg" == "--cpu" ]] && CPU_ONLY=true
done

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Prerequisites check ───────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v git  >/dev/null 2>&1 || error "git is not installed."
command -v curl >/dev/null 2>&1 || error "curl is not installed."
command -v ffmpeg >/dev/null 2>&1 || error "ffmpeg is not installed. Install via: sudo apt install ffmpeg"

CONDA_CMD=""
if command -v mamba >/dev/null 2>&1; then
  CONDA_CMD="mamba"
elif command -v conda >/dev/null 2>&1; then
  CONDA_CMD="conda"
else
  error "conda or mamba is required. Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
fi
info "Using: $CONDA_CMD"

# ── Conda environment ─────────────────────────────────────────────────────────
ENV_NAME="ailip"
if $CONDA_CMD env list | grep -q "^${ENV_NAME}"; then
  warn "Conda env '${ENV_NAME}' already exists. Skipping creation."
else
  info "Creating conda env: ${ENV_NAME} (Python 3.10)..."
  $CONDA_CMD create -y -n "$ENV_NAME" python=3.10
fi

# Activate helper (works in both conda and mamba)
CONDA_BASE=$($CONDA_CMD info --base)
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"
info "Activated conda env: $ENV_NAME"

# ── PyTorch with CUDA ─────────────────────────────────────────────────────────
if $CPU_ONLY; then
  info "Installing PyTorch (CPU-only)..."
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
else
  info "Installing PyTorch 2.x + CUDA 11.8..."
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
fi

# ── Common deps ───────────────────────────────────────────────────────────────
info "Installing common Python dependencies..."
pip install \
  numpy \
  scipy \
  opencv-python \
  pillow \
  imageio \
  imageio-ffmpeg \
  tqdm \
  einops \
  omegaconf \
  pyyaml \
  huggingface_hub \
  accelerate \
  diffusers \
  transformers \
  basicsr \
  facexlib \
  gfpgan \
  realesrgan

mkdir -p "$VENDOR_DIR"

# ── LatentSync ────────────────────────────────────────────────────────────────
LSYNC_DIR="$VENDOR_DIR/LatentSync"
if [[ -d "$LSYNC_DIR" ]]; then
  warn "LatentSync already cloned. Pulling latest..."
  git -C "$LSYNC_DIR" pull --ff-only || true
else
  info "Cloning LatentSync..."
  git clone https://github.com/bytedance/LatentSync.git "$LSYNC_DIR"
fi

info "Installing LatentSync dependencies..."
pip install -r "$LSYNC_DIR/requirements.txt" 2>/dev/null || true

# Download LatentSync checkpoint
LSYNC_CKPT="$LSYNC_DIR/checkpoints/latentsync_unet.pt"
if [[ -f "$LSYNC_CKPT" ]]; then
  warn "LatentSync checkpoint already exists."
else
  info "Downloading LatentSync checkpoint (~2 GB)..."
  mkdir -p "$(dirname "$LSYNC_CKPT")"
  # Try HuggingFace Hub download via Python
  python - <<'PYEOF'
from huggingface_hub import hf_hub_download
import shutil, os

ckpt = hf_hub_download(
    repo_id="ByteDance/LatentSync",
    filename="latentsync_unet.pt",
    local_dir="vendor/LatentSync/checkpoints",
)
print(f"Downloaded to {ckpt}")
PYEOF
fi

# whisper model for LatentSync audio encoder
python -c "import whisper; whisper.load_model('small')" 2>/dev/null || \
  pip install openai-whisper 2>/dev/null || \
  warn "whisper install failed — LatentSync may need it. Try: pip install openai-whisper"

# ── VideoReTalking ────────────────────────────────────────────────────────────
VRT_DIR="$VENDOR_DIR/video-retalking"
if [[ -d "$VRT_DIR" ]]; then
  warn "VideoReTalking already cloned."
else
  info "Cloning VideoReTalking..."
  git clone https://github.com/OpenTalker/video-retalking.git "$VRT_DIR"
fi

info "Installing VideoReTalking dependencies..."
pip install -r "$VRT_DIR/requirements.txt" 2>/dev/null || true

VRT_CKPT_DIR="$VRT_DIR/checkpoints"
mkdir -p "$VRT_CKPT_DIR"

if [[ ! -f "$VRT_CKPT_DIR/BFM.zip" ]] && [[ ! -d "$VRT_CKPT_DIR/BFM" ]]; then
  info "Downloading VideoReTalking checkpoints..."
  python - <<'PYEOF'
from huggingface_hub import snapshot_download
import os

snapshot_download(
    repo_id="vinthony/video-retalking",
    local_dir="vendor/video-retalking/checkpoints",
    ignore_patterns=["*.md"],
)
print("VideoReTalking checkpoints downloaded.")
PYEOF
else
  warn "VideoReTalking checkpoints already present."
fi

# ── CodeFormer ────────────────────────────────────────────────────────────────
CF_DIR="$VENDOR_DIR/CodeFormer"
if [[ -d "$CF_DIR" ]]; then
  warn "CodeFormer already cloned."
else
  info "Cloning CodeFormer..."
  git clone https://github.com/sczhou/CodeFormer.git "$CF_DIR"
fi

info "Installing CodeFormer dependencies..."
pip install -r "$CF_DIR/requirements.txt" 2>/dev/null || true
python -c "
import sys; sys.path.insert(0, 'vendor/CodeFormer')
from basicsr.utils.download_util import load_file_from_url
import os
os.makedirs('vendor/CodeFormer/weights/CodeFormer', exist_ok=True)
load_file_from_url(
    url='https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth',
    model_dir='vendor/CodeFormer/weights/CodeFormer',
    progress=True,
)
print('CodeFormer weights downloaded.')
" 2>/dev/null || warn "CodeFormer weight download failed — run manually if needed."

# ── Real-ESRGAN ───────────────────────────────────────────────────────────────
RESRGAN_DIR="$VENDOR_DIR/Real-ESRGAN"
if [[ -d "$RESRGAN_DIR" ]]; then
  warn "Real-ESRGAN already cloned."
else
  info "Cloning Real-ESRGAN..."
  git clone https://github.com/xinntao/Real-ESRGAN.git "$RESRGAN_DIR"
fi

info "Installing Real-ESRGAN..."
pip install -r "$RESRGAN_DIR/requirements.txt" 2>/dev/null || true
(cd "$RESRGAN_DIR" && python setup.py develop 2>/dev/null) || \
  pip install realesrgan || \
  warn "Real-ESRGAN setup failed."

# Download RealESRGAN_x4plus model
RESRGAN_MODEL_DIR="$RESRGAN_DIR/weights"
mkdir -p "$RESRGAN_MODEL_DIR"
if [[ ! -f "$RESRGAN_MODEL_DIR/RealESRGAN_x4plus.pth" ]]; then
  info "Downloading RealESRGAN_x4plus weights..."
  curl -L \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
    -o "$RESRGAN_MODEL_DIR/RealESRGAN_x4plus.pth"
else
  warn "RealESRGAN_x4plus.pth already exists."
fi

# ── Video inference script for Real-ESRGAN ────────────────────────────────────
# Real-ESRGAN's main inference_realesrgan.py supports video via ffmpeg.
# Create a convenience wrapper if the dedicated video script doesn't exist.
VIDEO_INFER="$RESRGAN_DIR/inference_realesrgan_video.py"
if [[ ! -f "$VIDEO_INFER" ]]; then
  info "Creating Real-ESRGAN video inference wrapper..."
  cat > "$VIDEO_INFER" << 'PYEOF'
"""
Thin wrapper: calls inference_realesrgan.py with the same args.
Real-ESRGAN's main script handles video via ffmpeg internally.
"""
import subprocess, sys
args = [sys.executable, "inference_realesrgan.py"] + sys.argv[1:]
sys.exit(subprocess.call(args))
PYEOF
fi

# ── Final verification ────────────────────────────────────────────────────────
info "Verifying installation..."
python - <<'PYEOF'
import importlib, sys

ok = True
for mod in ["torch", "cv2", "PIL", "basicsr", "realesrgan"]:
    try:
        importlib.import_module(mod)
        print(f"  ✓ {mod}")
    except ImportError:
        print(f"  ✗ {mod} — MISSING")
        ok = False

import torch
print(f"  CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

if ok:
    print("\n✅  Setup complete! Run: python pipeline.py --help")
else:
    print("\n⚠️  Some packages missing. Check errors above.")
    sys.exit(1)
PYEOF

echo ""
info "Setup done. To run the pipeline:"
echo ""
echo "  conda activate ailip"
echo "  python pipeline.py \\"
echo "    --source inputs/face.mp4 \\"
echo "    --audio  inputs/speech.wav \\"
echo "    --output outputs/result_2k.mp4"
echo ""
