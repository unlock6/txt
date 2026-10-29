"""Keep review examples on the local PC for later evaluation or training."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid


def collection_dir():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache'))
    return base / 'RecordingToText' / 'review-examples'


def _copy_verified(source: Path, target: Path) -> dict:
    before = source.stat()
    digest = hashlib.sha256()
    with source.open('rb') as reader, target.open('xb') as writer:
        while True:
            block = reader.read(1024 * 1024)
            if not block:
                break
            writer.write(block)
            digest.update(block)
        writer.flush()
        os.fsync(writer.fileno())
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError('자료를 복사하는 동안 원본 파일이 변경되었습니다.')
    return {'file': target.name, 'size': before.st_size, 'sha256': digest.hexdigest()}


def collect_example(audio: Path, transcript: Path, corrected: Path, *, root=None) -> Path:
    """Save a self-contained example; never publish incomplete or overwrite old data."""
    root = Path(root) if root is not None else collection_dir()
    for path in (audio, transcript, corrected):
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('학습 자료에 필요한 파일이 없거나 비어 있습니다.')
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.preparing-', dir=root))
    try:
        extension = audio.suffix.lower()
        if extension not in {'.m4a', '.mp3', '.wav', '.amr', '.3gp', '.3ga', '.aac', '.ogg', '.flac', '.mp4'}:
            raise ValueError('지원하지 않는 녹음 형식입니다.')
        entries = {
            'audio': _copy_verified(audio, temporary / ('audio' + extension)),
            'transcript': _copy_verified(transcript, temporary / 'original.txt'),
            'corrected': _copy_verified(corrected, temporary / 'corrected.txt'),
        }
        manifest = {'version': 1, 'purpose': 'reviewed audio and transcript for later evaluation', 'files': entries}
        with (temporary / 'manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        destination = root / uuid.uuid4().hex
        temporary.rename(destination)
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
