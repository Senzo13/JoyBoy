"""
Preview callbacks (TAESD/TAEF1), face detector, dimension adjustment.
Depends on: state.py
"""
from PIL import Image
import numpy as np
import torch

from core.generation.state import _state, GenerationCancelledException

# Non-generation singletons (model cache)
face_cascade = None

# TAESD — Tiny AutoEncoder pour previews ultra-rapides (~2MB vs ~50MB VAE)
_taesd = None
_taesd_loading = False
_taef1 = None
_taef1_loading = False


def make_cancel_callback(cancel_check):
    """
    Crée un callback pour diffusers qui vérifie l'annulation à chaque step.
    cancel_check: callable qui retourne True si la génération doit être annulée
    """
    def callback(pipe, step, timestep, callback_kwargs):
        if cancel_check and cancel_check():
            print(f"[CANCEL] Annulation détectée au step {step}")
            raise GenerationCancelledException("Génération annulée par l'utilisateur")
        return callback_kwargs
    return callback


def _get_taesd():
    """Charge TAESD (Tiny AutoEncoder ~2MB) pour les previews. Lazy load + cache global."""
    global _taesd, _taesd_loading
    if _taesd is not None:
        return _taesd
    if _taesd_loading:
        return None
    _taesd_loading = True
    try:
        from diffusers import AutoencoderTiny
        from core.models import custom_cache
        _taesd = AutoencoderTiny.from_pretrained(
            "madebyollin/taesdxl", torch_dtype=torch.float16, cache_dir=custom_cache
        ).to("cuda" if torch.cuda.is_available() else "cpu").eval()
        print("[TAESD] Ready (~2MB, previews ultra-rapides)")
    except Exception as e:
        print(f"[TAESD] Indisponible: {e}")
        _taesd = None
    _taesd_loading = False
    return _taesd


def _get_taef1():
    """Charge TAEF1 (Tiny AutoEncoder for Flux ~2MB, 16 channels) pour previews Flux. Lazy load."""
    global _taef1, _taef1_loading
    if _taef1 is not None:
        return _taef1
    if _taef1_loading:
        return None
    _taef1_loading = True
    try:
        from diffusers import AutoencoderTiny
        from core.models import custom_cache
        _taef1 = AutoencoderTiny.from_pretrained(
            "madebyollin/taef1", torch_dtype=torch.float16, cache_dir=custom_cache
        ).to("cuda" if torch.cuda.is_available() else "cpu").eval()
        print("[TAEF1] Ready (~2MB, previews Flux ultra-rapides)")
    except Exception as e:
        print(f"[TAEF1] Indisponible: {e}")
        _taef1 = None
    _taef1_loading = False
    return _taef1


def _unpack_flux_latents(latents, height, width):
    """Unpack Flux latents de 3D (batch, seq_len, 64) vers 4D (batch, 16, h, w)."""
    batch_size, num_patches, channels = latents.shape
    # Flux vae_scale_factor = 8, packing 2x2 → latent grid = image_size / 8
    h = int(height) // 8
    w = int(width) // 8
    latents = latents.view(batch_size, h // 2, w // 2, channels // 4, 2, 2)
    latents = latents.permute(0, 3, 1, 4, 2, 5)
    latents = latents.reshape(batch_size, channels // 4, h, w)
    return latents


def make_preview_callback(cancel_check=None, preview_every=5, target_size=None,
                          image_height=None, image_width=None, uncrop_info=None):
    """
    Crée un callback qui génère des previews pendant la génération.
    Utilise TAESD (~2MB) pour décoder les latents SDXL, TAEF1 (~2MB) pour Flux.
    Utilise pred_original_sample (x0) pour des previews propres.
    image_height/image_width: dimensions pixel pour unpack des latents Flux (3D→4D).
    uncrop_info: dict {crop: (a,b,c,d), base_image: PIL} pour recoller le crop dans l'original.
    """
    import base64
    from io import BytesIO

    _last_x0 = [None]
    _scheduler_patched = [False]

    def _patch_scheduler(pipe):
        """Wrappe le scheduler pour intercepter la prédiction x0 (image propre).

        Gère tous les types de schedulers:
        - DPMSolverMultistep/UniPC: patch convert_model_output() qui calcule x0 en interne
        - FlowMatchEulerDiscrete: calcul manuel x0 = sample - sigma * model_output
        - DDIM/EulerDiscrete: pred_original_sample dans le retour de step()
        """
        if _scheduler_patched[0]:
            return

        scheduler = pipe.scheduler
        sched_name = type(scheduler).__name__

        if hasattr(scheduler, 'convert_model_output'):
            _orig_convert = scheduler.convert_model_output
            def _wrapped_convert(*args, **kwargs):
                x0 = _orig_convert(*args, **kwargs)
                _last_x0[0] = x0
                return x0
            scheduler.convert_model_output = _wrapped_convert

        elif 'FlowMatch' in sched_name:
            _orig_step = scheduler.step
            def _wrapped_step(model_output, timestep, sample, *args, **kwargs):
                try:
                    idx = scheduler.step_index if scheduler.step_index is not None else 0
                    sigma = scheduler.sigmas[idx]
                    _last_x0[0] = sample - sigma * model_output
                except Exception:
                    pass
                return _orig_step(model_output, timestep, sample, *args, **kwargs)
            scheduler.step = _wrapped_step

        else:
            _orig_step = scheduler.step
            def _wrapped_step(*args, **kwargs):
                output = _orig_step(*args, **kwargs)
                if hasattr(output, 'pred_original_sample') and output.pred_original_sample is not None:
                    _last_x0[0] = output.pred_original_sample
                return output
            scheduler.step = _wrapped_step

        _scheduler_patched[0] = True

    def callback(pipe, step, timestep, callback_kwargs):
        if cancel_check and cancel_check():
            print(f"[CANCEL] Annulation détectée au step {step}")
            raise GenerationCancelledException("Génération annulée par l'utilisateur")

        _patch_scheduler(pipe)

        if step == 1 or (step > 0 and step % preview_every == 0):
            try:
                latents = callback_kwargs.get("latents")
                if latents is not None:
                    with torch.no_grad():
                        latents_to_decode = _last_x0[0] if _last_x0[0] is not None else latents

                        # Flux latents: packed 3D (batch, seq_len, 64) → unpack to 4D
                        is_flux_latent = latents_to_decode.dim() == 3
                        if is_flux_latent and image_height and image_width:
                            latents_to_decode = _unpack_flux_latents(latents_to_decode, image_height, image_width)

                        latent_channels = latents_to_decode.shape[1] if latents_to_decode.dim() == 4 else 0

                        if latent_channels == 16:
                            # TAEF1 : décodeur Flux ~2MB, 16 channels
                            taef1 = _get_taef1()
                            if taef1 is not None:
                                scaling = getattr(taef1.config, 'scaling_factor', 1.0)
                                shift = getattr(taef1.config, 'shift_factor', 0.0)
                                lat = (latents_to_decode.to(dtype=taef1.dtype, device=taef1.device) - shift) / scaling
                                decoded = taef1.decode(lat, return_dict=False)[0]
                            else:
                                decoded = None
                        elif latent_channels == 4:
                            # TAESD XL : décodeur SDXL ~2MB, 4 channels
                            taesd = _get_taesd()
                            if taesd is not None:
                                scaling = getattr(taesd.config, 'scaling_factor', 1.0)
                                lat = latents_to_decode.to(dtype=taesd.dtype, device=taesd.device) / scaling
                                decoded = taesd.decode(lat, return_dict=False)[0]
                            elif hasattr(pipe, 'vae'):
                                # Fallback: gros VAE (lent, taille réduite)
                                scaling = getattr(pipe.vae.config, 'scaling_factor', 0.18215)
                                lat = latents_to_decode / scaling
                                _, c, lh, lw = lat.shape
                                th, tw = max(lh // 2, 8), max(lw // 2, 8)
                                lat = torch.nn.functional.interpolate(lat, size=(th, tw), mode='bilinear', align_corners=False)
                                decoded = pipe.vae.decode(lat, return_dict=False)[0]
                            else:
                                decoded = None
                        else:
                            decoded = None

                        if decoded is not None:
                            # Convertir en image PIL
                            decoded = (decoded / 2 + 0.5).clamp(0, 1)
                            decoded = decoded.cpu().permute(0, 2, 3, 1).float().numpy()[0]
                            decoded = (decoded * 255).round().astype("uint8")
                            image = Image.fromarray(decoded)

                            # Uncrop: recoller la preview dans l'image originale
                            if uncrop_info is not None:
                                _uc = uncrop_info
                                _a, _b, _c, _d = _uc['crop']
                                _pw, _ph = _d - _c, _b - _a
                                image = image.resize((_pw, _ph), Image.LANCZOS)
                                _base = _uc['base_image'].copy()
                                _base.paste(image, (_c, _a))
                                image = _base

                            if target_size:
                                image = image.resize(target_size, Image.LANCZOS)
                            else:
                                image.thumbnail((256, 256), Image.LANCZOS)

                            buffer = BytesIO()
                            image.save(buffer, format="JPEG", quality=60)
                            _state.current_preview = base64.b64encode(buffer.getvalue()).decode('utf-8')

                        _state.current_preview_step = step + 1
                        source = "x0" if _last_x0[0] is not None else "noisy"
                        print(f"[PREVIEW] Step {step + 1}/{_state.total_steps} ({source})")
            except Exception as e:
                _state.current_preview_step = step + 1
                print(f"[PREVIEW] Step {step + 1}/{_state.total_steps} (sans image: {e})")
        else:
            _state.current_preview_step = step + 1

        return callback_kwargs

    return callback


def load_face_detector():
    """Charge le detecteur de visage OpenCV"""
    global face_cascade
    import cv2
    if face_cascade is None:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
    return face_cascade


def adjust_to_multiple_of_8(image: Image.Image) -> Image.Image:
    """Ajuste aux multiples de 8"""
    w, h = image.size
    new_w = (w // 8) * 8
    new_h = (h // 8) * 8
    if new_w != w or new_h != h:
        image = image.resize((new_w, new_h), Image.LANCZOS)
    return image
