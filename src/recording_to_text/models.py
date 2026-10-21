"""Pinned, verified model downloads. Audio is never sent to this downloader."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

MANIFEST = json.loads(Path(__file__).with_name("models.json").read_text(encoding="utf-8"))


def cache_root():
    override = os.environ.get("RECORDING_TO_TEXT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return base / "RecordingToText"


def model_path(name):
    if name not in MANIFEST:
        raise ValueError("지원하지 않는 모델입니다.")
    return cache_root() / ("model-" + name)


def valid_file(path, item):
    try:
        if path.stat().st_size != item["size"]:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest() == item["sha256"]
    except FileNotFoundError:
        return False


def needs_download(name):
    # Fast UI hint only. ensure_model always checks complete SHA-256 hashes.
    path = model_path(name)
    return any(not (path / item["name"]).is_file() or
               (path / item["name"]).stat().st_size != item["size"]
               for item in MANIFEST[name]["files"])


def ensure_model(name, download=False, progress=lambda message: None):
    path = model_path(name)
    spec = MANIFEST[name]
    for item in spec["files"]:
        dest = path / item["name"]
        progress("모델 파일 확인 중 · " + item["name"])
        if valid_file(dest, item):
            continue
        if not download:
            raise RuntimeError("모델이 없거나 손상됐습니다. 인터넷 연결 후 --download로 준비해 주세요.")
        path.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{item['name']}"
        request = urllib.request.Request(url, headers={"User-Agent": "recording-to-text/1.0"})
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path, prefix=".download-", suffix=".part", delete=False) as out:
                temp_path = Path(out.name)
                with urllib.request.urlopen(request, timeout=60) as response:
                    total = 0
                    last_mb = -1
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > item["size"]:
                            raise ValueError("모델 파일 크기가 일치하지 않습니다.")
                        out.write(block)
                        mb = total // (1024 * 1024)
                        if mb // 10 != last_mb // 10:
                            progress(f"モデル取得中 · {item['name']} {mb} / {item['size'] // (1024 * 1024)} MB")
                            last_mb = mb
            if not valid_file(temp_path, item):
                raise ValueError("모델 파일 검증에 실패했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.")
            os.replace(temp_path, dest)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return path
