"""Optional local batching; ordinary callers retain the original algorithm."""
SPEED_CHOICES = {
    "기본 처리 (기존 방식)": "normal",
    "빠른 처리 (묶음 처리)": "fast",
}


def transcription_segments(model, source, language="ko", speed="normal"):
    if speed not in {"normal", "fast"}:
        raise ValueError("처리 속도는 normal 또는 fast여야 합니다.")
    options = dict(language=language, task="transcribe", beam_size=5,
                   vad_filter=True, condition_on_previous_text=False,
                   word_timestamps=True)
    if speed == "normal":
        return model.transcribe(str(source), **options)
    from faster_whisper import BatchedInferencePipeline
    # A new wrapper per file resets timestamp state. Keep beam=5 and word
    # alignment. False is important: the batch API otherwise groups a whole
    # 30-second chunk into one segment, unlike the ordinary transcribe API.
    engine = BatchedInferencePipeline(model=model)
    return engine.transcribe(str(source), batch_size=2,
                             without_timestamps=False, **options)
