"""Small helpers for gallery sidecar metadata.

Each generated media file can have a sibling ``.json`` file with the same
stem. The gallery uses this to show the model and prompt without guessing from
filenames.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(v) for v in value]
    return str(value)


def save_gallery_metadata(asset_path: str | Path, **metadata: Any) -> Path | None:
    """Write a sibling metadata JSON for a generated image/video.

    Failures are intentionally non-fatal: generation should never fail just
    because the gallery metadata could not be written.
    """
    try:
        path = Path(asset_path)
        sidecar = path.with_suffix(".json")
        data = {
            "schema": 1,
            "asset_name": path.name,
            "asset_type": metadata.pop("asset_type", None) or path.suffix.lstrip(".").lower(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            **metadata,
        }
        sidecar.write_text(json.dumps(_safe_json(data), ensure_ascii=False, indent=2), encoding="utf-8")
        return sidecar
    except Exception as exc:
        print(f"[GALLERY] Metadata save skipped: {exc}")
        return None


def load_gallery_metadata(asset_path: str | Path) -> dict[str, Any]:
    """Read sibling metadata JSON if present."""
    try:
        sidecar = Path(asset_path).with_suffix(".json")
        if not sidecar.exists():
            return {}
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[GALLERY] Metadata read skipped for {asset_path}: {exc}")
        return {}
