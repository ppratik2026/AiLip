"""Shared utilities for the AiLip pipeline."""

import subprocess
import logging
import shutil
import json
from pathlib import Path

log = logging.getLogger("ailip")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(message)s",
        level=level,
    )


def check_vram() -> float:
    """Return free VRAM in GB on GPU 0, or 0 if no GPU found."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        )
        mb = int(result.stdout.strip().split("\n")[0].strip())
        return mb / 1024.0
    except Exception:
        return 0.0


def get_video_info(video_path: str) -> dict:
    """Return basic video metadata via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    video_stream = next(
        (s for s in data["streams"] if s["codec_type"] == "video"), {}
    )
    audio_stream = next(
        (s for s in data["streams"] if s["codec_type"] == "audio"), None
    )
    fps_raw = video_stream.get("avg_frame_rate", "25/1")
    num, den = fps_raw.split("/")
    fps = float(num) / float(den) if float(den) else 25.0
    return {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "duration": float(video_stream.get("duration", 0)),
        "has_audio": audio_stream is not None,
    }


def run_cmd(cmd: list, cwd: str = None, env: dict = None) -> int:
    """Run a shell command, streaming output to the logger. Returns exit code."""
    log.debug("Running: %s", " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
        env=env,
    )
    for line in proc.stdout:
        log.debug(line.rstrip())
    proc.wait()
    return proc.returncode


def require_tool(name: str):
    if not shutil.which(name):
        raise EnvironmentError(
            f"Required tool '{name}' not found. Run setup.sh first."
        )


def require_dir(path: str, label: str):
    p = Path(path)
    if not p.is_dir():
        raise EnvironmentError(
            f"{label} directory not found at '{path}'. Run setup.sh first."
        )


def image_to_video(image_path: str, audio_path: str, output_path: str, fps: float = 25.0):
    """Wrap a still image into a looping video matching the audio duration."""
    require_tool("ffprobe")
    require_tool("ffmpeg")
    # Get audio duration
    cmd = [
        "ffprobe", "-v", "quiet", "-of", "json",
        "-show_entries", "format=duration",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])

    run_cmd([
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(fps),
        "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        str(output_path),
    ])
