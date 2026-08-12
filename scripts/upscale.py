"""
Upscaling step: Real-ESRGAN frame-by-frame → 2560x1440 (2K).

Frame pipeline:
  1. ffmpeg: extract PNG frames from input video
  2. Real-ESRGAN: upscale each frame (4x)
  3. ffmpeg: reconstruct video at 2K (scale + letterbox/pillarbox to 2560x1440)
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

from .utils import run_cmd, require_dir, get_video_info, log

REALESRGAN_DIR = Path(__file__).parent.parent / "vendor" / "Real-ESRGAN"

TARGET_W = 2560
TARGET_H = 1440


def run_upscale(
    video_path: str,
    output_path: str,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
    gpu_id: int = 0,
    model_name: str = "RealESRGAN_x4plus",
    face_enhance: bool = False,
    tile: int = 0,
):
    """
    Upscale video to target resolution using Real-ESRGAN (frame-based).

    face_enhance: use Real-ESRGAN's built-in GFPGAN face pass.
                  Set False when CodeFormer was already run.
    tile: tiled inference size in px (0 = disabled). Use 256 or 512 for OOM.
    """
    require_dir(str(REALESRGAN_DIR), "Real-ESRGAN")

    weights_dir  = REALESRGAN_DIR / "weights"
    model_file   = weights_dir / f"{model_name}.pth"
    if not model_file.exists():
        raise FileNotFoundError(
            f"Real-ESRGAN model not found: {model_file}\n"
            "Run setup.sh to download it."
        )

    info = get_video_info(video_path)
    fps  = info["fps"]
    log.info("Source: %dx%d @ %.2f fps", info["width"], info["height"], fps)

    frames_in  = tempfile.mkdtemp(prefix="ailip_esrgan_in_")
    frames_out = tempfile.mkdtemp(prefix="ailip_esrgan_out_")

    try:
        # ── Step 1: extract frames ─────────────────────────────────────────
        log.info("Extracting frames...")
        rc = run_cmd([
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vsync", "0",
            "-q:v", "2",
            f"{frames_in}/frame_%06d.png",
        ])
        if rc != 0:
            raise RuntimeError("ffmpeg frame extraction failed")

        n_frames = len(list(Path(frames_in).glob("*.png")))
        log.info("Extracted %d frames", n_frames)

        # ── Step 2: Real-ESRGAN upscale ────────────────────────────────────
        inference_script = REALESRGAN_DIR / "inference_realesrgan.py"
        if not inference_script.exists():
            raise FileNotFoundError(
                f"inference_realesrgan.py not found at {REALESRGAN_DIR}\n"
                "Run setup.sh to clone Real-ESRGAN."
            )

        cmd = [
            sys.executable, str(inference_script),
            "-n", model_name,
            "-i", frames_in,
            "-o", frames_out,
            "--outscale", "4",
            "--model_path", str(model_file),
        ]
        if face_enhance:
            cmd.append("--face_enhance")
        if tile > 0:
            cmd += ["--tile", str(tile)]

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

        log.info("Running Real-ESRGAN (4x, model=%s)...", model_name)
        rc = run_cmd(cmd, cwd=str(REALESRGAN_DIR), env=env)
        if rc != 0:
            raise RuntimeError(f"Real-ESRGAN failed (exit {rc})")

        # Real-ESRGAN outputs frame_000001_out.png, etc.
        # Rename to sequential frame_%06d.png for ffmpeg
        upscaled = sorted(Path(frames_out).glob("*_out.png"))
        if not upscaled:
            # Some versions output without _out suffix
            upscaled = sorted(Path(frames_out).glob("*.png"))
        if not upscaled:
            raise RuntimeError("Real-ESRGAN produced no output frames")

        for i, src in enumerate(upscaled, start=1):
            src.rename(src.parent / f"frame_{i:06d}.png")

        log.info("Upscaled %d frames", len(upscaled))

        # ── Step 3: reconstruct video at 2K ───────────────────────────────
        vf = (
            f"scale={target_w}:{target_h}"
            ":force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        log.info("Reconstructing at %dx%d...", target_w, target_h)
        rc = run_cmd([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{frames_out}/frame_%06d.png",
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", "16",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])
        if rc != 0:
            raise RuntimeError("ffmpeg video reconstruction failed")

        log.info("Upscale done → %s", output_path)

    finally:
        shutil.rmtree(frames_in,  ignore_errors=True)
        shutil.rmtree(frames_out, ignore_errors=True)
