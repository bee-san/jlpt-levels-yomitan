from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(b"".join(canonical_bytes(record) for record in records))
    os.replace(temporary, path)


class AcquisitionError(RuntimeError):
    pass


class CachedFetcher:
    def __init__(self, cache_dir: Path, user_agent: str, minimum_delay_ms: int = 1000, timeout_seconds: int = 30, retries: int = 3, sleep: Callable[[float], None] = time.sleep) -> None:
        if not user_agent or user_agent.startswith(("Python-urllib/", "python-requests/")):
            raise ValueError("a descriptive User-Agent is required")
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.minimum_delay = minimum_delay_ms / 1000
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.sleep = sleep
        self._last_request_at: float | None = None

    def get(self, url: str, *, max_bytes: int, offline: bool = False) -> tuple[bytes, bool]:
        key = sha256_bytes(url.encode("utf-8"))
        path = self.cache_dir / f"{key}.bin"
        if path.is_file():
            data = path.read_bytes()
            if len(data) > max_bytes:
                raise AcquisitionError("cached response exceeds maxBytes")
            return data, True
        if offline:
            raise AcquisitionError(f"offline cache miss: {key}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(self.retries + 1):
            if self._last_request_at is not None:
                self.sleep(max(0.0, self.minimum_delay - (time.monotonic() - self._last_request_at)))
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip"})
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) > max_bytes:
                        raise AcquisitionError("response Content-Length exceeds maxBytes")
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise AcquisitionError("response exceeds maxBytes")
                    encoding = response.headers.get("Content-Encoding", "").lower()
                    if encoding == "gzip":
                        try:
                            data = gzip.decompress(data)
                        except (OSError, EOFError) as error:
                            raise AcquisitionError("invalid gzip response") from error
                        if len(data) > max_bytes:
                            raise AcquisitionError("decompressed response exceeds maxBytes")
                    elif encoding:
                        raise AcquisitionError(f"unsupported Content-Encoding: {encoding}")
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                    raise AcquisitionError(f"HTTP {error.code} fetching source") from error
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(30.0, 2.0 ** attempt + random.random())
                self.sleep(delay)
                continue
            except (OSError, urllib.error.URLError) as error:
                if attempt == self.retries:
                    raise AcquisitionError("source request failed") from error
                self.sleep(min(30.0, 2.0 ** attempt + random.random()))
                continue
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
            return data, False
        raise AssertionError("unreachable")
