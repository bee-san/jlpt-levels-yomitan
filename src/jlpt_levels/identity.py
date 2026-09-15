from __future__ import annotations

import hashlib
import json


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def lexeme_id(term: str, reading: str) -> str:
    if not term or not reading:
        raise ValueError("term and reading must be non-empty")
    identity = json.dumps([term, reading], ensure_ascii=False, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(identity).hexdigest()
