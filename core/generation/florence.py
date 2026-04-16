"""
Florence-2 Vision Model
Modèle de vision léger et rapide de Microsoft (~500MB)
Remplace BLIP et qwen2.5vl pour les descriptions d'images
"""

import torch
from PIL import Image
import threading

# State
_model = None
_processor = None
_lock = threading.Lock()
_device = None

# Cache multi-entrées — évite de re-analyser la même image pour le même task
# Clé: (image_hash, task_type) → résultat string
_cache = {}
_CACHE_MAX_SIZE = 100


def _image_hash(image):
    """Hash rapide d'une image PIL (sample pixels, pas de hash complet)."""
    import hashlib
    small = image.resize((64, 64)).convert('RGB')
    return hashlib.md5(small.tobytes()).hexdigest()


def _get_device():
    """Détermine le device optimal.

    Florence ~500MB → CUDA si assez de VRAM (tourne AVANT la diffusion,
    pas de conflit avec le UNet). CPU fallback si VRAM < 6GB.
    """
    global _device
    if _device is None:
        if torch.cuda.is_available():
            from core.models import VRAM_GB
            # Florence ~500MB, tourne avant la diffusion → pas de conflit VRAM
            _device = "cuda" if VRAM_GB >= 6 else "cpu"
        else:
            _device = "cpu"
    return _device


def load_florence():
    """Charge Florence-2-base (~500MB, rapide)."""
    global _model, _processor

    with _lock:
        if _model is not None:
            return _model, _processor

        print("[FLORENCE] Chargement Florence-2-base (~500MB)...")

        from transformers import AutoProcessor, AutoModelForCausalLM
        import os
        import sys

        model_id = "microsoft/Florence-2-base"
        device = _get_device()

        try:
            # Mock flash_attn pour éviter l'erreur d'import dans le code custom Florence
            # On doit aussi définir __spec__ sinon le code Florence détecte que c'est un fake
            if "flash_attn" not in sys.modules:
                import types
                from importlib.machinery import ModuleSpec

                fake_flash_attn = types.ModuleType("flash_attn")
                fake_flash_attn.__spec__ = ModuleSpec("flash_attn", None)
                fake_flash_attn.flash_attn_func = None
                fake_flash_attn.flash_attn_varlen_func = None

                fake_interface = types.ModuleType("flash_attn.flash_attn_interface")
                fake_interface.__spec__ = ModuleSpec("flash_attn.flash_attn_interface", None)
                fake_interface.flash_attn_func = None
                fake_interface.flash_attn_varlen_func = None

                sys.modules["flash_attn"] = fake_flash_attn
                sys.modules["flash_attn.flash_attn_interface"] = fake_interface

            _processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

            # Charger avec attn_implementation explicite pour éviter SDPA/flash_attn
            dtype = torch.float16 if device != "cpu" else torch.float32

            # Restore clean register_parameter (may be patched by parallel model loading)
            try:
                from core.models.manager import _restore_register_parameter
                _restore_register_parameter()
            except ImportError:
                pass

            try:
                _model = AutoModelForCausalLM.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    attn_implementation="eager",
                    low_cpu_mem_usage=False,
                )
                # Fix meta tensors (tied weights: lm_head, embed_tokens)
                # Florence custom code peut laisser des poids tied en meta device
                _meta_fixed = 0
                for _pname, _p in list(_model.named_parameters()):
                    if _p.is_meta:
                        _parts = _pname.split('.')
                        _target = _model
                        for _part in _parts[:-1]:
                            _target = getattr(_target, _part)
                        _target._parameters[_parts[-1]] = torch.nn.Parameter(
                            torch.zeros(_p.shape, dtype=_p.dtype, device="cpu"),
                            requires_grad=_p.requires_grad
                        )
                        _meta_fixed += 1
                if _meta_fixed > 0:
                    print(f"[FLORENCE] Fixed {_meta_fixed} meta tensors (tied weights)")
                    _model.tie_weights()
                if device != "cpu":
                    _model = _model.to(device)
            except (NotImplementedError, RuntimeError) as _load_err:
                print(f"[FLORENCE] Primary load failed ({_load_err}), trying device_map...")
                # Fallback: charger directement sur le device
                _model = AutoModelForCausalLM.from_pretrained(
                    model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    attn_implementation="eager",
                    device_map=device,
                    low_cpu_mem_usage=False,
                )

            _model.eval()
            print(f"[FLORENCE] Ready ({device})")
            return _model, _processor

        except Exception as e:
            print(f"[FLORENCE] Erreur chargement: {e}")
            return None, None


def unload_florence():
    """Décharge Florence-2 pour libérer la VRAM."""
    global _model, _processor

    with _lock:
        if _model is not None:
            print("[FLORENCE] Déchargement...")
            del _model
            _model = None
        if _processor is not None:
            del _processor
            _processor = None

        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def is_loaded():
    """True si Florence-2 est chargé en RAM."""
    return _model is not None


def get_ram_mb():
    """RAM utilisée par Florence-2 (~500MB si chargé)."""
    return 500 if _model is not None else 0


def _cache_get(image, task):
    """Vérifie le cache pour un (image_hash, task). Retourne (hit, result)."""
    if image is None:
        return False, None
    img_hash = _image_hash(image)
    key = (img_hash, task)
    if key in _cache:
        print(f"[FLORENCE] Cache hit ({task})")
        return True, _cache[key]
    return False, img_hash


def _cache_set(img_hash, task, result):
    """Stocke un résultat dans le cache. Évicte les plus anciens si plein."""
    if len(_cache) >= _CACHE_MAX_SIZE:
        # Supprimer la plus ancienne entrée (FIFO)
        oldest_key = next(iter(_cache))
        del _cache[oldest_key]
    _cache[(img_hash, task)] = result


def describe_image(image, task="<CAPTION>") -> str:
    """
    Génère une description de l'image avec cache.

    Tasks disponibles:
    - <CAPTION> : Description courte
    - <DETAILED_CAPTION> : Description détaillée
    - <MORE_DETAILED_CAPTION> : Description très détaillée

    Returns:
        Description textuelle de l'image
    """
    if image is None:
        return ""

    # Cache check
    hit, cached = _cache_get(image, task)
    if hit:
        return cached
    img_hash = cached  # _cache_get retourne le hash si miss

    model, processor = load_florence()
    if model is None:
        return ""

    try:
        device = _get_device()

        # Convertir en RGB si nécessaire
        if hasattr(image, 'mode') and image.mode != 'RGB':
            image = image.convert('RGB')

        # Vérifier que l'image est valide (PIL avec dimensions)
        if not hasattr(image, 'size') or image.size[0] == 0 or image.size[1] == 0:
            print("[FLORENCE] Image invalide (pas de dimensions)")
            return ""

        # Préparer l'input - Florence attend float16 sur GPU
        inputs = processor(text=task, images=image, return_tensors="pt")
        # Vérifier pixel_values (peut être None si le processor échoue)
        if inputs.get('pixel_values') is None:
            print("[FLORENCE] pixel_values=None après processing, skip")
            return ""
        model_dtype = next(model.parameters()).dtype
        inputs = {k: v.to(device=device, dtype=model_dtype) if v.is_floating_point() else v.to(device) for k, v in inputs.items()}

        # Générer (use_cache=False : le code custom Florence prepare_inputs_for_generation
        # crash quand past_key_values contient des None — incompatibilité transformers récent)
        with torch.no_grad():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=100,
                num_beams=1,
                do_sample=False,
                use_cache=False,
            )

        # Décoder
        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

        # Parser la réponse (Florence retourne dans un format spécial)
        parsed = processor.post_process_generation(
            generated_text,
            task=task,
            image_size=(image.width, image.height)
        )

        # Extraire le texte
        if isinstance(parsed, dict):
            result = parsed.get(task, "")
        else:
            result = str(parsed)

        result = result.strip()
        if result:
            _cache_set(img_hash, task, result)
        return result

    except Exception as e:
        import traceback
        print(f"[FLORENCE] Erreur: {e}")
        traceback.print_exc()
        return ""


def describe_person_for_nudity(image) -> str:
    """
    Décrit une personne pour enrichir un prompt nudity.
    Réutilise describe_image() avec cache intégré.

    Returns:
        String avec les attributs (ex: "slim body, long hair, standing pose")
    """
    description = describe_image(image, task="<MORE_DETAILED_CAPTION>")
    if description and len(description) < 200:
        print(f"[FLORENCE] Description: {description[:80]}...")
        return description
    return ""


def get_status():
    """Retourne le status du modèle."""
    return {
        "loaded": _model is not None,
        "device": _device if _model else None,
    }
