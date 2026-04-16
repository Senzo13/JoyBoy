"""
Generation state — singleton, exceptions, progress wrappers, context history.
Zero internal dependencies (leaf module).
"""
from pathlib import Path


# Exception pour annulation GPU
class GenerationCancelledException(Exception):
    """Exception levée quand une génération est annulée"""
    pass


# ============================================================
# GENERATION STATE — encapsule toutes les variables globales de génération
# ============================================================

class GenerationState:
    """État centralisé pour la génération d'images et de vidéos."""

    _DEFAULT_VIDEO_PROGRESS = {
        'active': False,
        'step': 0,
        'total_steps': 0,
        'pass': 0,
        'total_passes': 0,
        'phase': '',
        'message': ''
    }

    def __init__(self):
        self.reset()

    def reset(self):
        """Réinitialise tout l'état de génération."""
        # Images
        self.current_image = None
        self.original_image = None
        # Video
        self.last_video_frame = None
        self.last_video_prompt = ""
        self.all_video_frames = []
        self.ltx2_audio = None
        self.ltx2_audio_sr = 24000
        # Preview
        self.current_preview = None
        self.current_preview_step = 0
        self.total_steps = 0
        self.current_phase = "generation"
        self.current_preview_message = ""
        # Video progress
        self.video_progress = self._DEFAULT_VIDEO_PROGRESS.copy()
        # Context history
        self.context_history = []
        # Seed
        self.last_seed = None

    # --- Preview ---

    def get_current_preview(self):
        """Retourne (preview, step, total, phase)."""
        return self.current_preview, self.current_preview_step, self.total_steps, self.current_phase

    def get_current_preview_status(self):
        """Retourne l'etat complet de preview/progression pour le polling UI."""
        return {
            "preview": self.current_preview,
            "step": self.current_preview_step,
            "total": self.total_steps,
            "phase": self.current_phase,
            "message": self.current_preview_message,
        }

    def clear_preview(self):
        """Efface la preview courante."""
        self.current_preview = None
        self.current_preview_step = 0
        self.total_steps = 0
        self.current_phase = "generation"
        self.current_preview_message = ""

    def set_phase(self, phase: str, steps: int = None, message: str = ""):
        """Change la phase de génération (pour le feedback UI)."""
        self.current_phase = phase
        self.current_preview_step = 0
        if steps is not None:
            self.total_steps = steps
        self.current_preview_message = message or ""

    def set_progress_phase(self, phase: str, step: int = 0, total: int = None, message: str = ""):
        """Publie une progression sans preview image (downloads, setup, decode, etc.)."""
        self.current_phase = phase
        self.current_preview_step = max(0, int(step or 0))
        if total is not None:
            self.total_steps = max(0, int(total or 0))
        self.current_preview_message = message or ""

    # --- Video progress ---

    def get_video_progress(self):
        """Retourne une copie de la progression vidéo."""
        return self.video_progress.copy()

    def update_video_progress(self, step=None, total_steps=None, pass_num=None,
                              total_passes=None, phase=None, message=None, active=None):
        """Met à jour la progression de la génération vidéo."""
        if active is not None:
            self.video_progress['active'] = active
        if step is not None:
            self.video_progress['step'] = step
        if total_steps is not None:
            self.video_progress['total_steps'] = total_steps
        if pass_num is not None:
            self.video_progress['pass'] = pass_num
        if total_passes is not None:
            self.video_progress['total_passes'] = total_passes
        if phase is not None:
            self.video_progress['phase'] = phase
        if message is not None:
            self.video_progress['message'] = message

    def clear_video_progress(self):
        """Réinitialise la progression vidéo."""
        self.video_progress = self._DEFAULT_VIDEO_PROGRESS.copy()


# Singleton global
_state = GenerationState()

# Cache d'embeddings SDXL — monkey-patch encode_prompt pour skip text encoders (~3s sur 8GB)
_prompt_embed_cache = {}
_PROMPT_CACHE_MAX = 4

# Historique de contexte max
MAX_HISTORY = 10


# --- Module-level wrappers (backward compat pour les imports existants) ---

def get_video_progress():
    return _state.get_video_progress()

def update_video_progress(step=None, total_steps=None, pass_num=None, total_passes=None, phase=None, message=None, active=None):
    _state.update_video_progress(step=step, total_steps=total_steps, pass_num=pass_num, total_passes=total_passes, phase=phase, message=message, active=active)

def clear_video_progress():
    _state.clear_video_progress()

def get_current_preview():
    return _state.get_current_preview()

def get_current_preview_status():
    return _state.get_current_preview_status()

def clear_preview():
    _state.clear_preview()

def set_phase(phase: str, steps: int = None, message: str = ""):
    _state.set_phase(phase, steps, message=message)

def set_progress_phase(phase: str, step: int = 0, total: int = None, message: str = ""):
    _state.set_progress_phase(phase, step, total, message=message)


# --- Accessor functions ---

def get_current_images():
    """Retourne les images courantes (original, modifie)"""
    return _state.original_image, _state.current_image


def get_video_info():
    """Retourne les infos sur la vidéo en cours"""
    return {
        "total_frames": len(_state.all_video_frames),
        "duration_sec": len(_state.all_video_frames) / 16,
        "can_continue": _state.last_video_frame is not None,
        "last_prompt": _state.last_video_prompt or ""
    }


def reset_video():
    """Reset la vidéo en cours pour en commencer une nouvelle"""
    _state.all_video_frames = []
    _state.last_video_frame = None
    _state.last_video_prompt = ""
    print("[VIDEO] Reset - prêt pour nouvelle vidéo")


def delete_video_for_chat(chat_id: str):
    """Supprime les fichiers vidéo associés à une conversation"""
    if not chat_id:
        return False

    output_dir = Path("output") / "videos"
    deleted = False

    # Chercher et supprimer les fichiers vidéo de cette conversation
    for ext in ["mp4", "gif"]:
        video_path = output_dir / f"video_{chat_id}.{ext}"
        if video_path.exists():
            try:
                video_path.unlink()
                print(f"[VIDEO] Supprimé: {video_path}")
                deleted = True
            except Exception as e:
                print(f"[VIDEO] Erreur suppression {video_path}: {e}")

    return deleted


def get_context_summary():
    """Retourne un resume du contexte actuel"""
    if not _state.context_history:
        return "Pas de contexte"

    summary = []
    for i, h in enumerate(_state.context_history[-5:]):
        summary.append(f"{i+1}. [{h['type']}] {h['prompt'][:40]}...")
    return "\n".join(summary)


def clear_context():
    """Efface l'historique de contexte"""
    _state.context_history = []
    _state.current_image = None
    _state.original_image = None
    return "Contexte effacé"
