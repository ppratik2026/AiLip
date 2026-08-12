"""Audio-video merge step using ffmpeg."""

import logging
from .utils import run_cmd, log


def merge_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    crf: int = 16,
):
    """
    Mux audio_path into video_path, replacing any existing audio track.
    Audio is re-encoded to AAC 192k. Video stream is copied as-is.
    """
    log.info("Merging audio → %s", output_path)
    rc = run_cmd([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(output_path),
    ])
    if rc != 0:
        raise RuntimeError(f"ffmpeg audio merge failed (exit code {rc})")
    log.info("Final output → %s", output_path)
