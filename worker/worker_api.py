#!/usr/bin/env python3
"""
AiLip — GPU Worker API
Runs on the GPU server (RunPod / Vast.ai / Lambda Labs / your machine).

The Hostinger webapp sends jobs here via HTTP. This API:
  - Receives uploaded files (video/image + audio)
  - Runs the full GPU pipeline (LatentSync → CodeFormer → Real-ESRGAN)
  - Exposes job status + file download endpoints

Security: all requests must carry  X-API-Key: <WORKER_API_KEY>  header.
Set WORKER_API_KEY env var on both the GPU server AND the Hostinger webapp.

Usage (GPU server):
    export WORKER_API_KEY="your-secret-key-here"
    python worker_api.py --port 8000
    # or: bash start_worker.sh
"""

import os
import sys
import uuid
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB

JOBS_DIR = Path(tempfile.gettempdir()) / "ailip_worker_jobs"
JOBS_DIR.mkdir(exist_ok=True)

_jobs: dict = {}
_lock = threading.Lock()

API_KEY = os.environ.get("WORKER_API_KEY", "").strip()
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ALLOWED_VIDEO  = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_AUDIO  = {".wav", ".mp3", ".aac", ".m4a", ".ogg"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_auth():
    if not API_KEY:
        return  # no key set → open (only for local/trusted network use)
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        abort(401, "Invalid API key")


# ── Job store ─────────────────────────────────────────────────────────────────

def _new_job() -> str:
    jid = str(uuid.uuid4())
    with _lock:
        _jobs[jid] = {"status": "queued", "progress": 0, "message": "Queued…", "output": None, "error": None}
    return jid


def _update(jid: str, **kw):
    with _lock:
        if jid in _jobs:
            _jobs[jid].update(kw)


def _get(jid: str) -> dict:
    with _lock:
        return dict(_jobs.get(jid, {}))


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(jid, source_path, audio_path, job_dir, model, no_enhance, no_upscale):
    try:
        output_path = job_dir / "output_2k.mp4"
        pipeline_script = ROOT_DIR / "pipeline.py"

        cmd = [
            sys.executable, str(pipeline_script),
            "--source", str(source_path),
            "--audio",  str(audio_path),
            "--output", str(output_path),
            "--model",  model,
        ]
        if no_enhance:
            cmd.append("--no-enhance")
        if no_upscale:
            cmd.append("--no-upscale")

        step_progress = {
            "[0/4]": (10, "Converting image to video…"),
            "[1/4]": (25, "Lipsync model running…"),
            "[2/4]": (55, "Enhancing faces with CodeFormer…"),
            "[3/4]": (75, "Upscaling to 2K with Real-ESRGAN…"),
            "[4/4]": (92, "Merging audio…"),
        }

        _update(jid, status="running", progress=5, message="Starting pipeline…")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(ROOT_DIR),
        )
        for line in proc.stdout:
            for tag, (pct, msg) in step_progress.items():
                if tag in line:
                    _update(jid, progress=pct, message=msg)

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("Pipeline failed. Check worker logs.")

        _update(jid, status="done", progress=100, message="Done!", output=str(output_path))

    except Exception as exc:
        _update(jid, status="error", progress=0, message=str(exc), error=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Public health check — no auth needed."""
    try:
        import torch
        gpu = torch.cuda.is_available()
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3 if gpu else 0
        gpu_name = torch.cuda.get_device_name(0) if gpu else "None"
    except Exception:
        gpu, vram, gpu_name = False, 0.0, "torch not installed"

    return jsonify({
        "status":   "ok",
        "gpu":      gpu,
        "vram_gb":  round(vram, 1),
        "gpu_name": gpu_name,
        "jobs":     len(_jobs),
    })


@app.route("/process", methods=["POST"])
def process():
    """
    Accept a lipsync job.

    Form fields:
      source  — video or image file
      audio   — audio file
      model   — auto | latentsync | videoretalking  (default: auto)
      no_enhance — true/false
      no_upscale — true/false
    """
    _check_auth()

    if "source" not in request.files or not request.files["source"].filename:
        return jsonify(error="No source file"), 400
    if "audio" not in request.files or not request.files["audio"].filename:
        return jsonify(error="No audio file"), 400

    src_file = request.files["source"]
    aud_file = request.files["audio"]

    src_ext  = Path(src_file.filename).suffix.lower()
    aud_ext  = Path(aud_file.filename).suffix.lower()

    if src_ext not in ALLOWED_IMAGE | ALLOWED_VIDEO:
        return jsonify(error=f"Unsupported source format: {src_ext}"), 400
    if aud_ext not in ALLOWED_AUDIO:
        return jsonify(error=f"Unsupported audio format: {aud_ext}"), 400

    model      = request.form.get("model", "auto")
    no_enhance = request.form.get("no_enhance", "false").lower() == "true"
    no_upscale = request.form.get("no_upscale", "false").lower() == "true"

    jid     = _new_job()
    job_dir = JOBS_DIR / jid
    job_dir.mkdir()

    src_path = job_dir / f"source{src_ext}"
    aud_path = job_dir / f"audio{aud_ext}"
    src_file.save(str(src_path))
    aud_file.save(str(aud_path))

    threading.Thread(
        target=_run_pipeline,
        args=(jid, src_path, aud_path, job_dir, model, no_enhance, no_upscale),
        daemon=True,
    ).start()

    return jsonify(job_id=jid)


@app.route("/job/<jid>", methods=["GET"])
def job_status(jid):
    _check_auth()
    job = _get(jid)
    if not job:
        return jsonify(error="Not found"), 404
    return jsonify(job)


@app.route("/download/<jid>", methods=["GET"])
def download(jid):
    _check_auth()
    job = _get(jid)
    if not job or job.get("status") != "done":
        abort(404)
    output = job.get("output")
    if not output or not Path(output).exists():
        abort(404)
    return send_file(output, as_attachment=True, download_name="ailip_2k.mp4", mimetype="video/mp4")


@app.route("/cleanup/<jid>", methods=["DELETE"])
def cleanup(jid):
    """Delete job files to free disk space."""
    _check_auth()
    job_dir = JOBS_DIR / jid
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    with _lock:
        _jobs.pop(jid, None)
    return jsonify(ok=True)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AiLip GPU Worker API")
    parser.add_argument("--host",   default="0.0.0.0")
    parser.add_argument("--port",   type=int, default=8000)
    parser.add_argument("--debug",  action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    a = parser.parse_args()

    print()
    print("=" * 50)
    print("  AiLip GPU Worker API")
    print(f"  http://{a.host}:{a.port}")
    print(f"  API key: {'SET ✓' if API_KEY else 'NOT SET (open access)'}")
    print("=" * 50)
    print()

    if a.debug:
        app.run(host=a.host, port=a.port, debug=True)
    else:
        try:
            import gunicorn  # noqa: F401
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "gunicorn", "-q"], check=True)

        os.execvpe(sys.executable, [
            sys.executable, "-m", "gunicorn",
            "-w", str(a.workers),
            "-b", f"{a.host}:{a.port}",
            "--timeout", "7200",
            "--log-level", "info",
            "--access-logfile", "-",
            "worker_api:app",
        ], os.environ)
