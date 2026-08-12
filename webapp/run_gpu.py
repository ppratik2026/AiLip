#!/usr/bin/env python3
"""
AiLip — GPU Mode Runner
Starts the full webapp with LatentSync + CodeFormer + Real-ESRGAN.

What's active in GPU mode:
  ✅ Image upload + Ken Burns animation
  ✅ Multiple dialogue lines + TTS (gTTS online, pyttsx3 offline)
  ✅ Full LatentSync or VideoReTalking lipsync (auto-selected by VRAM)
  ✅ CodeFormer face enhancement
  ✅ Real-ESRGAN 2K (2560×1440) upscaling
  ✅ Progress bar + step indicators
  ✅ Download final 2K video

Requirements:
  - Run `bash setup.sh` first to download all models
  - NVIDIA GPU with 4+ GB VRAM (8+ for LatentSync)
  - conda env "ailip" activated (or deps installed manually)

Usage:
    python run_gpu.py               # gunicorn, port 5000
    python run_gpu.py --port 8080
    python run_gpu.py --dev         # Flask dev server (auto-reload)
    python run_gpu.py --skip-checks # skip model file verification
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

WEBAPP_DIR = Path(__file__).parent
ROOT_DIR   = WEBAPP_DIR.parent
VENDOR_DIR = ROOT_DIR / "vendor"


# ── Pre-flight checks ─────────────────────────────────────────────────────────

def _check_gpu():
    """Return (has_gpu, vram_gb, gpu_name)."""
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return True, props.total_memory / 1024**3, props.name
    except ImportError:
        pass
    return False, 0.0, "None"


def _check_models():
    """Return list of missing model paths (empty = all OK)."""
    missing = []

    # LatentSync checkpoint
    ls_dir  = VENDOR_DIR / "LatentSync"
    ls_ckpt = ls_dir / "checkpoints" / "latentsync_unet.pt"
    if not ls_dir.exists():
        missing.append("LatentSync repo not cloned (run setup.sh)")
    elif not ls_ckpt.exists():
        missing.append(f"LatentSync checkpoint missing: {ls_ckpt}")

    # VideoReTalking checkpoint (fallback model)
    vrt_dir  = VENDOR_DIR / "video-retalking"
    vrt_ckpt = vrt_dir / "checkpoints" / "30_net_gen.pth"
    if not vrt_dir.exists():
        missing.append("VideoReTalking repo not cloned (run setup.sh)")
    elif not vrt_ckpt.exists():
        missing.append(f"VideoReTalking checkpoints missing: {vrt_dir / 'checkpoints'}")

    # CodeFormer
    cf_ckpt = VENDOR_DIR / "CodeFormer" / "weights" / "CodeFormer" / "codeformer.pth"
    if not cf_ckpt.exists():
        missing.append(f"CodeFormer weights missing: {cf_ckpt}")

    # Real-ESRGAN
    esrgan_ckpt = VENDOR_DIR / "Real-ESRGAN" / "weights" / "RealESRGAN_x4plus.pth"
    if not esrgan_ckpt.exists():
        missing.append(f"RealESRGAN weights missing: {esrgan_ckpt}")

    return missing


def _ensure_gunicorn():
    try:
        import gunicorn  # noqa: F401
    except ImportError:
        print("  Installing gunicorn...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "gunicorn", "-q"],
            check=True,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AiLip GPU Mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--port",         type=int, default=5000)
    parser.add_argument("--host",         default="0.0.0.0")
    parser.add_argument("--workers",      type=int, default=1,
                        help="Gunicorn worker count (keep 1 for GPU, default: 1)")
    parser.add_argument("--dev",          action="store_true",
                        help="Use Flask dev server instead of gunicorn (auto-reload)")
    parser.add_argument("--skip-checks",  action="store_true",
                        help="Skip GPU and model file verification")
    args = parser.parse_args()

    print()
    print("=" * 56)
    print("  AiLip — GPU Mode (Full Pipeline)")
    print("=" * 56)
    print()

    # ── GPU check ─────────────────────────────────────────────────────────────
    has_gpu, vram, gpu_name = _check_gpu()
    if has_gpu:
        lipsync_model = "LatentSync" if vram >= 8.0 else "VideoReTalking"
        print(f"  GPU    : {gpu_name}")
        print(f"  VRAM   : {vram:.1f} GB")
        print(f"  Model  : {lipsync_model}  (auto-selected at inference time)")
    else:
        print("  GPU    : NOT detected")
        if not args.skip_checks:
            print()
            print("  No NVIDIA GPU found. GPU mode will be very slow.")
            print("  For CPU testing without models, use: python run_demo.py")
            ans = input("  Continue anyway? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                sys.exit(0)
    print()

    # ── Model check ───────────────────────────────────────────────────────────
    if not args.skip_checks:
        missing = _check_models()
        if missing:
            print("  [!] Missing models — run  bash setup.sh  first:\n")
            for m in missing:
                print(f"      • {m}")
            print()
            print("  bash setup.sh")
            sys.exit(1)
        else:
            print("  Models : all present ✓")
            print()

    # ── Environment setup ─────────────────────────────────────────────────────
    # Make LatentSync importable (it runs as a module from its own dir via cwd,
    # but pipeline.py needs ROOT_DIR on sys.path)
    _prepend = os.pathsep.join([
        str(ROOT_DIR),
        str(VENDOR_DIR / "LatentSync"),
    ])
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = _prepend + (os.pathsep + existing if existing else "")

    print(f"  Starting server at http://localhost:{args.port}")
    print()

    sys.path.insert(0, str(WEBAPP_DIR))

    if args.dev:
        # Flask development server (auto-reload, single-threaded)
        from app import app
        app.run(host=args.host, port=args.port, debug=True, threaded=True)
    else:
        # Gunicorn — production WSGI server
        _ensure_gunicorn()
        os.chdir(str(WEBAPP_DIR))
        cmd = [
            sys.executable, "-m", "gunicorn",
            "-w", str(args.workers),
            "-b", f"{args.host}:{args.port}",
            "--timeout",   "3600",    # 1 h — long jobs (LatentSync + ESRGAN)
            "--keep-alive", "5",
            "--log-level", "info",
            "--access-logfile", "-",
            "--error-logfile",  "-",
            "app:app",
        ]
        os.execvpe(sys.executable, cmd, os.environ)


if __name__ == "__main__":
    main()
