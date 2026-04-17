"""
Diffuser step callbacks: soft inpaint, Fooocus clamp, adaptive CFG, quality harmonize.
Depends on: state.py, compositing.py, anisotropic.py (lazy)
"""
import numpy as np
import torch

from core.generation.state import _state, GenerationCancelledException, set_phase
from core.generation.compositing import _pixel_composite

# ============================================================
# SOFT INPAINTING — blending latent avec préservation de magnitude
# Basé sur A1111 PR #14208 (CodeHatchling)
# Résout: peau grise/désaturée SDXL, démarcation visible aux bords du masque
# Le lerp linéaire classique réduit la magnitude des vecteurs latents → désaturation.
# Cette méthode interpole direction ET magnitude séparément.
# ============================================================

SOFT_INPAINT_FEATHER_RADIUS = 16   # Rayon Gaussian blur sur le masque (pixels)
SOFT_INPAINT_BLEND_POWER = 1.0     # Contrôle temporel (1.0=équilibré)
SOFT_INPAINT_BLEND_SCALE = 0.5     # Force de préservation (0.5=équilibré)
SOFT_INPAINT_DETAIL = 4.0          # Préservation du contraste (4.0=bon défaut)

FOOOCUS_SHARPNESS = 2.0  # Intensité du filtre anisotropique (Fooocus default)
ADM_SCALER_END = 0.3       # ADM scaling actif les premiers 30% des steps (Fooocus default)
ADM_SMALL_IMAGE_THRESH = 600  # En dessous de 600px (max dim), réduire le scaling ADM
ADM_POS_SCALE = 1.5        # Fooocus default: 1.5x
ADM_NEG_SCALE = 0.8        # Fooocus default: 0.8x

QUALITY_SHARPNESS_RATIO = 1.5  # Ratio netteté gen/orig au-delà duquel on harmonise

COMPOSITE_RADIUS_BRUSH = 32
COMPOSITE_RADIUS_SEG = 48


def _match_latent_tensor(tensor, reference, *, dtype=None):
    """Move callback state tensors onto the live latent tensor device/dtype.

    Diffusers keeps callback kwargs on the active runtime device. Captured
    tensors created before the pipeline call may still be on CPU, which breaks
    macOS/MPS as soon as the callback blends them with live latents.
    """
    if not torch.is_tensor(tensor) or not torch.is_tensor(reference):
        return tensor

    target_dtype = dtype if dtype is not None else reference.dtype
    if tensor.device == reference.device and tensor.dtype == target_dtype:
        return tensor
    return tensor.to(device=reference.device, dtype=target_dtype)


def _match_latent_device(tensor, reference):
    if not torch.is_tensor(tensor) or not torch.is_tensor(reference):
        return tensor
    if tensor.device == reference.device:
        return tensor
    return tensor.to(device=reference.device)


def _magnitude_preserving_blend(orig_latents, gen_latents, blend_t, detail_preservation=4.0):
    """
    Blend latents avec préservation de magnitude.
    blend_t: 0=garder original, 1=utiliser généré (shape [B,1,H,W] broadcast sur 4 channels)
    """
    one_minus_t = 1.0 - blend_t

    # Direction: interpolation linéaire standard
    interp = orig_latents * one_minus_t + gen_latents * blend_t

    # Magnitude actuelle (réduite par le lerp — c'est le problème du gris)
    current_mag = torch.norm(interp, p=2, dim=1, keepdim=True).to(torch.float32) + 1e-5

    # Magnitude désirée: power mean biaisé vers la plus grande
    p = detail_preservation
    t_mag = blend_t[:, :1].to(torch.float32)
    one_minus_t_mag = 1.0 - t_mag

    orig_mag = torch.norm(orig_latents, p=2, dim=1, keepdim=True).to(torch.float32).pow(p) * one_minus_t_mag
    gen_mag = torch.norm(gen_latents, p=2, dim=1, keepdim=True).to(torch.float32).pow(p) * t_mag
    desired_mag = (orig_mag + gen_mag).pow(1.0 / p)

    # Renormaliser le vecteur interpolé à la magnitude désirée
    scale = (desired_mag / current_mag).to(interp.dtype)
    return interp * scale


def make_soft_inpaint_callback(orig_latents, noise, soft_mask_latent,
                                preview_callback=None, cancel_check=None):
    """
    Callback diffusers callback_on_step_end pour soft inpainting.
    Remplace le blend binaire dur du pipeline par un blend smooth dans l'espace latent.

    Args:
        orig_latents: image originale encodée VAE [B,4,H/8,W/8]
        noise: bruit aléatoire pour noiser l'original à chaque step
        soft_mask_latent: masque flou en espace latent [B,1,H/8,W/8] (0=garder, 1=inpaint)
        preview_callback: callback preview TAESD existant à chaîner
    """
    nmask = 1.0 - soft_mask_latent  # 1=garder original, 0=inpaint

    def step_callback(pipe, step_index, timestep, callback_kwargs):
        latents = callback_kwargs["latents"]

        # Annulation
        if cancel_check and cancel_check():
            print(f"[CANCEL] Annulation au step {step_index}")
            raise GenerationCancelledException("Génération annulée par l'utilisateur")

        timesteps = pipe.scheduler.timesteps
        is_last = (step_index >= len(timesteps) - 1)

        if is_last:
            # Dernier step: laisser le résultat du débruiteur intact
            if preview_callback:
                preview_callback(pipe, step_index, timestep, callback_kwargs)
            return callback_kwargs

        # Sigma (niveau de bruit) pour ce timestep
        if hasattr(pipe.scheduler, 'sigmas') and pipe.scheduler.sigmas is not None:
            idx = min(step_index, len(pipe.scheduler.sigmas) - 1)
            sigma = float(pipe.scheduler.sigmas[idx])
        else:
            alphas = pipe.scheduler.alphas_cumprod
            t_val = int(timestep.item()) if hasattr(timestep, 'item') else int(timestep)
            t_idx = min(t_val, len(alphas) - 1)
            alpha = float(alphas[t_idx])
            sigma = ((1 - alpha) / alpha) ** 0.5

        # Masque scalé par sigma: début=liberté débruiteur, fin=préservation original
        # Keep this math in fp32: Apple MPS does not reliably support fp64 ops.
        sigma_t = torch.tensor(sigma, device=latents.device, dtype=torch.float32)
        nmask_step = _match_latent_tensor(nmask, latents, dtype=torch.float32)
        modified_nmask = torch.pow(
            nmask_step,
            (sigma_t ** SOFT_INPAINT_BLEND_POWER) * SOFT_INPAINT_BLEND_SCALE
        ).to(latents.dtype)
        blend_t = 1.0 - modified_nmask  # 0=original, 1=denoised

        # Original bruité au prochain timestep (pour cohérence avec le scheduler)
        next_t = timesteps[step_index + 1]
        next_t_batch = _match_latent_device(next_t.unsqueeze(0), latents)
        orig_step_latents = _match_latent_tensor(orig_latents, latents)
        noise_step = _match_latent_tensor(noise, latents)
        noised_orig = pipe.scheduler.add_noise(
            orig_step_latents, noise_step, next_t_batch
        )
        noised_orig = _match_latent_tensor(noised_orig, latents)

        # Blend avec préservation de magnitude (élimine le gris)
        blended = _magnitude_preserving_blend(
            noised_orig, latents, blend_t, SOFT_INPAINT_DETAIL
        )
        callback_kwargs["latents"] = blended

        # Preview TAESD
        if preview_callback:
            preview_callback(pipe, step_index, timestep, callback_kwargs)

        return callback_kwargs

    return step_callback


def make_fooocus_clamp_callback(orig_latents, noise, mask_latent,
                                 preview_callback=None, cancel_check=None,
                                 seed=None):
    """
    Fooocus-style double blending + anisotropic sharpness.

    Fooocus fait DEUX blends par step:
    1. POST-MODEL (x0 prediction): force non-mask x0 = original clean
       → le scheduler calcule les bons latents pour les zones non-mask
    2. POST-STEP (latents): force non-mask = fill + energy noise frais
       → équivalent au PRE-MODEL blend de Fooocus pour le step suivant

    + Anisotropic: bilateral blur guidé sur epsilon pour lisser le bruit
    tout en préservant les edges (transitions masque/original nettes).

    Fooocus energy noise: un générateur SÉPARÉ (seed+1) produit du bruit
    FRAIS à chaque step, scalé par sigma. Contrairement à réutiliser le
    même tensor de bruit, ceci donne des textures plus naturelles/variées.

    Args:
        orig_latents: image fill encodée VAE [B,4,H/8,W/8]
        noise: bruit (legacy, non utilisé — remplacé par energy noise)
        mask_latent: masque binaire en espace latent [B,1,H/8,W/8] (0=garder, 1=inpaint)
        seed: seed de génération (energy noise utilise seed+1)
    """
    from core.generation.anisotropic import adaptive_anisotropic_filter

    _scheduler_patched = [False]
    _orig_convert = [None]
    _step_progress = [0.0]  # Partagé entre step_callback et le hook scheduler
    _adm_reverted = [False]  # ADM scaling revert flag (une seule fois à 30%)

    # Energy noise generator (Fooocus: separate generator seeded with seed+1)
    # Produces FRESH noise at each step instead of reusing the same tensor.
    # This gives more natural/varied skin textures.
    _energy_seed = ((seed or 0) + 1) % (2**32)
    _energy_gen = torch.Generator(device='cpu').manual_seed(_energy_seed)

    def _patch_scheduler_x0_blend(pipe):
        """Patch convert_model_output pour:
        1. Anisotropic sharpness sur epsilon (bilateral blur guidé par x0)
        2. Forcer x0 = original dans les zones non-mask
        """
        if _scheduler_patched[0]:
            return

        scheduler = pipe.scheduler
        if hasattr(scheduler, 'convert_model_output'):
            _orig_convert[0] = scheduler.convert_model_output

            def _x0_blended_convert(*args, **kwargs):
                model_output = args[0]
                sample = kwargs.get('sample')
                if sample is None and len(args) > 2:
                    sample = args[2]

                # --- Anisotropic sharpness (Fooocus) ---
                # Bilateral blur sur epsilon guidé par x0 approx
                # Progressif: alpha monte avec les steps (plus de sharpness en fin)
                progress = _step_progress[0]
                alpha = 0.001 * FOOOCUS_SHARPNESS * progress
                if alpha > 1e-6 and sample is not None:
                    x0_approx = sample - model_output
                    eps_filtered = adaptive_anisotropic_filter(x=model_output, g=x0_approx)
                    model_output = eps_filtered * alpha + model_output * (1.0 - alpha)
                    # Reconstruire args avec model_output modifié
                    args = (model_output,) + args[1:]

                x0 = _orig_convert[0](*args, **kwargs)
                # Fooocus post-model blend: non-mask x0 = clean original
                _mask = mask_latent.to(device=x0.device, dtype=x0.dtype)
                _orig = orig_latents.to(device=x0.device, dtype=x0.dtype)
                return x0 * _mask + _orig * (1.0 - _mask)

            scheduler.convert_model_output = _x0_blended_convert
            print("[FOOOCUS] Scheduler patched: x0 blend + anisotropic sharpness active")

        _scheduler_patched[0] = True

    def _unpatch_scheduler(pipe):
        """Restaurer le scheduler original après génération."""
        if _orig_convert[0] is not None:
            pipe.scheduler.convert_model_output = _orig_convert[0]
            _orig_convert[0] = None
        _scheduler_patched[0] = False

    def step_callback(pipe, step_index, timestep, callback_kwargs):
        latents = callback_kwargs["latents"]

        # Annulation
        if cancel_check and cancel_check():
            _unpatch_scheduler(pipe)
            raise GenerationCancelledException("Génération annulée par l'utilisateur")

        # Tracking progress pour l'anisotropic sharpness (alpha progressif)
        timesteps = pipe.scheduler.timesteps
        _step_progress[0] = step_index / max(len(timesteps) - 1, 1)

        # ADM temporal gating: revert à la taille réelle après 30% des steps
        # add_time_ids format: [orig_h, orig_w, crop_top, crop_left, target_h, target_w]
        # Concaténé [negative, positive] par le pipeline avant la boucle
        if _step_progress[0] > ADM_SCALER_END and not _adm_reverted[0]:
            time_ids = callback_kwargs.get("add_time_ids")
            if time_ids is not None:
                time_ids = _match_latent_tensor(time_ids, latents)
                actual_h = orig_latents.shape[2] * 8
                actual_w = orig_latents.shape[3] * 8
                time_ids[:, 0] = actual_h
                time_ids[:, 1] = actual_w
                callback_kwargs["add_time_ids"] = time_ids
                _adm_reverted[0] = True
                print(f"[FOOOCUS] ADM scaling reverted to {actual_h}x{actual_w} at step {step_index} ({_step_progress[0]:.0%})")

        # Patch scheduler au premier step (post-model x0 blend + anisotropic)
        _patch_scheduler_x0_blend(pipe)

        is_last = (step_index >= len(timesteps) - 1)

        if not is_last:
            # Post-step clamp (Fooocus pre-model blend for next step)
            # Energy noise: FRESH random noise per step (Fooocus-style)
            # Key insight: generate NEW noise each step instead of reusing the same tensor.
            # This gives more natural/varied skin textures.
            # Use scheduler.add_noise for correct scaling (handles alpha/sigma math).
            next_t = timesteps[step_index + 1]
            orig_step_latents = _match_latent_tensor(orig_latents, latents)
            mask_step_latent = _match_latent_tensor(mask_latent, latents)
            next_t_batch = _match_latent_device(next_t.unsqueeze(0), latents)
            _fresh_noise = torch.randn(
                orig_step_latents.shape, dtype=latents.dtype,
                generator=_energy_gen, device='cpu'
            ).to(latents.device)
            noised_orig = pipe.scheduler.add_noise(
                orig_step_latents, _fresh_noise, next_t_batch
            )
            noised_orig = _match_latent_tensor(noised_orig, latents)
            clamped = noised_orig * (1.0 - mask_step_latent) + latents * mask_step_latent
            callback_kwargs["latents"] = clamped
        else:
            # Dernier step: restaurer le scheduler
            _unpatch_scheduler(pipe)

        # Preview TAESD
        if preview_callback:
            preview_callback(pipe, step_index, timestep, callback_kwargs)

        return callback_kwargs

    return step_callback


def make_adaptive_cfg_callback(base_cfg, mimic_cfg=None, inner_callback=None):
    """Adaptive CFG: réduit le CFG progressivement pour éviter sur-saturation.

    Early steps: base_cfg (fort guidage pour composition).
    Late steps: interpole vers mimic_cfg (guidage plus doux).
    mimic_cfg par défaut = 60% du base_cfg (ex: 5.0 → 3.0).
    JAMAIS en dessous de 2.0 sinon le modèle perd le guidage et produit du vide.
    """
    if mimic_cfg is None:
        mimic_cfg = max(base_cfg * 0.6, 2.0)

    def callback(pipe, step_index, timestep, callback_kwargs):
        total = len(pipe.scheduler.timesteps)
        progress = step_index / max(total - 1, 1)

        # Blend linéaire: CFG diminue avec la progression
        adaptive = base_cfg * (1 - progress) + mimic_cfg * progress
        pipe._guidance_scale = adaptive

        # Chain inner callback (preview + latent clamping)
        if inner_callback:
            return inner_callback(pipe, step_index, timestep, callback_kwargs)
        return callback_kwargs

    return callback


_harmonize_upscaler = None  # Cache Real-ESRGAN GPU FP16 pour harmonize (évite reload)


def _quality_harmonize(result, mask, original, brush_mode=False, composite_radius=None):
    """Harmonise la qualité entre zones générées et originales.

    Compare la netteté (Laplacian variance) des deux zones.
    Si la zone générée est significativement plus nette, upscale+downscale
    les zones originales avec Real-ESRGAN pour harmoniser.
    La zone générée est protégée par le masque.
    """
    from PIL import Image
    import cv2

    if mask is None or original is None:
        return result
    if result.size != original.size:
        return result

    result_np = np.array(result)
    mask_np = np.array(mask.convert('L').resize(result.size, Image.BILINEAR))

    # Zones binaires
    gen_zone = mask_np > 127
    orig_zone = mask_np <= 127

    if np.sum(gen_zone) < 100 or np.sum(orig_zone) < 100:
        return result

    # Mesurer la netteté via Laplacian variance (plus haut = plus net)
    gray = cv2.cvtColor(result_np, cv2.COLOR_RGB2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)

    sharp_gen = float(np.var(laplacian[gen_zone]))
    sharp_orig = float(np.var(laplacian[orig_zone]))

    if sharp_orig < 1.0:
        sharp_orig = 1.0  # Éviter division par zéro

    ratio = sharp_gen / sharp_orig
    print(f"[HARMONIZE] Sharpness — generated: {sharp_gen:.0f}, original: {sharp_orig:.0f}, ratio: {ratio:.2f}x")

    # Only harmonize if generated zone is significantly sharper than original
    if ratio < QUALITY_SHARPNESS_RATIO:
        print(f"[HARMONIZE] Skip — ratio {ratio:.2f}x below threshold {QUALITY_SHARPNESS_RATIO}x")
        return result

    # Real-ESRGAN GPU FP16 (~32MB VRAM, rapide)
    global _harmonize_upscaler
    try:
        from utils.compat import _patch_torchvision_compatibility
        _patch_torchvision_compatibility()
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
        import torch
    except ImportError:
        print(f"[HARMONIZE] Skip — Real-ESRGAN unavailable")
        return result

    print(f"[HARMONIZE] Enhancing original zones on GPU FP16 (sharpness ratio {ratio:.2f}x)...")
    set_phase("harmonize", 0)

    try:
        if _harmonize_upscaler is None:
            torch.cuda.empty_cache()
            _net = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            _harmonize_upscaler = RealESRGANer(
                scale=4,
                model_path='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
                model=_net, tile=400, tile_pad=10, pre_pad=0, half=True, gpu_id=0,
            )
            print(f"[HARMONIZE] Real-ESRGAN GPU FP16 chargé (~32MB VRAM)")
        img_bgr = cv2.cvtColor(result_np, cv2.COLOR_RGB2BGR)
        upscaled_bgr, _ = _harmonize_upscaler.enhance(img_bgr, outscale=1)
        upscaled_rgb = cv2.cvtColor(upscaled_bgr, cv2.COLOR_BGR2RGB)

        # Blend : zone générée = inchangée, zones originales = upscalé
        # FIX: arguments were SWAPPED before — Real-ESRGAN was applied to generated
        # zone (porcelain skin!) instead of original zones
        _comp_radius = composite_radius if composite_radius is not None else (COMPOSITE_RADIUS_BRUSH if brush_mode else COMPOSITE_RADIUS_SEG)
        harmonized = _pixel_composite(result_np, upscaled_rgb, mask_np, _comp_radius)
        result = Image.fromarray(harmonized)
        print(f"[HARMONIZE] Done — original zones enhanced (generated zone preserved)")
    except Exception as e:
        print(f"[HARMONIZE] Error: {e}")

    return result
