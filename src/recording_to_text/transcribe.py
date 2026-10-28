"""Local transcription app. Run without arguments for the GUI."""
from __future__ import annotations

import argparse
import gc
import os
from pathlib import Path
import queue
import sys
import threading
import time

from .review import format_transcript, segment_record
from .processing_options import SPEED_CHOICES, transcription_segments
from .models import ensure_model, model_path, needs_download, MANIFEST
import tempfile

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
FORMATS = {".m4a", ".mp3", ".wav", ".amr", ".3gp", ".3ga", ".aac", ".ogg", ".flac", ".mp4"}


def validate_source(source: Path) -> Path:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in FORMATS:
        raise ValueError("지원하는 녹음 파일을 선택해 주세요. (m4a, mp3, wav, amr 등)")
    if source.stat().st_size == 0:
        raise ValueError("내용이 없는 파일입니다. 다른 녹음 파일을 선택해 주세요.")
    return source


def load_model(name="small", download=False, progress=lambda message: None):
    path = ensure_model(name, download=download, progress=progress)
    from faster_whisper import WhisperModel
    return WhisperModel(str(path), device="cpu", compute_type="int8",
                        cpu_threads=min(4, os.cpu_count() or 2), num_workers=1,
                        local_files_only=True)


def save_result(source: Path, text: str) -> Path:
    """Publish a complete TXT atomically without replacing any existing file."""
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=source.parent, prefix=".recording-to-text-",
                                         suffix=".tmp", mode="w", encoding="utf-8-sig",
                                         newline="\n", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(text.rstrip() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        for index in range(1, 10000):
            suffix = "" if index == 1 else f"-{index}"
            dest = source.with_name(source.stem + ".음성변환" + suffix + ".txt")
            try:
                if os.name == "nt":
                    os.rename(temp_path, dest)  # Windows rename never replaces an existing target.
                else:
                    os.link(temp_path, dest)  # Atomic create-if-absent on POSIX.
                return dest
            except FileExistsError:
                continue
        raise RuntimeError("같은 이름의 결과가 너무 많습니다.")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def recognize(source: Path, model=None, language="ko", progress=lambda value: None, speed="normal", on_segment=lambda row: None):
    source = validate_source(source)
    model = model if model is not None else load_model()
    started = time.monotonic()
    segments, info = transcription_segments(model, source, language=language, speed=speed)
    lines = []
    for segment in segments:
        if segment.text.strip():
            row = segment_record(segment)
            lines.append(row)
            on_segment(row)
        progress(min(99, 100 * segment.end / max(info.duration, 1)))
    if not lines:
        raise ValueError("인식된 말소리가 없습니다. 녹음이 들리는지 확인해 주세요. TXT는 만들지 않았습니다.")
    text, flagged_count = format_transcript(lines)
    return text, lines, flagged_count, time.monotonic() - started


def transcribe(source: Path, model=None, language="ko", progress=lambda value: None, speed="normal", on_segment=lambda row: None):
    text, _, _, seconds = recognize(source, model, language, progress, speed=speed, on_segment=on_segment)
    output = save_result(source, text)
    progress(100)
    return output, seconds


def gui(speed="normal"):
    from .ui import launch_gui
    launch_gui(speed=speed, validate_source=validate_source,
               load_model=lambda name, progress: load_model(name, download=True, progress=progress),
               transcribe=transcribe, speed_choices=SPEED_CHOICES,
               needs_download=needs_download, manifest=MANIFEST)


def main():
    parser = argparse.ArgumentParser(description="Local recording-to-TXT")
    parser.add_argument("audio", nargs="?", type=Path)
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    parser.add_argument("--model", choices=["small", "turbo"], default="small")
    parser.add_argument("--download", action="store_true", help="Allow missing model downloads (audio stays local)")
    parser.add_argument("--check", action="store_true", help="Load the local model without audio")
    parser.add_argument("--speed", choices=["normal", "fast"], default="normal", help="Use optional batch processing")
    args = parser.parse_args()
    if args.check:
        load_model(args.model, download=args.download, progress=print)
        print("OK: CPU int8 model loaded from disk, offline mode enabled.")
    elif args.audio:
        output, seconds = transcribe(args.audio, model=load_model(args.model, download=args.download, progress=print), language=args.language, speed=args.speed)
        print(f"Saved: {output}\nElapsed: {seconds:.1f}s")
    else:
        gui(speed=args.speed)


if __name__ == "__main__":
    main()
