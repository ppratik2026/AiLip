"""
Face enhancement step using CodeFormer.

Extracts frames → CodeFormer face restore → reconstructs video.
"""

import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path

from .utils import run_cmd, require_dir, get_video_info, log

CODEFORMER_DIR = Path(__file__).parent.parent / "vendor" / "CodeFormer"


def run_enhance(
    video_path: str,
    output_path: str,
    gpu_id: int = 0,
    fidelity_weight: float = 0.7,
    face_upsample: bool = True,
    bg_tile: int = 400,
):
    """
    Enhance faces in a video using CodeFormer.

    fidelity_weight: 0 = max restoration quality, 1 = max fidelity to input.
    0.7 is a good balance.
    """
    require_dir(str(CODEFORMER_DIR), "CodeFormer")

    info = get_video_info(video_path)
    fps = info["fps"]

    frames_dir = tempfile.mkdtemp(prefix="ailip_frames_in_")
    enhanced_dir = tempfile.mkdtemp(prefix="ailip_frames_out_")

    try:
        # Extract frames
        log.info("Extracting frames from %s (fps=%.2f)...", video_path, fps)
        rc = run_cmd([
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vsync", "0",
            "-q:v", "2",
            f"{frames_dir}/frame_%06d.png",
        ])
        if rc != 0:
            raise RuntimeError("ffmpeg frame extraction failed")

        frame_count = len(list(Path(frames_dir).glob("*.png")))
        log.info("Extracted %d frames", frame_count)

        # Run CodeFormer
        cmd = [
            sys.executable, "inference_codeformer.py",
            "--input_path", frames_dir,
            "--output_path", enhanced_dir,
            "-w", str(fidelity_weight),
            "--bg_tile", str(bg_tile),
        ]
        if face_upsample:
            cmd.append("--face_upsample")

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

        log.info("Running CodeFormer face enhancement...")
        rc = run_cmd(cmd, cwd=str(CODEFORMER_DIR), env=env)
        if rc != 0:
            raise RuntimeError(f"CodeFormer failed with exit code {rc}")

        # CodeFormer outputs to a subfolder named 'final_results'
        final_dir = Path(enhanced_dir) / "final_results"
        if not final_dir.exists():
            # Some versions output directly
            final_dir = Path(enhanced_dir)

        # Reconstruct video from enhanced frames
        log.info("Reconstructing video from enhanced frames...")
        rc = run_cmd([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-pattern_type", "glob",
            "-i", f"{final_dir}/*.png",
            "-c:v", "libx264",
            "-crf", "17",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])
        if rc != 0:
            raise RuntimeError("ffmpeg video reconstruction failed")

        log.info("CodeFormer enhancement done → %s", output_path)

    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        shutil.rmtree(enhanced_dir, ignore_errors=True)
