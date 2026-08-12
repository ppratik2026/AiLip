#!/usr/bin/env python3
"""
AiLip — 2K Lipsync Pipeline
Single command: source video/image + audio → lipsynced 2560x1440 MP4

Usage:
  python pipeline.py --source face.mp4 --audio speech.wav --output result.mp4
  python pipeline.py --source face.jpg --audio speech.wav --output result.mp4 --model latentsync
  python pipeline.py --source face.mp4 --audio speech.wav --output result.mp4 --no-enhance --tile 256
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path so `scripts` package resolves correctly
sys.path.insert(0, str(Path(__file__).parent))

from scripts.utils import setup_logging, check_vram, get_video_info, require_tool, image_to_video, log
from scripts.lipsync import run_lipsync
from scripts.enhance import run_enhance
from scripts.upscale import run_upscale
from scripts.merge_av import merge_audio


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="AiLip: 2K Lipsync Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", required=True,
                        help="Input video (MP4/MKV/AVI) or image (JPG/PNG).")
    parser.add_argument("--audio", required=True,
                        help="Input audio file (WAV/MP3/AAC).")
    parser.add_argument("--output", required=True,
                        help="Output video path (.mp4).")

    parser.add_argument("--model", default="auto",
                        choices=["auto", "latentsync", "videoretalking"],
                        help="Lipsync model. 'auto' picks based on VRAM. (default: auto)")
    parser.add_argument("--gpu-id", type=int, default=0,
                        help="GPU index to use. (default: 0)")

    parser.add_argument("--no-enhance", action="store_true",
                        help="Skip CodeFormer face enhancement step.")
    parser.add_argument("--no-upscale", action="store_true",
                        help="Skip Real-ESRGAN 2K upscaling step.")

    parser.add_argument("--fidelity", type=float, default=0.7,
                        help="CodeFormer fidelity weight 0-1 (0=max restore, 1=max fidelity). (default: 0.7)")
    parser.add_argument("--guidance-scale", type=float, default=2.0,
                        help="LatentSync guidance scale. (default: 2.0)")
    parser.add_argument("--seed", type=int, default=1247,
                        help="LatentSync random seed. (default: 1247)")

    parser.add_argument("--target-width", type=int, default=2560,
                        help="Output width in pixels. (default: 2560)")
    parser.add_argument("--target-height", type=int, default=1440,
                        help="Output height in pixels. (default: 1440)")
    parser.add_argument("--tile", type=int, default=0,
                        help="Real-ESRGAN tile size (0=disabled). Use 256 if OOM. (default: 0)")
    parser.add_argument("--esrgan-model", default="RealESRGAN_x4plus",
                        help="Real-ESRGAN model name. (default: RealESRGAN_x4plus)")

    parser.add_argument("--keep-temp", action="store_true",
                        help="Keep intermediate files for debugging.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show debug output.")

    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)

    # Validate inputs
    source = Path(args.source)
    audio = Path(args.audio)
    output = Path(args.output)

    if not source.exists():
        log.error("Source file not found: %s", source)
        sys.exit(1)
    if not audio.exists():
        log.error("Audio file not found: %s", audio)
        sys.exit(1)

    require_tool("ffmpeg")
    # ffprobe is used when available; utils.py falls back to ffmpeg stderr parsing otherwise

    output.parent.mkdir(parents=True, exist_ok=True)

    is_image = source.suffix.lower() in IMAGE_EXTENSIONS
    vram = check_vram()
    log.info("=" * 60)
    log.info("AiLip 2K Lipsync Pipeline")
    log.info("  Source  : %s", source)
    log.info("  Audio   : %s", audio)
    log.info("  Output  : %s", output)
    log.info("  Model   : %s", args.model)
    log.info("  GPU     : %d (%.1f GB free VRAM)", args.gpu_id, vram)
    log.info("  Enhance : %s", not args.no_enhance)
    log.info("  Upscale : %s → %dx%d", not args.no_upscale, args.target_width, args.target_height)
    log.info("=" * 60)

    tmp_dir = tempfile.mkdtemp(prefix="ailip_")
    t_start = time.time()

    try:
        # ── Step 0: Image → Video (if source is an image) ──────────────────
        if is_image:
            log.info("[0/4] Converting image to video loop...")
            tmp_source_video = os.path.join(tmp_dir, "source_loop.mp4")
            image_to_video(str(source), str(audio), tmp_source_video)
            working_video = tmp_source_video
        else:
            working_video = str(source)

        # ── Step 1: Lipsync ────────────────────────────────────────────────
        log.info("[1/4] Running lipsync...")
        lipsync_out = os.path.join(tmp_dir, "lipsync.mp4")
        run_lipsync(
            video_path=working_video,
            audio_path=str(audio),
            output_path=lipsync_out,
            model=args.model,
            gpu_id=args.gpu_id,
            guidance_scale=args.guidance_scale,
            seed=args.seed,
        )

        current = lipsync_out

        # ── Step 2: Face Enhancement ───────────────────────────────────────
        if not args.no_enhance:
            log.info("[2/4] Running CodeFormer face enhancement...")
            enhanced_out = os.path.join(tmp_dir, "enhanced.mp4")
            run_enhance(
                video_path=current,
                output_path=enhanced_out,
                gpu_id=args.gpu_id,
                fidelity_weight=args.fidelity,
            )
            current = enhanced_out
        else:
            log.info("[2/4] Skipping face enhancement.")

        # ── Step 3: 2K Upscale ─────────────────────────────────────────────
        if not args.no_upscale:
            log.info("[3/4] Running Real-ESRGAN 2K upscale...")
            upscaled_out = os.path.join(tmp_dir, "upscaled.mp4")
            run_upscale(
                video_path=current,
                output_path=upscaled_out,
                target_w=args.target_width,
                target_h=args.target_height,
                gpu_id=args.gpu_id,
                model_name=args.esrgan_model,
                face_enhance=False,  # CodeFormer already ran
                tile=args.tile,
            )
            current = upscaled_out
        else:
            log.info("[3/4] Skipping upscale.")

        # ── Step 4: Audio Merge ────────────────────────────────────────────
        log.info("[4/4] Merging audio into final video...")
        merge_audio(
            video_path=current,
            audio_path=str(audio),
            output_path=str(output),
        )

        elapsed = time.time() - t_start
        log.info("=" * 60)
        log.info("Done in %.1f seconds!", elapsed)
        log.info("Output: %s", output.resolve())
        log.info("=" * 60)

    except Exception as e:
        log.error("Pipeline failed: %s", e)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            log.info("Temp files kept at: %s", tmp_dir)


if __name__ == "__main__":
    main()
