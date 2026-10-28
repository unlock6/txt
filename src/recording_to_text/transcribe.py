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


def recognize(source: Path, model=None, language="ko", progress=lambda value: None, speed="normal"):
    source = validate_source(source)
    model = model if model is not None else load_model()
    started = time.monotonic()
    segments, info = transcription_segments(model, source, language=language, speed=speed)
    lines = []
    for segment in segments:
        if segment.text.strip():
            lines.append(segment_record(segment))
        progress(min(99, 100 * segment.end / max(info.duration, 1)))
    if not lines:
        raise ValueError("인식된 말소리가 없습니다. 녹음이 들리는지 확인해 주세요. TXT는 만들지 않았습니다.")
    text, flagged_count = format_transcript(lines)
    return text, lines, flagged_count, time.monotonic() - started


def transcribe(source: Path, model=None, language="ko", progress=lambda value: None, speed="normal"):
    text, _, _, seconds = recognize(source, model, language, progress, speed=speed)
    output = save_result(source, text)
    progress(100)
    return output, seconds


def gui(speed="normal"):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    app = tk.Tk()
    app.title("녹음을 글자로 · PC용")
    app.geometry("780x770")
    app.minsize(720, 740)
    app.option_add("*Font", ("맑은 고딕", 12))
    style = ttk.Style(app)
    style.configure("TButton", font=("맑은 고딕", 13), padding=10)
    frame = ttk.Frame(app, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="녹음 파일을 글자로 바꾸기", font=("맑은 고딕", 21, "bold")).pack(anchor="w")
    ttk.Label(frame, text="파일을 선택하고 ‘글자로 변환’을 누르세요.", padding=(0, 12, 0, 8)).pack(anchor="w")
    model_options = {"큰 모델 · turbo (약 1.6GB)": "turbo", "작은 모델 · small (약 0.5GB)": "small"}
    model_choice = tk.StringVar(value="작은 모델 · small (약 0.5GB)")
    model_row = ttk.Frame(frame)
    model_row.pack(anchor="w", pady=(0, 8))
    ttk.Label(model_row, text="변환 방식  ").pack(side="left")
    model_selector = ttk.Combobox(model_row, textvariable=model_choice,
                                  values=list(model_options), state="readonly", width=28)
    model_selector.pack(side="left")
    speed_choice = tk.StringVar(value=next(label for label, value in SPEED_CHOICES.items() if value == speed))
    speed_row = ttk.Frame(frame)
    speed_row.pack(anchor="w", pady=(0, 8))
    ttk.Label(speed_row, text="처리 속도  ").pack(side="left")
    speed_selector = ttk.Combobox(speed_row, textvariable=speed_choice, values=list(SPEED_CHOICES), state="readonly", width=28)
    speed_selector.pack(side="left")
    ttk.Label(frame, text="빠른 처리는 같은 모델로 여러 구간을 함께 처리합니다.\n인식 결과가 달라질 수 있으니 중요한 내용은 원음과 확인하세요.", foreground="#555555", wraplength=650).pack(anchor="w")
    chosen = tk.StringVar(value="선택된 녹음 파일이 없습니다.")
    status = tk.StringVar(value="준비됨 · 음성 인식은 이 PC에서 처리합니다.")
    ttk.Label(frame, textvariable=chosen, wraplength=650).pack(anchor="w", fill="x", pady=10)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w", pady=10)
    state = {"source": None, "output": None, "model": None, "model_name": None, "requested_model": None, "requested_speed": speed, "busy": False}
    events = queue.Queue()

    def select():
        selected = filedialog.askopenfilename(
            title="녹음 파일 선택", parent=app,
            filetypes=[("녹음 파일", "*.m4a *.mp3 *.wav *.amr *.3gp *.3ga *.aac *.ogg *.flac *.mp4"), ("모든 파일", "*.*")],
        )
        if not selected:
            return
        try:
            state["source"] = validate_source(Path(selected))
        except Exception as exc:
            messagebox.showerror("파일 확인", str(exc), parent=app)
            return
        chosen.set(str(state["source"]))
        status.set("파일을 골랐습니다. ‘글자로 변환’을 누르세요.")
        run_button.configure(state="normal")
        bar["value"] = 0

    def work():
        try:
            if state["model"] is None or state["model_name"] != state["requested_model"]:
                events.put(("status", "음성 인식 준비 중입니다. 잠시 기다려 주세요."))
                state["model"] = None
                gc.collect()
                state["model"] = load_model(state["requested_model"], download=True,
                                             progress=lambda message: events.put(("status", message)))
                state["model_name"] = state["requested_model"]
            events.put(("status", "글자로 바꾸는 중입니다. 창을 열어 두세요."))
            output, seconds = transcribe(state["source"], state["model"],
                                         progress=lambda value: events.put(("progress", value)),
                                         speed=state["requested_speed"])
            events.put(("done", (output, seconds)))
        except Exception as exc:
            events.put(("error", str(exc)))

    def start():
        if state["busy"] or state["source"] is None:
            return
        requested = model_options[model_choice.get()]
        if needs_download(requested):
            size = sum(item["size"] for item in MANIFEST[requested]["files"]) / 1e9
            if not messagebox.askyesno("모델 준비", f"처음 한 번 약 {size:.1f}GB 모델을 내려받습니다.\n인터넷 연결과 저장 공간이 필요합니다.\n녹음 파일은 업로드하지 않습니다.\n계속할까요?", parent=app):
                return
        state["busy"] = True
        state["requested_model"] = model_options[model_choice.get()]
        state["requested_speed"] = SPEED_CHOICES[speed_choice.get()]
        state["output"] = None
        model_selector.configure(state="disabled")
        speed_selector.configure(state="disabled")
        select_button.configure(state="disabled")
        run_button.configure(state="disabled")
        folder_button.configure(state="disabled")
        bar["value"] = 0
        status.set("변환을 시작합니다. 길이에 따라 시간이 걸릴 수 있습니다.")
        threading.Thread(target=work, daemon=True).start()

    def finish():
        state["busy"] = False
        model_selector.configure(state="readonly")
        speed_selector.configure(state="readonly")
        select_button.configure(state="normal")
        run_button.configure(state="normal")

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "status":
                    status.set(value)
                elif kind == "progress":
                    bar["value"] = value
                elif kind == "done":
                    output, seconds = value
                    state["output"] = output
                    finish()
                    folder_button.configure(state="normal")
                    status.set(f"완료 · 약 {seconds:.0f}초\n{output.name}\n녹음 파일과 같은 폴더에 저장했습니다.")
                    messagebox.showinfo("변환 완료", f"TXT를 저장했습니다.\n\n{output}\n\n[확인 필요] 구간을 원래 녹음과 확인해 주세요.\n표시가 없는 부분에도 오류가 있을 수 있습니다.", parent=app)
                elif kind == "error":
                    finish()
                    status.set("변환하지 못했습니다. 아래 안내를 확인해 주세요.")
                    messagebox.showerror("변환 확인", value, parent=app)
        except queue.Empty:
            pass
        app.after(150, poll)

    def close():
        if state["busy"] and not messagebox.askyesno(
            "변환 중", "지금 닫으면 변환이 중단됩니다. 창을 닫을까요?", parent=app
        ):
            return
        app.destroy()

    select_button = ttk.Button(buttons, text="1. 녹음 파일 선택", command=select)
    select_button.pack(side="left", padx=(0, 12))
    run_button = ttk.Button(buttons, text="2. 글자로 변환", command=start, state="disabled")
    run_button.pack(side="left")
    bar = ttk.Progressbar(frame, mode="determinate", maximum=100)
    bar.pack(fill="x", pady=12)
    ttk.Label(frame, textvariable=status, wraplength=650).pack(anchor="w", fill="x")
    folder_button = ttk.Button(frame, text="저장 폴더 열기", state="disabled",
                               command=lambda: os.startfile(str(state["output"].parent)))
    folder_button.pack(anchor="w", pady=12)
    ttk.Label(frame, text="원본 녹음은 유지합니다. 한국어 녹음용입니다.\n잘못 적힌 부분이 있을 수 있으니 중요한 내용은 녹음과 확인하세요.",
              wraplength=650, foreground="#555555").pack(anchor="w", side="bottom")
    app.protocol("WM_DELETE_WINDOW", close)
    poll()
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Local recording-to-TXT with review markers")
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
