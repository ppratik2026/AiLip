#!/usr/bin/env python3
"""
AiLip Webapp
Page 1 — Image to Video (animated with Ken Burns effect or real SVD)
Page 2 — Lipsync     (Video + Audio/Text → 2K lipsynced output)
"""

from flask import Flask, render_template, request, jsonify, send_file, abort
import os
import sys
import uuid
import threading
import subprocess
import tempfile
from pathlib import Path

# Resolve pipeline root (one level up from webapp/)
PIPELINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PIPELINE_DIR))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

JOBS_DIR = Path(tempfile.gettempdir()) / "ailip_jobs"
JOBS_DIR.mkdir(exist_ok=True)

# ── In-memory job store ────────────────────────────────────────────────────────
_jobs: dict = {}
_lock = threading.Lock()

ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ALLOWED_VIDEO  = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_AUDIO  = {".wav", ".mp3", ".aac", ".m4a", ".ogg"}


def new_job() -> str:
    jid = str(uuid.uuid4())
    with _lock:
        _jobs[jid] = {"status": "queued", "progress": 0, "message": "Queued…", "output": None, "error": None}
    return jid


def update_job(jid: str, **kwargs):
    with _lock:
        if jid in _jobs:
            _jobs[jid].update(kwargs)


def get_job(jid: str) -> dict:
    with _lock:
        return dict(_jobs.get(jid, {}))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_ext(filename: str, allowed: set) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext in allowed else list(allowed)[0]


def _text_to_speech(text: str, output_wav: str):
    """Convert text to WAV using gTTS → ffmpeg, falling back to pyttsx3."""
    try:
        from gtts import gTTS
        tmp_mp3 = output_wav.replace(".wav", "_tmp.mp3")
        gTTS(text=text, lang="en").save(tmp_mp3)
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_mp3, output_wav],
            check=True, capture_output=True
        )
        os.remove(tmp_mp3)
    except ImportError:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, output_wav)
            engine.runAndWait()
        except Exception:
            raise RuntimeError(
                "No TTS engine available. Install one: pip install gTTS"
            )


def _get_audio_duration(audio_path: str) -> float:
    """Return duration of audio file in seconds via ffprobe."""
    import json as _json
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-of", "json",
         "-show_entries", "format=duration", str(audio_path)],
        capture_output=True, text=True,
    )
    try:
        return float(_json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 8.0


def _build_animation_vf(style: str, frames: int) -> str:
    """Return ffmpeg -vf string for the requested Ken Burns style."""
    if style == "zoom_in":
        return (
            f"zoompan=z='if(lte(on,1),1.0,min(1.4,zoom+0.0015))'"
            f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale=1280:720"
        )
    if style == "zoom_out":
        return (
            f"zoompan=z='if(lte(on,1),1.4,max(1.0,zoom-0.0015))'"
            f":d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',scale=1280:720"
        )
    if style == "pan_right":
        return (
            f"zoompan=z=1.3:d={frames}"
            f":x='if(lte(on,1),0,min(iw*0.2,x+iw*0.2/{frames}))'"
            f":y='ih/2-(ih/zoom/2)',scale=1280:720"
        )
    if style == "pan_left":
        return (
            f"zoompan=z=1.3:d={frames}"
            f":x='if(lte(on,1),iw*0.2,max(0,x-iw*0.2/{frames}))'"
            f":y='ih/2-(ih/zoom/2)',scale=1280:720"
        )
    # still / default
    return "scale=1280:720"


def _render_animated_video(image_path: Path, vf: str, duration: float, fps: int, output_path: Path):
    fps_arg = str(fps)
    if vf == "scale=1280:720":
        # still image — no zoompan needed
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-vf", vf, "-c:v", "libx264", "-t", str(duration),
            "-pix_fmt", "yuv420p", "-r", fps_arg, str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-vf", vf, "-c:v", "libx264", "-t", str(duration),
            "-pix_fmt", "yuv420p", str(output_path),
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg animation failed:\n{result.stderr[-600:]}")


# ── Image-to-Video worker ──────────────────────────────────────────────────────

MIN_DURATION = 8.0   # seconds — enforced minimum for all outputs
WORDS_PER_SEC = 2.3  # average TTS speaking rate

def _parse_animation(prompt: str) -> str:
    """Return animation style key from prompt text."""
    p = prompt.lower()
    if any(k in p for k in ["zoom in", "zoom-in", "close up", "closer"]):
        return "zoom_in"
    if any(k in p for k in ["zoom out", "zoom-out", "pull back", "wider"]):
        return "zoom_out"
    if any(k in p for k in ["pan right", "move right", "slide right"]):
        return "pan_right"
    if any(k in p for k in ["pan left", "move left", "slide left"]):
        return "pan_left"
    if any(k in p for k in ["still", "static", "no movement"]):
        return "still"
    return "zoom_in"


def _run_img2vid(
    job_id: str,
    image_path: Path,
    prompt: str,
    base_duration: float,
    dialogues: list[str],   # list of dialogue strings (may be empty)
    job_dir: Path,
):
    try:
        update_job(job_id, status="running", progress=5, message="Analyzing prompt…")

        has_dialogue = any(d.strip() for d in dialogues)
        fps = 25

        # ── Step 1: TTS (if dialogue provided) ────────────────────────────
        audio_path = None
        if has_dialogue:
            full_text = " ".join(d.strip() for d in dialogues if d.strip())
            update_job(job_id, progress=12, message="Generating speech from dialogue…")
            audio_path = job_dir / "dialogue.wav"
            _text_to_speech(full_text, str(audio_path))
            audio_dur  = _get_audio_duration(str(audio_path))
            # 1 second padding after speech, enforce 8 s minimum
            duration   = max(MIN_DURATION, audio_dur + 1.0)
        else:
            duration = max(MIN_DURATION, base_duration)

        frames = int(duration * fps)
        style  = _parse_animation(prompt)
        vf     = _build_animation_vf(style, frames)

        # ── Step 2: Render animation ───────────────────────────────────────
        update_job(job_id, progress=28, message=f"Rendering {duration:.1f}s animated video…")
        animated_path = job_dir / "animated.mp4"
        _render_animated_video(image_path, vf, duration, fps, animated_path)

        # ── Step 3: Lipsync (only when dialogue given) ─────────────────────
        if has_dialogue:
            update_job(job_id, progress=48, message="Running lipsync on animated video…")
            output_path = job_dir / "output.mp4"
            pipeline_script = PIPELINE_DIR / "pipeline.py"

            cmd = [
                sys.executable, str(pipeline_script),
                "--source", str(animated_path),
                "--audio",  str(audio_path),
                "--output", str(output_path),
                "--model",  "auto",
                "--no-enhance",   # keep Page 1 fast; user can enhance on Page 2
                "--no-upscale",
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(PIPELINE_DIR),
            )
            step_map = {"[1/4]": (60, "Lipsync model running…"), "[4/4]": (88, "Merging audio…")}
            for line in proc.stdout:
                for tag, (pct, msg) in step_map.items():
                    if tag in line:
                        update_job(job_id, progress=pct, message=msg)
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError("Lipsync step failed. Run setup.sh to ensure models are downloaded.")
        else:
            output_path = animated_path

        update_job(job_id, status="done", progress=100, message="Video ready!", output=str(output_path))

    except Exception as exc:
        update_job(job_id, status="error", progress=0, message=str(exc), error=str(exc))


# ── Lipsync worker ─────────────────────────────────────────────────────────────

def _run_lipsync(
    job_id: str,
    video_path: Path,
    audio_path: Path,
    dialogue_text: str | None,
    model: str,
    no_enhance: bool,
    no_upscale: bool,
    job_dir: Path,
):
    try:
        # Step 0: TTS if no audio file provided
        if dialogue_text:
            update_job(job_id, status="running", progress=8, message="Converting text to speech…")
            _text_to_speech(dialogue_text, str(audio_path))

        output_path = job_dir / "output_2k.mp4"
        pipeline_script = PIPELINE_DIR / "pipeline.py"

        cmd = [
            sys.executable, str(pipeline_script),
            "--source", str(video_path),
            "--audio", str(audio_path),
            "--output", str(output_path),
            "--model", model,
        ]
        if no_enhance:
            cmd.append("--no-enhance")
        if no_upscale:
            cmd.append("--no-upscale")

        update_job(job_id, status="running", progress=15, message="Starting pipeline…")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(PIPELINE_DIR),
        )

        step_progress = {"[1/4]": 25, "[2/4]": 55, "[3/4]": 75, "[4/4]": 92}
        step_msgs = {
            "[1/4]": "Lipsync model running…",
            "[2/4]": "Enhancing faces with CodeFormer…",
            "[3/4]": "Upscaling to 2K with Real-ESRGAN…",
            "[4/4]": "Merging audio…",
        }
        for line in proc.stdout:
            for tag, pct in step_progress.items():
                if tag in line:
                    update_job(job_id, progress=pct, message=step_msgs[tag])

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(
                "Pipeline failed. Make sure setup.sh was run and all models are downloaded."
            )

        update_job(job_id, status="done", progress=100, message="Lipsync complete!", output=str(output_path))

    except Exception as exc:
        update_job(job_id, status="error", progress=0, message=str(exc), error=str(exc))


# ── API routes ─────────────────────────────────────────────────────────────────

@app.route("/api/img2vid", methods=["POST"])
def api_img2vid():
    if "image" not in request.files or not request.files["image"].filename:
        return jsonify(error="No image uploaded"), 400

    img_file  = request.files["image"]
    ext       = _safe_ext(img_file.filename, ALLOWED_IMAGE)
    prompt    = request.form.get("prompt", "").strip()
    duration  = float(request.form.get("duration", MIN_DURATION))

    # Accept multiple dialogue lines sent as dialogue[] or dialogue
    dialogues = request.form.getlist("dialogue[]") or request.form.getlist("dialogue")

    job_id  = new_job()
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    image_path = job_dir / f"input{ext}"
    img_file.save(str(image_path))

    threading.Thread(
        target=_run_img2vid,
        args=(job_id, image_path, prompt, duration, dialogues, job_dir),
        daemon=True,
    ).start()

    return jsonify(job_id=job_id)


@app.route("/api/lipsync", methods=["POST"])
def api_lipsync():
    if "video" not in request.files or not request.files["video"].filename:
        return jsonify(error="No video uploaded"), 400

    video_file = request.files["video"]
    has_audio  = "audio" in request.files and request.files["audio"].filename
    dialogue   = request.form.get("dialogue", "").strip()

    if not has_audio and not dialogue:
        return jsonify(error="Provide an audio file or dialogue text"), 400

    model       = request.form.get("model", "auto")
    no_enhance  = request.form.get("no_enhance") == "true"
    no_upscale  = request.form.get("no_upscale") == "true"

    job_id  = new_job()
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    vid_ext  = _safe_ext(video_file.filename, ALLOWED_VIDEO)
    vid_path = job_dir / f"input{vid_ext}"
    video_file.save(str(vid_path))

    if has_audio:
        aud_file = request.files["audio"]
        aud_ext  = _safe_ext(aud_file.filename, ALLOWED_AUDIO)
        aud_path = job_dir / f"audio{aud_ext}"
        aud_file.save(str(aud_path))
        dialogue_text = None
    else:
        aud_path      = job_dir / "audio.wav"
        dialogue_text = dialogue

    threading.Thread(
        target=_run_lipsync,
        args=(job_id, vid_path, aud_path, dialogue_text, model, no_enhance, no_upscale, job_dir),
        daemon=True,
    ).start()

    return jsonify(job_id=job_id)


@app.route("/api/job/<job_id>")
def api_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return jsonify(error="Not found"), 404
    return jsonify(job)


@app.route("/api/download/<job_id>")
def api_download(job_id: str):
    job = get_job(job_id)
    if not job or job.get("status") != "done":
        abort(404)
    output = job.get("output")
    if not output or not Path(output).exists():
        abort(404)
    fname = "ailip_video.mp4" if "lipsync" in str(output) else "ailip_animated.mp4"
    return send_file(output, as_attachment=True, download_name=fname, mimetype="video/mp4")


# ── Page routes ────────────────────────────────────────────────────────────────

@app.route("/")
def page1():
    return render_template("page1.html")


@app.route("/lipsync")
def page2():
    return render_template("page2.html")


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)
