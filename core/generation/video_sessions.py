"""Persistent video continuation sessions.

Sessions live under output/videos, which is ignored by git. They let JoyBoy
continue a generated video after a restart without putting generated assets in
the public repository.
"""

from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Any

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field


VIDEO_OUTPUT_DIR = Path("output") / "videos"
VIDEO_SESSION_DIR = VIDEO_OUTPUT_DIR / "sessions"
VIDEO_KEYFRAME_DIR = VIDEO_OUTPUT_DIR / "keyframes"
VIDEO_SESSION_SCHEMA = 2
VIDEO_IMPORT_DIR = VIDEO_OUTPUT_DIR / "imports"

DEFAULT_VIDEO_ANALYSIS_MODEL = os.environ.get(
    "JOYBOY_VIDEO_ANALYSIS_MODEL",
    "qwen3-vl:32b-instruct-q8_0",
).strip()


class VideoAnalysisPayload(BaseModel):
    scene: str = Field(default="")
    subjects: str = Field(default="")
    camera: str = Field(default="")
    motion: str = Field(default="")
    last_frame_state: str = Field(default="")
    continuity_prompt: str = Field(default="")
    audio_prompt: str = Field(default="")


def _safe_session_id(value: str | None) -> str:
    raw = str(value or "").strip()
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw)


def _ensure_dirs() -> None:
    VIDEO_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_IMPORT_DIR.mkdir(parents=True, exist_ok=True)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _session_path(session_id: str) -> Path:
    return VIDEO_SESSION_DIR / f"{_safe_session_id(session_id)}.json"


def frame_to_pil(frame: Any) -> Image.Image | None:
    """Convert a generated frame into a RGB PIL image."""
    if frame is None:
        return None
    if isinstance(frame, Image.Image):
        return frame.convert("RGB")
    try:
        if hasattr(frame, "cpu"):
            frame = frame.cpu().numpy()
        if isinstance(frame, np.ndarray):
            arr = frame
            if arr.dtype != np.uint8:
                arr = (arr * 255 if arr.max() <= 1.0 else arr).clip(0, 255).astype(np.uint8)
            if arr.ndim == 3 and arr.shape[0] in (3, 4):
                arr = np.transpose(arr, (1, 2, 0))
            return Image.fromarray(arr[:, :, :3]).convert("RGB")
        return Image.fromarray(np.array(frame)).convert("RGB")
    except Exception:
        return None


def _save_preview_image(frame: Any, path: Path, *, max_size: int = 320) -> str | None:
    image = frame_to_pil(frame)
    if image is None:
        return None
    image.thumbnail((max_size, max_size), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return str(path)


def _image_data_url(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        raw = Path(path).read_bytes()
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return ""


def _select_keyframe_indices(total_frames: int, max_count: int = 5) -> list[int]:
    if total_frames <= 0:
        return []
    count = min(max_count, total_frames)
    if count == 1:
        return [total_frames - 1]
    return sorted({round(i * (total_frames - 1) / (count - 1)) for i in range(count)})


def save_video_session(session: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    session_id = _safe_session_id(session.get("id")) or f"vid_{uuid.uuid4().hex[:12]}"
    session = {**session, "id": session_id, "schema": VIDEO_SESSION_SCHEMA}
    _session_path(session_id).write_text(
        json.dumps(_json_safe(session), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return session


def load_video_session(session_id: str | None) -> dict[str, Any] | None:
    safe_id = _safe_session_id(session_id)
    if not safe_id:
        return None
    path = _session_path(safe_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[VIDEO_SESSION] Read skipped for {safe_id}: {exc}")
        return None


def find_latest_video_session(chat_id: str | None = None) -> dict[str, Any] | None:
    _ensure_dirs()
    candidates = sorted(VIDEO_SESSION_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if chat_id and data.get("chat_id") != chat_id:
            continue
        return data if isinstance(data, dict) else None
    return None


def create_video_session(
    *,
    video_path: str | Path,
    frames: list[Any],
    prompt: str,
    final_prompt: str,
    model_id: str,
    model_name: str,
    fps: int,
    chat_id: str | None,
    video_format: str,
    width: int | None = None,
    height: int | None = None,
    source_session_id: str | None = None,
    anchor_frame_index: int | None = None,
    analysis_summary: dict[str, Any] | None = None,
    continuation_prompt: str = "",
    audio_engine: str = "auto",
    audio_prompt: str = "",
    inherited_keyframes: list[dict[str, Any]] | None = None,
    frame_index_offset: int = 0,
) -> dict[str, Any]:
    """Persist a generated video session and keyframe thumbnails."""
    _ensure_dirs()
    session_id = f"vid_{uuid.uuid4().hex[:12]}"
    session_keyframe_dir = VIDEO_KEYFRAME_DIR / session_id
    frame_count = len(frames or [])

    keyframes: list[dict[str, Any]] = []
    for frame in inherited_keyframes or []:
        if not isinstance(frame, dict):
            continue
        keyframes.append({
            "index": int(frame.get("index", 0) or 0),
            "time_sec": frame.get("time_sec"),
            "path": frame.get("path"),
        })

    for index in _select_keyframe_indices(frame_count):
        image_path = session_keyframe_dir / f"frame_{index:05d}.png"
        saved = _save_preview_image(frames[index], image_path)
        if saved:
            absolute_index = int(frame_index_offset or 0) + int(index)
            keyframes.append({
                "index": absolute_index,
                "time_sec": round(absolute_index / fps, 3) if fps else None,
                "path": saved,
            })

    last_frame_path = None
    if frame_count:
        last_frame_path = _save_preview_image(
            frames[-1],
            session_keyframe_dir / "last_frame.png",
            max_size=768,
        )

    session = {
        "id": session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video_path": str(video_path),
        "format": video_format,
        "chat_id": chat_id,
        "model_id": model_id,
        "model_name": model_name,
        "prompt": prompt,
        "final_prompt": final_prompt,
        "fps": int(fps or 0),
        "frames": int(frame_index_offset or 0) + frame_count,
        "duration_sec": round((int(frame_index_offset or 0) + frame_count) / fps, 3) if fps else None,
        "width": width,
        "height": height,
        "last_frame_path": last_frame_path,
        "keyframes": keyframes,
        "source_session_id": source_session_id,
        "anchor_frame_index": anchor_frame_index,
        "continuation_prompt": continuation_prompt,
        "analysis_summary": analysis_summary or {},
        "audio_engine": audio_engine,
        "audio_prompt": audio_prompt,
    }
    return save_video_session(session)


def _probe_video_duration(video_path: str | Path) -> float | None:
    """Return duration in seconds using ffmpeg stderr metadata when available."""
    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", str(video_path)],
            capture_output=True,
            timeout=20,
        )
        output = (result.stderr or b"").decode(errors="replace")
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception as exc:
        print(f"[VIDEO_SESSION] duration probe skipped: {exc}")
        return None


def _probe_video_size(video_path: str | Path) -> tuple[int, int] | None:
    """Return the first video stream size using ffmpeg stderr metadata."""
    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", str(video_path)],
            capture_output=True,
            timeout=20,
        )
        output = (result.stderr or b"").decode(errors="replace")
        match = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", output)
        if not match:
            return None
        width, height = match.groups()
        return int(width), int(height)
    except Exception as exc:
        print(f"[VIDEO_SESSION] size probe skipped: {exc}")
        return None


def _probe_video_frame_stats(video_path: str | Path) -> tuple[int | None, float | None]:
    """Return exact-ish frame count and FPS using OpenCV when available."""
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None, None
        try:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or None
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
            return frame_count, fps
        finally:
            cap.release()
    except Exception as exc:
        print(f"[VIDEO_SESSION] frame stats probe skipped: {exc}")
        return None, None


def _concat_output_is_valid(
    source_path: str | Path,
    segment_path: str | Path,
    output_path: str | Path,
) -> bool:
    source_duration = _probe_video_duration(source_path) or 0.0
    segment_duration = _probe_video_duration(segment_path) or 0.0
    output_duration = _probe_video_duration(output_path) or 0.0
    if source_duration > 0 and segment_duration > 0 and output_duration <= 0:
        print(
            "[VIDEO_SESSION] concat rejected: output duration unavailable "
            f"(source={source_duration:.2f}s segment={segment_duration:.2f}s)"
        )
        return False
    if source_duration <= 0 or segment_duration <= 0:
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0

    expected_min = source_duration + max(0.5, segment_duration * 0.65)
    if output_duration >= expected_min:
        return True

    print(
        "[VIDEO_SESSION] concat rejected: "
        f"source={source_duration:.2f}s segment={segment_duration:.2f}s output={output_duration:.2f}s"
    )
    return False


def _extract_last_video_frame_precise(video_path: str | Path, output_path: Path) -> bool:
    """Extract the real decoded final frame, not a timestamp near the end."""
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False
        try:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            frame = None

            if frame_count > 0:
                for frame_index in range(frame_count - 1, max(-1, frame_count - 30), -1):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    ok, candidate = cap.read()
                    if ok and candidate is not None:
                        frame = candidate
                        break
            else:
                while True:
                    ok, candidate = cap.read()
                    if not ok:
                        break
                    frame = candidate

            if frame is None:
                return False

            output_path.parent.mkdir(parents=True, exist_ok=True)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            Image.fromarray(rgb).convert("RGB").save(output_path, "PNG")
            return output_path.exists()
        finally:
            cap.release()
    except Exception as exc:
        print(f"[VIDEO_SESSION] precise last frame extract skipped: {exc}")
        return False


def _extract_video_frame(video_path: str | Path, output_path: Path, *, at_time: float | None = None, last: bool = False) -> bool:
    try:
        import imageio_ffmpeg

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if last:
            if _extract_last_video_frame_precise(video_path, output_path):
                return True
            cmd = [
                ffmpeg_path,
                "-y",
                "-sseof",
                "-2",
                "-i",
                str(video_path),
                "-update",
                "1",
                "-q:v",
                "2",
                str(output_path),
            ]
        else:
            cmd = [
                ffmpeg_path,
                "-y",
                "-ss",
                str(max(0.0, float(at_time or 0))),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                str(output_path),
            ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return result.returncode == 0 and output_path.exists()
    except Exception as exc:
        print(f"[VIDEO_SESSION] frame extract skipped: {exc}")
        return False


def create_video_source_session(
    *,
    video_path: str | Path,
    prompt: str = "",
    model_id: str = "external-video",
    model_name: str = "Vidéo importée",
    fps: int = 24,
    chat_id: str | None = None,
    video_format: str = "mp4",
) -> dict[str, Any]:
    """Persist an uploaded video as a continuation-ready source session."""
    _ensure_dirs()
    session_id = f"vid_{uuid.uuid4().hex[:12]}"
    source = Path(video_path)
    suffix = source.suffix.lower() or f".{video_format or 'mp4'}"
    imported_path = VIDEO_IMPORT_DIR / f"{session_id}{suffix}"
    shutil.copyfile(source, imported_path)

    duration = _probe_video_duration(imported_path) or 0.0
    source_size = _probe_video_size(imported_path)
    probed_frame_count, probed_fps = _probe_video_frame_stats(imported_path)
    effective_fps = int(round(probed_fps or fps or 24)) or 24
    frame_count = probed_frame_count or (max(1, int(round(duration * effective_fps))) if duration else 0)
    last_frame_index = max(0, int(frame_count or 1) - 1)
    session_keyframe_dir = VIDEO_KEYFRAME_DIR / session_id

    keyframes: list[dict[str, Any]] = []
    if duration > 0:
        sample_count = min(5, max(1, int(duration)))
        for idx in range(sample_count):
            time_sec = 0.0 if sample_count == 1 else (duration * idx / sample_count)
            frame_index = min(last_frame_index, int(round(time_sec * effective_fps)))
            image_path = session_keyframe_dir / f"frame_{frame_index:05d}.png"
            if _extract_video_frame(imported_path, image_path, at_time=time_sec):
                keyframes.append({
                    "index": frame_index,
                    "time_sec": round(time_sec, 3),
                    "path": str(image_path),
                })

    last_frame_path = session_keyframe_dir / "last_frame.png"
    saved_last = _extract_video_frame(imported_path, last_frame_path, last=True)
    if saved_last:
        keyframes = [
            frame for frame in keyframes
            if int(frame.get("index", -1) or -1) != last_frame_index
        ]
        keyframes.append({
            "index": last_frame_index,
            "time_sec": round(max(0.0, duration - (1 / effective_fps)), 3) if duration else None,
            "path": str(last_frame_path),
            "is_last": True,
        })

    session = {
        "id": session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video_path": str(imported_path),
        "format": video_format,
        "chat_id": chat_id,
        "model_id": model_id,
        "model_name": model_name,
        "prompt": prompt,
        "final_prompt": prompt,
        "fps": effective_fps,
        "frames": frame_count or len(keyframes),
        "duration_sec": round(duration, 3) if duration else None,
        "width": source_size[0] if source_size else None,
        "height": source_size[1] if source_size else None,
        "last_frame_path": str(last_frame_path) if saved_last else (keyframes[-1]["path"] if keyframes else None),
        "keyframes": keyframes,
        "source_session_id": None,
        "anchor_frame_index": None,
        "continuation_prompt": "",
        "analysis_summary": {},
        "audio_engine": "auto",
        "audio_prompt": prompt,
        "imported": True,
    }
    return save_video_session(session)


def public_video_session(session: dict[str, Any] | None) -> dict[str, Any]:
    if not session:
        return {}
    anchors = []
    frame_count = int(session.get("frames") or 0)
    fps = int(session.get("fps") or 0)
    last_index = max(0, frame_count - 1) if frame_count else None
    last_frame_path = session.get("last_frame_path")
    for frame in session.get("keyframes") or []:
        try:
            index = int(frame.get("index", 0) or 0)
        except (TypeError, ValueError):
            index = 0
        if last_frame_path and last_index is not None and index >= last_index:
            continue
        anchors.append({
            "index": index,
            "timeSec": frame.get("time_sec"),
            "thumbnail": _image_data_url(frame.get("path")),
            "isLast": bool(frame.get("is_last")),
        })
    if last_frame_path:
        anchors.append({
            "index": last_index if last_index is not None else None,
            "timeSec": round(last_index / fps, 3) if last_index is not None and fps else session.get("duration_sec"),
            "thumbnail": _image_data_url(last_frame_path),
            "isLast": True,
        })
    return {
        "videoSessionId": session.get("id"),
        "sourceVideoSessionId": session.get("source_session_id"),
        "canContinue": bool(last_frame_path or anchors),
        "continuationAnchors": anchors,
        "analysisSummary": session.get("analysis_summary") or {},
    }


def get_anchor_image(session: dict[str, Any] | None, anchor_frame_index: int | None = None) -> Image.Image | None:
    if not session:
        return None
    candidates = list(session.get("keyframes") or [])
    frame_count = int(session.get("frames") or 0)
    last_index = max(0, frame_count - 1) if frame_count else None
    last_frame_path = session.get("last_frame_path")
    if last_frame_path and (
        anchor_frame_index is None
        or (last_index is not None and int(anchor_frame_index) >= last_index)
    ):
        try:
            return frame_to_pil(Image.open(last_frame_path))
        except Exception:
            pass
    if anchor_frame_index is not None:
        for frame in candidates:
            if int(frame.get("index", -1)) == int(anchor_frame_index):
                return frame_to_pil(Image.open(frame["path"]))
    if last_frame_path:
        try:
            return frame_to_pil(Image.open(last_frame_path))
        except Exception:
            pass
    if candidates:
        last = candidates[-1]
        try:
            return frame_to_pil(Image.open(last["path"]))
        except Exception:
            pass
    return None


def _encode_frame_for_ollama(image: Image.Image) -> str:
    buf = BytesIO()
    image = image.convert("RGB")
    image.thumbnail((640, 640), Image.LANCZOS)
    image.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _analysis_fallback(session: dict[str, Any] | None, user_prompt: str = "") -> dict[str, Any]:
    final_prompt = (session or {}).get("final_prompt") or (session or {}).get("prompt") or ""
    prompt = user_prompt or final_prompt or "continue the same scene"
    return {
        "scene": final_prompt,
        "subjects": "",
        "camera": "",
        "motion": "",
        "last_frame_state": "",
        "continuity_prompt": build_continuation_prompt(final_prompt, prompt, {}),
        "audio_prompt": prompt,
        "model": "",
        "fallback": True,
    }


def analyze_video_session(
    session: dict[str, Any] | None,
    *,
    user_prompt: str = "",
    model: str | None = None,
    max_frames: int = 5,
) -> dict[str, Any]:
    """Analyze keyframes with a local Ollama vision model when available."""
    if not session:
        return _analysis_fallback(session, user_prompt)

    model_name = (model or DEFAULT_VIDEO_ANALYSIS_MODEL or "").strip()
    frames = []
    for item in (session.get("keyframes") or [])[:max_frames]:
        try:
            frames.append(Image.open(item["path"]).convert("RGB"))
        except Exception:
            continue
    if not frames:
        anchor = get_anchor_image(session)
        if anchor is not None:
            frames.append(anchor)
    if not frames or not model_name:
        return _analysis_fallback(session, user_prompt)

    try:
        from core.ai.text_model_router import call_text_model_structured

        images = [_encode_frame_for_ollama(frame) for frame in frames]
        payload = call_text_model_structured(
            [
                {
                    "role": "system",
                    "content": (
                        "You analyze sparse keyframes from one generated video. "
                        "Return compact JSON for continuing the same shot. "
                        "Describe visible continuity only; do not invent events."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze the scene, subjects, camera, motion, and last frame. "
                        "For visible people, describe stable visual identity cues: face, hair, outfit, body proportions, pose, and crop. "
                        "Build a continuity prompt for the next generated segment. "
                        f"Previous prompt: {session.get('final_prompt') or session.get('prompt') or ''}\n"
                        f"User continuation request: {user_prompt or ''}"
                    ),
                    "images": images,
                },
            ],
            schema_model=VideoAnalysisPayload,
            purpose="image_analysis",
            model=model_name,
            num_predict=420,
            temperature=0.15,
            timeout=120,
        )
        if payload:
            payload["model"] = model_name
            payload["fallback"] = False
            return payload
    except Exception as exc:
        print(f"[VIDEO_SESSION] Video analysis skipped: {exc}")

    fallback = _analysis_fallback(session, user_prompt)
    fallback["model"] = model_name
    return fallback


def build_continuation_prompt(
    previous_prompt: str,
    user_prompt: str = "",
    analysis: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic prompt for natural video continuation."""
    analysis = analysis or {}
    user_direction = (user_prompt or "").strip()
    edit_intent_words = (
        "change face", "change identity", "different person", "new person",
        "older", "younger", "fatter", "thinner", "bigger", "smaller",
        "muscular", "pregnant", "transform", "morph", "modify body",
        "modifier le visage", "changer le visage", "changer la personne",
        "grossir", "maigrir", "plus gros", "plus grosse", "plus mince",
        "musclé", "enceinte", "transforme", "modifier le corps",
    )
    allows_identity_or_body_change = any(word in user_direction.lower() for word in edit_intent_words)
    parts = [
        "Continue the same video naturally from the selected anchor frame.",
        "Keep subject identity, lighting, composition, camera direction, and motion continuity.",
        "Start from the anchor frame exactly: preserve the last visible pose, crop, camera angle, lens feel, and scene layout.",
        (
            "Match the source video look and quality: preserve original exposure, contrast, color grade, sharpness, "
            "grain/noise, compression artifacts, skin texture, camera/lens feel, and detail level. Do not beautify, "
            "upscale, denoise, over-sharpen, relight, color-correct, boost saturation, increase contrast, make more cinematic, "
            "or improve the source unless explicitly requested."
        ),
    ]
    if not allows_identity_or_body_change:
        parts.append(
            "If a human/person is visible, preserve the same face, facial structure, skin tone, hair, body shape, proportions, outfit, and age. "
            "Do not beautify, replace, reshape, slim, enlarge, age, de-age, or redesign the person."
        )
    else:
        parts.append(
            "Preserve any person visually except for the explicit body/face change requested by the user."
        )
    if previous_prompt:
        parts.append(f"Previous video prompt: {previous_prompt.strip()}")
    for key, label in (
        ("scene", "Scene"),
        ("subjects", "Subjects"),
        ("camera", "Camera"),
        ("motion", "Motion"),
        ("last_frame_state", "Anchor frame"),
    ):
        value = str(analysis.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    continuity = str(analysis.get("continuity_prompt") or "").strip()
    if continuity:
        parts.append(f"Continuity direction: {continuity}")
    if user_prompt:
        parts.append(f"New user direction: {user_direction}")
    else:
        parts.append("New user direction: continue the existing action smoothly.")
    parts.append("Avoid jump cuts, sudden subject changes, duplicated limbs, warped faces, and abrupt camera resets.")
    return "\n".join(parts)


def concat_video_segments(source_path: str | Path, new_segment_path: str | Path, *, fps: int | None = None) -> Path | None:
    """Concatenate source and generated continuation into a fresh MP4."""
    source = Path(source_path)
    segment = Path(new_segment_path)
    if not source.exists() or not segment.exists():
        return None
    try:
        if source.resolve() == segment.resolve():
            print("[VIDEO_SESSION] concat skipped: source and segment point to the same file")
            return None
    except Exception:
        pass

    output = segment.with_name(segment.stem + "_continued.mp4")
    try:
        import imageio_ffmpeg
        import subprocess

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        width, height = _probe_video_size(source) or _probe_video_size(segment) or (0, 0)
        if width <= 0 or height <= 0:
            print("[VIDEO_SESSION] concat skipped: unable to probe video size")
            return None
        width -= width % 2
        height -= height % 2
        fps_filter = f",fps={int(fps)}" if fps else ""
        filter_graph = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setpts=PTS-STARTPTS,setsar=1{fps_filter}[v0];"
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setpts=PTS-STARTPTS,setsar=1{fps_filter}[v1];"
            "[v0][v1]concat=n=2:v=1:a=0[v]"
        )
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            str(source),
            "-i",
            str(segment),
            "-filter_complex",
            filter_graph,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode == 0 and output.exists():
            if _concat_output_is_valid(source, segment, output):
                os.replace(output, segment)
                return segment
            output.unlink(missing_ok=True)
        stderr = result.stderr.decode(errors="replace")[-500:]
        print(f"[VIDEO_SESSION] concat filter failed: {stderr}")
    except Exception as exc:
        print(f"[VIDEO_SESSION] concat skipped: {exc}")

    return None


def make_temp_anchor_image(image: Image.Image) -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    image.convert("RGB").save(path)
    return path


__all__ = [
    "DEFAULT_VIDEO_ANALYSIS_MODEL",
    "VIDEO_SESSION_SCHEMA",
    "VideoAnalysisPayload",
    "analyze_video_session",
    "build_continuation_prompt",
    "concat_video_segments",
    "create_video_session",
    "create_video_source_session",
    "find_latest_video_session",
    "frame_to_pil",
    "get_anchor_image",
    "load_video_session",
    "public_video_session",
    "save_video_session",
]
