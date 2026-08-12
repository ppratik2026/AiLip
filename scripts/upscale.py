"""
Upscaling step: Real-ESRGAN video-mode → 2560x1440 (2K).

Uses Real-ESRGAN's video inference for temporal consistency.
Final ffmpeg pass letterboxes/pillarboxes to exact 2560x1440 if needed.
"""

import os
import sys
import tempfile
import logging
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
    Upscale video to target resolution using Real-ESRGAN.

    face_enhance: Use Real-ESRGAN's built-in face enhancement (GFPGAN-based).
    Set to False if CodeFormer was already run before this step.
    tile: Tile size for tiled inference (0 = no tiling, use if OOM).
    """
    require_dir(str(REALESRGAN_DIR), "Real-ESRGAN")

    info = get_video_info(video_path)
    src_w, src_h, fps = info["width"], info["height"], info["fps"]
    log.info("Source resolution: %dx%d @ %.2f fps", src_w, src_h, fps)

    # Calculate needed outscale to meet or exceed target dimensions
    scale_w = target_w / src_w
    scale_h = target_h / src_h
    # Use 4x (Real-ESRGAN default) and let ffmpeg finish the resize
    outscale = 4

    tmp_upscaled = tempfile.mktemp(suffix="_realesrgan.mp4", prefix="ailip_")

    try:
        inference_script = REALESRGAN_DIR / "inference_realesrgan_video.py"
        if not inference_script.exists():
            # Fallback to main inference script which also accepts video
            inference_script = REALESRGAN_DIR / "inference_realesrgan.py"

        cmd = [
            sys.executable, str(inference_script),
            "-n", model_name,
            "-i", str(video_path),
            "-o", tmp_upscaled,
            "--outscale", str(outscale),
        ]
        if face_enhance:
            cmd.append("--face_enhance")
        if tile > 0:
            cmd += ["--tile", str(tile)]

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

        log.info("Running Real-ESRGAN (outscale=%dx)...", outscale)
        rc = run_cmd(cmd, cwd=str(REALESRGAN_DIR), env=env)
        if rc != 0:
            raise RuntimeError(f"Real-ESRGAN failed with exit code {rc}")

        # Final ffmpeg pass: scale + pad to exact target resolution
        # scale=w:h:force_original_aspect_ratio=decrease,pad=w:h:(ow-iw)/2:(oh-ih)/2
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
        log.info("Scaling to %dx%d...", target_w, target_h)
        rc = run_cmd([
            "ffmpeg", "-y",
            "-i", tmp_upscaled,
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", "16",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])
        if rc != 0:
            raise RuntimeError("ffmpeg final scale failed")

        log.info("Upscale done → %s", output_path)

    finally:
        if os.path.exists(tmp_upscaled):
            os.remove(tmp_upscaled)
