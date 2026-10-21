"""Heuristic review flags, not a calibrated correctness or dialect detector."""
import math
import re

REVIEW_VERSION = 'review-v1'
FILLERS = {'네', '예', '아', '어', '음', '응', '오', '그', '뭐', '좀', '에'}


def clock(seconds):
    value = max(0, int(seconds))
    hours, rest = divmod(value, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}' if hours else f'{minutes:02d}:{secs:02d}'


def segment_record(segment):
    words = getattr(segment, 'words', None) or []
    return {'start': float(segment.start), 'end': float(segment.end),
            'text': segment.text.strip(),
            'avg_logprob': getattr(segment, 'avg_logprob', None),
            'no_speech_prob': getattr(segment, 'no_speech_prob', None),
            'compression_ratio': getattr(segment, 'compression_ratio', None),
            'words': [{'start': float(w.start), 'end': float(w.end),
                       'word': w.word, 'probability': float(w.probability)} for w in words]}


def valid_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def review_reasons(record):
    reasons = []
    low_words = []
    for word in record.get('words') or []:
        text = word.get('word', '').strip()
        bare = re.sub(r'[^\w가-힣]', '', text)
        probability = word.get('probability')
        if bare and bare not in FILLERS and valid_number(probability) and probability < 0.55:
            low_words.append(word)
    if low_words:
        reasons.append('인식이 불확실한 표현')
    avg = record.get('avg_logprob')
    speech = record.get('no_speech_prob')
    compression = record.get('compression_ratio')
    if valid_number(avg) and avg < -0.75:
        reasons.append('구간 인식이 불확실함')
    if valid_number(speech) and speech > 0.5:
        reasons.append('말소리가 불분명할 수 있음')
    if valid_number(compression) and compression > 2.4:
        reasons.append('반복 표현 확인')
    if not record.get('words') and not valid_number(avg):
        reasons.append('인식 점검 정보 없음')
    return reasons, low_words


def format_transcript(records):
    records = [row for row in records if row['text'].strip()]
    count = sum(bool(review_reasons(row)[0]) for row in records)
    lines = ['음성 변환 결과', f'확인 필요: {count}개 구간',
             '[확인 필요]는 자동 점검 표시입니다. 표시가 없는 부분에도 오류가 있을 수 있습니다.',
             '시각은 원본 녹음의 대략적인 재생 위치입니다. 인식된 표현은 임의로 고치지 않았습니다.', '']
    for row in records:
        reasons, low_words = review_reasons(row)
        span = f"{clock(row['start'])}~{clock(row['end'])}"
        label = f'[확인 필요 {span}]' if reasons else f'[{span}]'
        lines.append(f"{label} {row['text'].strip()}")
        if reasons:
            lines.append('  확인 이유: ' + ', '.join(reasons))
        if low_words:
            phrases = [f"{word['word'].strip()} ({clock(word['start'])})" for word in low_words]
            lines.append('  다시 들을 표현: ' + ', '.join(phrases))
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n', count
