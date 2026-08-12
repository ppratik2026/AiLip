"""Shared utilities for the AiLip pipeline."""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("ailip")


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="[%(levelname)s] %(message)s",
        level=level,
    )


def check_vram() -> float:
    """Return free VRAM in GB on GPU 0, or 0.0 if no GPU found."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        )
        mb = int(result.stdout.strip().split("\n")[0].strip())
        return mb / 1024.0
    except Exception:
        return 0.0


def _ffmpeg_duration(path: str) -> float:
    """Parse duration from ffmpeg's stderr output (works without ffprobe)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(path)],
        capture_output=True, text=True,
    )
    m = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", result.stderr)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    return 0.0


def get_video_info(video_path: str) -> dict:
    """Return basic video metadata.

    Tries ffprobe (JSON) first; falls back to ffmpeg stderr parsing.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            cmd = [
                ffprobe, "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(video_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data   = json.loads(result.stdout)
            vstream = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
            astream = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
            fps_raw = vstream.get("avg_frame_rate", "25/1")
            num, den = fps_raw.split("/")
            fps = float(num) / float(den) if float(den) else 25.0
            return {
                "width":     int(vstream.get("width", 0)),
                "height":    int(vstream.get("height", 0)),
                "fps":       fps,
                "duration":  float(vstream.get("duration", 0)),
                "has_audio": astream is not None,
            }
        except Exception:
            pass  # fall through to ffmpeg fallback

    # Fallback: parse ffmpeg stderr
    result = subprocess.run(
        ["ffmpeg", "-i", str(video_path)],
        capture_output=True, text=True,
    )
    stderr = result.stderr

    # Resolution
    res_m = re.search(r"(\d{2,5})x(\d{2,5})", stderr)
    w = int(res_m.group(1)) if res_m else 0
    h = int(res_m.group(2)) if res_m else 0

    # FPS
    fps_m = re.search(r"([\d.]+)\s+fps", stderr)
    fps = float(fps_m.group(1)) if fps_m else 25.0

    # Duration
    dur_m = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", stderr)
    if dur_m:
        dur = int(dur_m.group(1)) * 3600 + int(dur_m.group(2)) * 60 + float(dur_m.group(3))
    else:
        dur = 0.0

    has_audio = "Audio:" in stderr

    return {"width": w, "height": h, "fps": fps, "duration": dur, "has_audio": has_audio}


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
            f"Required tool '{name}' not found.\n"
            "Run:  sudo apt install ffmpeg\n"
            "Or:   bash setup.sh  (installs everything)"
        )


def require_dir(path: str, label: str):
    p = Path(path)
    if not p.is_dir():
        raise EnvironmentError(
            f"{label} directory not found at '{path}'.\n"
            "Run: bash setup.sh  to clone and download all models."
        )


def image_to_video(
    image_path: str,
    audio_path: str,
    output_path: str,
    fps: float = 25.0,
):
    """Wrap a still image into a looping video matching the audio duration."""
    require_tool("ffmpeg")

    # Get audio duration (try ffprobe first, fall back to ffmpeg stderr)
    duration = 0.0
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            cmd = [
                ffprobe, "-v", "quiet", "-of", "json",
                "-show_entries", "format=duration",
                str(audio_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except Exception:
            pass
    if not duration:
        duration = _ffmpeg_duration(audio_path) or 8.0

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
