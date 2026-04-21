"""
OpenPose skeletons + prompt fallback for pose control.

Priority:
1. Cached skeleton: output/skeletons/{pose}_skeleton.png → ControlNet
2. Reference photo: output/skeletons/{pose}.png → extract with OpenPose → ControlNet
3. Prompt fallback: positive/negative keywords injected into the prompt (no ControlNet)
"""

from pathlib import Path
from PIL import Image
import numpy as np

from core.generation.pose_prompts import (
    POSE_ALIASES as _POSE_ALIASES,
    POSE_PROMPTS as _POSE_PROMPTS,
)

# Directory containing reference photos and cached skeletons
_SKELETONS_DIR = Path("output/skeletons")

# Cache: pose_name → PIL.Image
_skeleton_cache = {}


def _publish_pose_progress(phase: str, step: int = 0, message: str = ""):
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase(phase, step=step, total=100, message=message)
    except Exception:
        pass

def generate_pose_skeleton(pose_name, width, height):
    """Get an OpenPose skeleton image for the given pose.

    Tries:
    1. Cached skeleton file (output/skeletons/{pose}_skeleton.png)
    2. Reference photo (output/skeletons/{pose}.png) → extract with OpenPose → cache

    Returns None if no skeleton image available (caller should use get_pose_prompts() instead).
    """
    _name = _POSE_ALIASES.get(pose_name, pose_name)

    # 1. Memory cache
    if _name in _skeleton_cache:
        _publish_pose_progress("pose_skeleton_ready", 100, "Squelette pose prêt")
        return _skeleton_cache[_name].resize((width, height), Image.BILINEAR)

    # 2. Cached skeleton on disk
    cached_path = _SKELETONS_DIR / f"{_name}_skeleton.png"
    if cached_path.exists():
        _publish_pose_progress("extract_pose_skeleton", 65, "Chargement squelette pose...")
        skeleton = Image.open(cached_path).convert('RGB')
        _skeleton_cache[_name] = skeleton
        print(f"[SKELETON] Loaded cached skeleton: {cached_path.name}")
        _publish_pose_progress("pose_skeleton_ready", 100, "Squelette pose prêt")
        return skeleton.resize((width, height), Image.BILINEAR)

    # 3. Reference photo → extract with OpenPose
    ref_path = _SKELETONS_DIR / f"{_name}.png"
    if not ref_path.exists():
        ref_path = _SKELETONS_DIR / f"{_name}.jpg"
    if ref_path.exists():
        _publish_pose_progress("extract_pose_skeleton", 35, "Extraction squelette OpenPose...")
        skeleton = _extract_skeleton_from_photo(ref_path)
        if skeleton is not None:
            _skeleton_cache[_name] = skeleton
            try:
                cached_path.parent.mkdir(parents=True, exist_ok=True)
                skeleton.save(cached_path)
                print(f"[SKELETON] Cached extracted skeleton: {cached_path.name}")
            except Exception:
                pass
            _publish_pose_progress("pose_skeleton_ready", 100, "Squelette pose prêt")
            return skeleton.resize((width, height), Image.BILINEAR)

    # No skeleton available → caller should use prompt fallback
    _publish_pose_progress("pose_fallback", 100, "Squelette absent, fallback prompt")
    return None


def get_pose_prompts(pose_name):
    """Get (positive, negative) prompt additions for a pose when no skeleton is available.

    Returns:
        (positive_str, negative_str) to inject into the prompt, or (None, None) if unknown pose.
    """
    _name = _POSE_ALIASES.get(pose_name, pose_name)
    prompts = _POSE_PROMPTS.get(_name)
    if prompts is None:
        return None, None
    return prompts


def get_available_poses():
    """List all known pose names (with skeleton images or prompt fallback)."""
    poses = set(_POSE_PROMPTS.keys())
    # Also check for skeleton files that may not have prompt definitions
    if _SKELETONS_DIR.exists():
        for f in _SKELETONS_DIR.glob("*_skeleton.png"):
            poses.add(f.stem.replace("_skeleton", ""))
        for f in _SKELETONS_DIR.glob("*.png"):
            if not f.stem.endswith("_skeleton"):
                poses.add(f.stem)
        for f in _SKELETONS_DIR.glob("*.jpg"):
            poses.add(f.stem)
    return sorted(poses)


def _extract_skeleton_from_photo(photo_path):
    """Run OpenposeDetector on a reference photo to extract skeleton."""
    try:
        from core.generation.body_estimation import load_dwpose, unload_dwpose

        model = load_dwpose()
        if model is None or model == "simple":
            print(f"[SKELETON] OpenposeDetector unavailable, can't extract from {photo_path.name}")
            return None

        photo = Image.open(photo_path).convert('RGB')
        print(f"[SKELETON] Extracting skeleton from {photo_path.name} ({photo.size[0]}x{photo.size[1]})...")
        skeleton = model(photo)
        unload_dwpose()

        if skeleton is not None:
            skeleton = skeleton.convert('RGB') if skeleton.mode != 'RGB' else skeleton
            arr = np.array(skeleton)
            if arr.max() < 10:
                print(f"[SKELETON] Extraction returned blank image, pose not detected")
                return None
            print(f"[SKELETON] Extracted skeleton from {photo_path.name}")
            return skeleton
        return None
    except Exception as e:
        print(f"[SKELETON] Extraction failed for {photo_path.name}: {e}")
        return None
