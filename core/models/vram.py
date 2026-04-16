"""
VRAM Manager - Memory management functions for GPU and system RAM.

Contains:
- VRAM cleanup (clear_vram)
- Pre/post generation VRAM preparation (prepare_for_image_generation, etc.)
- VRAM status reporting (get_vram_status, log_vram_status)
- Model unloading functions for the legacy global pipeline system
"""

import gc
import torch

from core.models.registry import VRAM_GB, IS_MAC


# Flag pour bloquer le prechargement pendant la generation video
video_generating = False

# Global state (legacy pipeline refs used by unload functions)
# These are set/read by models.py which maintains these globals
# This module references them for unload/status functions


def clear_vram(aggressive=False):
    """
    Libere la VRAM et la RAM.

    Args:
        aggressive: Si True, nettoyage profond (plus lent mais libere plus)
    """
    import ctypes

    gc.collect(0)
    gc.collect(1)
    gc.collect(2)

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

        if aggressive:
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.reset_accumulated_memory_stats()

    if aggressive:
        try:
            import sys
            if sys.platform == 'win32':
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetCurrentProcess()
                kernel32.SetProcessWorkingSetSize(handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
        except Exception:
            pass

        try:
            import re
            re.purge()

            import linecache
            linecache.clearcache()
        except Exception:
            pass


def prepare_for_image_generation(unload_segmentation=True, unload_ollama=True):
    """
    Prepare la VRAM avant une generation d'image.
    Decharge les modeles temporaires pour liberer de l'espace pour SDXL.
    """
    actions = []

    if unload_segmentation:
        try:
            from core.segmentation import unload_segmentation_models
            unload_segmentation_models()
            actions.append("segmentation")
        except Exception:
            pass

    if unload_ollama:
        try:
            from core.ollama_service import unload_model, get_loaded_models
            import threading
            loaded = get_loaded_models()
            if loaded:
                def _unload_ollama_bg(models):
                    for model_name in models:
                        try:
                            unload_model(model_name)
                        except Exception:
                            pass
                threading.Thread(target=_unload_ollama_bg, args=(loaded,), daemon=True).start()
                actions.extend(loaded)
        except Exception as e:
            print(f"[VRAM] Erreur dechargement Ollama: {e}")

    if actions:
        print(f"[VRAM] Libere: {', '.join(actions)}")

    clear_vram(aggressive=True)


def after_image_generation(reload_utility=True):
    """
    Apres une generation d'image, recharge les modeles utiles pour la prochaine requete.
    """
    if reload_utility:
        try:
            from core.ollama_service import preload_model
            from config import UTILITY_MODEL
            preload_model(UTILITY_MODEL)
            print(f"[VRAM] Utility AI recharge (pret pour prochain enhance)")
        except Exception:
            pass


def get_vram_status():
    """Retourne l'etat actuel de la VRAM"""
    # Import from models.py to access legacy globals
    from core import models as m

    status = {
        "inpaint_loaded": m.inpaint_pipe is not None,
        "inpaint_model": m.current_model if m.inpaint_pipe else None,
        "text2img_loaded": m.text2img_pipe is not None,
        "text2img_model": m.current_text2img_model if m.text2img_pipe else None,
        "video_loaded": m.video_pipe is not None,
        "outpaint_loaded": m.outpaint_pipe is not None,
        "caption_loaded": m.caption_model is not None,
        "vram_total_gb": VRAM_GB,
        "vram_used_gb": 0,
        "vram_free_gb": 0,
    }

    if torch.cuda.is_available():
        status["vram_used_gb"] = round(torch.cuda.memory_allocated() / 1024**3, 2)
        status["vram_free_gb"] = round((torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1024**3, 2)

    return status


def log_vram_status(context: str = ""):
    """Affiche l'etat VRAM dans les logs"""
    from core.models.registry import VIDEO_MODELS

    status = get_vram_status()
    models_loaded = []

    from core import models as m

    if status["inpaint_loaded"]:
        model_name = status['inpaint_model']
        if model_name and '/' in model_name:
            model_name = model_name.split('/')[-1][:20]
        models_loaded.append(f"inpaint ({model_name})")

    if status["text2img_loaded"]:
        model_name = status['text2img_model']
        if model_name and '/' in model_name:
            model_name = model_name.split('/')[-1][:20]
        models_loaded.append(f"text2img ({model_name})")

    if status["video_loaded"]:
        vid_name = VIDEO_MODELS.get(m.current_video_model, {}).get("name", m.current_video_model or "SVD")
        models_loaded.append(f"video ({vid_name})")

    if status["outpaint_loaded"]:
        models_loaded.append("outpaint")

    if status["caption_loaded"]:
        models_loaded.append("BLIP")

    try:
        from core.ollama_service import get_loaded_models
        ollama_models = get_loaded_models()
        if ollama_models:
            for om in ollama_models:
                models_loaded.append(f"{om}")
    except Exception:
        pass

    print(f"\n{'_'*50}")
    print(f"VRAM STATUS | {context}")
    print(f"{'_'*50}")
    print(f"   GPU: {status['vram_used_gb']:.1f}GB / {status['vram_total_gb']:.1f}GB ({status['vram_free_gb']:.1f}GB libre)")

    if models_loaded:
        print(f"   Charges: {', '.join(models_loaded)}")
    else:
        print(f"   Charges: aucun (VRAM libre)")
    print(f"{'_'*50}\n")


def unload_all_image_models():
    """Decharge tous les modeles d'image pour liberer la VRAM"""
    from core import models as m

    unloaded = False

    if m.inpaint_pipe is not None:
        print("[VRAM] Unloading inpaint model...")
        del m.inpaint_pipe
        m.inpaint_pipe = None
        m.current_model = None
        unloaded = True

    if m.text2img_pipe is not None:
        print("[VRAM] Unloading text2img model...")
        del m.text2img_pipe
        m.text2img_pipe = None
        m.current_text2img_model = None
        unloaded = True

    if m.outpaint_pipe is not None:
        print("[VRAM] Unloading outpaint model...")
        del m.outpaint_pipe
        m.outpaint_pipe = None
        unloaded = True

    if m.video_pipe is not None:
        print("[VRAM] Unloading video model...")
        del m.video_pipe
        m.video_pipe = None
        unloaded = True

    if unloaded:
        clear_vram()
        print("[VRAM] All image models unloaded")


def unload_caption_model():
    """Decharge le modele BLIP (caption) pour liberer la VRAM"""
    from core import models as m

    if m.caption_model is not None:
        print("[VRAM] Unloading BLIP caption model...")
        del m.caption_model
        m.caption_model = None

    if m.caption_processor is not None:
        del m.caption_processor
        m.caption_processor = None

    clear_vram()


def unload_zoe_detector():
    """Decharge le detecteur ZoeDepth pour liberer la VRAM"""
    from core import models as m

    if m.zoe_detector is not None:
        print("[VRAM] Unloading ZoeDepth detector...")
        del m.zoe_detector
        m.zoe_detector = None
        clear_vram()


def unload_outpaint_pipeline():
    """Decharge le pipeline d'outpainting (ControlNets) pour liberer la VRAM"""
    from core import models as m

    if m.outpaint_pipe is not None:
        print("[VRAM] Unloading outpaint pipeline...")
        del m.outpaint_pipe
        m.outpaint_pipe = None
        clear_vram()


def unload_video_model():
    """Decharge le modele video SVD (Stable Video Diffusion) pour liberer la VRAM"""
    from core import models as m

    if m.video_pipe is not None:
        print("[VRAM] Unloading video model...")
        del m.video_pipe
        m.video_pipe = None
        clear_vram()


def prepare_for_video_generation():
    """
    Prepare la VRAM avant une generation video.
    Decharge tous les modeles sauf video pour maximiser la VRAM disponible.
    """
    global video_generating
    from core import models as m

    video_generating = True
    actions = []

    if m.inpaint_pipe is not None:
        print("[VRAM] Unloading inpaint for video...")
        del m.inpaint_pipe
        m.inpaint_pipe = None
        actions.append("inpaint")

    if m.text2img_pipe is not None:
        print("[VRAM] Unloading text2img for video...")
        del m.text2img_pipe
        m.text2img_pipe = None
        actions.append("text2img")

    if m.outpaint_pipe is not None:
        print("[VRAM] Unloading outpaint for video...")
        del m.outpaint_pipe
        m.outpaint_pipe = None
        actions.append("outpaint")

    try:
        from core.segmentation import unload_segmentation_models
        unload_segmentation_models()
        actions.append("segmentation")
    except Exception:
        pass

    try:
        from core.ollama_service import unload_model, get_loaded_models
        loaded = get_loaded_models()
        if loaded:
            for model_name in loaded:
                try:
                    unload_model(model_name)
                    actions.append(model_name)
                except Exception:
                    pass
    except Exception:
        pass

    if actions:
        print(f"[VRAM] Libere pour video: {', '.join(actions)}")

    clear_vram(aggressive=True)


def video_generation_done():
    """Appele quand la generation video est terminee pour reactiver le prechargement"""
    global video_generating
    video_generating = False


def is_video_generating():
    """Verifie si une generation video est en cours"""
    return video_generating


def get_current_loaded_models():
    """Retourne un dict decrivant les modeles actuellement charges."""
    from core import models as m

    loaded = {}
    if m.inpaint_pipe is not None:
        loaded["inpaint"] = m.current_model
    if m.text2img_pipe is not None:
        loaded["text2img"] = m.current_text2img_model
    if m.video_pipe is not None:
        loaded["video"] = m.current_video_model
    if m.outpaint_pipe is not None:
        loaded["outpaint"] = True
    if m.caption_model is not None:
        loaded["caption"] = True
    return loaded


def smart_unload_for_vram(needed_gb: float):
    """
    Decharge des modeles intelligemment pour liberer la VRAM necessaire.

    Args:
        needed_gb: Quantite de VRAM a liberer en GB
    """
    if not torch.cuda.is_available():
        return

    free_gb = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1024**3

    if free_gb >= needed_gb:
        return

    # Decharger dans l'ordre: caption, outpaint, text2img, inpaint, video
    unload_order = [
        unload_caption_model,
        unload_zoe_detector,
        unload_outpaint_pipeline,
    ]

    for unload_fn in unload_order:
        unload_fn()
        free_gb = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1024**3
        if free_gb >= needed_gb:
            return
