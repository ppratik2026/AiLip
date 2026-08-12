#!/usr/bin/env python3
"""
AiLip — Demo Mode Runner
Tests the full webapp UI without any GPU or model downloads.

What works in demo mode:
  ✅ Image upload + drag-drop
  ✅ Multiple dialogue lines + live duration estimate
  ✅ Ken Burns animation (zoom/pan/still)
  ✅ Text-to-Speech (gTTS)
  ✅ Full progress bar + step indicators
  ✅ Video preview + download
  ⚡ Lipsync step → replaced with simple audio-video merge
  ⚡ CodeFormer / Real-ESRGAN → skipped (not downloaded)

Usage:
    python run_demo.py            # default port 5000
    python run_demo.py --port 8080
"""

import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path

WEBAPP_DIR = Path(__file__).parent
REQUIRED_PKGS = {
    "flask":           "flask",
    "gtts":            "gtts",
    "imageio_ffmpeg":  "imageio-ffmpeg",
}


def _install(pip_name: str):
    print(f"  Installing {pip_name}…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_name, "-q"],
        check=True,
    )


def ensure_deps():
    print("Checking dependencies…")
    for import_name, pip_name in REQUIRED_PKGS.items():
        try:
            __import__(import_name)
            print(f"  ✓ {pip_name}")
        except ImportError:
            _install(pip_name)
            print(f"  ✓ {pip_name} (just installed)")


def resolve_ffmpeg() -> str:
    """Return path to a working ffmpeg with libx264 support."""
    # 1. System ffmpeg
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        r = subprocess.run([sys_ff, "-codecs"], capture_output=True, text=True)
        if "libx264" in r.stdout or "h264" in r.stdout.lower():
            return sys_ff

    # 2. imageio-ffmpeg bundled binary (full codecs including libx264)
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ff, "-version"], capture_output=True, text=True)
    print(f"  Using ffmpeg: {ff.split('/')[-1]}")
    return ff


def create_sample_inputs():
    """Generate a simple sample face image for testing if inputs/ is empty."""
    inputs_dir = WEBAPP_DIR.parent / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    sample = inputs_dir / "sample_face.jpg"
    if sample.exists():
        return

    try:
        from PIL import Image, ImageDraw
        # Draw a simple placeholder face
        img = Image.new("RGB", (512, 512), color=(240, 220, 200))
        draw = ImageDraw.Draw(img)
        # Head outline
        draw.ellipse([80, 60, 430, 460], outline=(180, 150, 120), width=6)
        # Eyes
        draw.ellipse([160, 180, 210, 220], fill=(50, 50, 50))
        draw.ellipse([300, 180, 350, 220], fill=(50, 50, 50))
        # Nose
        draw.polygon([(256, 240), (230, 310), (282, 310)], outline=(180, 150, 120), width=3)
        # Mouth
        draw.arc([190, 310, 320, 380], start=10, end=170, fill=(180, 100, 100), width=5)
        img.save(str(sample), "JPEG", quality=90)
        print(f"  Created sample image: inputs/sample_face.jpg")
    except ImportError:
        pass   # PIL not available — user can upload their own image


def main():
    parser = argparse.ArgumentParser(description="AiLip Demo Mode")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print()
    print("=" * 55)
    print("  AiLip — Demo Mode (no GPU / no model downloads)")
    print("=" * 55)
    print()

    ensure_deps()
    ffmpeg_bin = resolve_ffmpeg()
    create_sample_inputs()

    # Set env vars for app.py
    os.environ["AILIP_DEMO"]       = "1"
    os.environ["AILIP_FFMPEG_BIN"] = ffmpeg_bin

    print()
    print(f"  DEMO_MODE  : ON  (lipsync replaced with audio-mux)")
    print(f"  FFMPEG     : {ffmpeg_bin}")
    print()
    print(f"  Starting server…")
    print(f"  Open: http://localhost:{args.port}")
    print()
    print("  Test checklist:")
    print("  1. Upload inputs/sample_face.jpg  (or any image)")
    print("  2. Click 'zoom in' chip")
    print("  3. Add 2–3 dialogue lines")
    print("  4. Click Generate + Lipsync → watch progress")
    print("  5. Download the output video")
    print("  6. Go to /lipsync page, upload that video + dialogue")
    print()

    sys.path.insert(0, str(WEBAPP_DIR))
    from app import app
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
