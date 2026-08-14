"""
Lipsync step: LatentSync (primary) with VideoReTalking fallback.

LatentSync  requires ~8 GB+ free VRAM.
VideoReTalking requires ~4-6 GB free VRAM.
"""

import os
import sys
import logging
from pathlib import Path

from .utils import check_vram, run_cmd, require_dir, log

LATENTSYNC_DIR = Path(__file__).parent.parent / "vendor" / "LatentSync"
VIDEORETALKING_DIR = Path(__file__).parent.parent / "vendor" / "video-retalking"

LATENTSYNC_VRAM_THRESHOLD = 8.0  # GB


def run_latentsync(
    video_path: str,
    audio_path: str,
    output_path: str,
    gpu_id: int = 0,
    guidance_scale: float = 2.0,
    seed: int = 1247,
):
    require_dir(str(LATENTSYNC_DIR), "LatentSync")

    ckpt = LATENTSYNC_DIR / "checkpoints" / "latentsync_unet.pt"
    if not ckpt.exists():
        raise FileNotFoundError(
            f"LatentSync checkpoint not found at {ckpt}. Run setup.sh."
        )

    unet_cfg = LATENTSYNC_DIR / "configs" / "unet" / "stage2.yaml"

    cmd = [
        sys.executable, "-m", "scripts.inference",
        "--unet_config_path", str(unet_cfg),
        "--inference_ckpt_path", str(ckpt),
        "--guidance_scale", str(guidance_scale),
        "--video_path", str(video_path),
        "--audio_path", str(audio_path),
        "--video_out_path", str(output_path),
        "--seed", str(seed),
    ]

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    log.info("Running LatentSync lipsync...")
    rc = run_cmd(cmd, cwd=str(LATENTSYNC_DIR), env=env)
    if rc != 0:
        raise RuntimeError(f"LatentSync failed with exit code {rc}")
    log.info("LatentSync done → %s", output_path)


def run_videoretalking(
    video_path: str,
    audio_path: str,
    output_path: str,
    gpu_id: int = 0,
):
    require_dir(str(VIDEORETALKING_DIR), "VideoReTalking")

    cmd = [
        sys.executable, "inference.py",
        "--face", str(video_path),
        "--audio", str(audio_path),
        "--outfile", str(output_path),
    ]

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    log.info("Running VideoReTalking lipsync...")
    rc = run_cmd(cmd, cwd=str(VIDEORETALKING_DIR), env=env)
    if rc != 0:
        raise RuntimeError(f"VideoReTalking failed with exit code {rc}")
    log.info("VideoReTalking done → %s", output_path)


def run_lipsync(
    video_path: str,
    audio_path: str,
    output_path: str,
    model: str = "auto",
    gpu_id: int = 0,
    **kwargs,
):
    """
    Run the lipsync step.
    model: 'auto' | 'latentsync' | 'videoretalking'
    'auto' picks LatentSync if free VRAM >= 8 GB, else VideoReTalking.
    """
    if model == "auto":
        vram = check_vram()
        log.info("Detected %.1f GB free VRAM", vram)
        model = "latentsync" if vram >= LATENTSYNC_VRAM_THRESHOLD else "videoretalking"
        log.info("Auto-selected model: %s", model)

    if model == "latentsync":
        run_latentsync(video_path, audio_path, output_path, gpu_id=gpu_id, **kwargs)
    elif model == "videoretalking":
        run_videoretalking(video_path, audio_path, output_path, gpu_id=gpu_id)
    else:
        raise ValueError(f"Unknown lipsync model: {model!r}")
