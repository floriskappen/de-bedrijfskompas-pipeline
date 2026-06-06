"""Lifecycle timestamp sidecars for dataset-output records."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

TIMESTAMPS_DIRNAME = "timestamps"
TIMESTAMP_FIELDS = frozenset({"created_at", "updated_at"})


@dataclass(frozen=True)
class TimestampSidecar:
    created_at: str
    updated_at: str
    content_hash: str


def timestamp_path(out_dir: Path, company_id: str) -> Path:
    return out_dir / TIMESTAMPS_DIRNAME / f"{company_id}.json"


def canonical_record_bytes(record: dict) -> bytes:
    payload = {key: value for key, value in record.items() if key not in TIMESTAMP_FIELDS}
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(record: dict) -> str:
    return hashlib.sha256(canonical_record_bytes(record)).hexdigest()


def load_sidecar(out_dir: Path, company_id: str) -> TimestampSidecar | None:
    path = timestamp_path(out_dir, company_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warning: ignoring malformed timestamp sidecar {path}: {exc}", file=sys.stderr)
        return None
    created_at = payload.get("created_at") if isinstance(payload, dict) else None
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else None
    stored_hash = payload.get("content_hash") if isinstance(payload, dict) else None
    if not all(isinstance(value, str) and value for value in (created_at, updated_at, stored_hash)):
        print(f"warning: ignoring malformed timestamp sidecar {path}", file=sys.stderr)
        return None
    return TimestampSidecar(created_at=created_at, updated_at=updated_at, content_hash=stored_hash)


def write_sidecar(out_dir: Path, company_id: str, sidecar: TimestampSidecar) -> None:
    path = timestamp_path(out_dir, company_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "created_at": sidecar.created_at,
                "updated_at": sidecar.updated_at,
                "content_hash": sidecar.content_hash,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
