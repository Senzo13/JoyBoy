"""
Fooocus Inpaint Patch — Weight delta application for SDXL UNet (diffusers).

Downloads and applies the Fooocus inpaint patch from HuggingFace (lllyasviel/fooocus_inpaint):
- fooocus_inpaint_head.pth (52KB): 5→320 conv, processes [latent_image, mask]
- inpaint_v26.fooocus.patch (1.3GB): UNet weight deltas in LDM format

The patch eliminates VAE color shift during inpainting by modifying
the UNet to natively handle inpainting with perfect color matching.

MUST be applied BEFORE quanto INT8 quantization (deltas are float, not quantized).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

FOOOCUS_REPO = "lllyasviel/fooocus_inpaint"
HEAD_FILENAME = "fooocus_inpaint_head.pth"
PATCH_FILENAME = "inpaint_v26.fooocus.patch"

# Storage for InpaintHead instances (outside nn.Module tree to survive quantization)
# Keyed by id(unet) → FooocusInpaintHead
_active_heads = {}


# ============================================================
# LDM → DIFFUSERS KEY MAPPING (SDXL UNet)
# ============================================================
# SDXL config:
#   down_block_types=["DownBlock2D", "CrossAttnDownBlock2D", "CrossAttnDownBlock2D"]
#   up_block_types=["CrossAttnUpBlock2D", "CrossAttnUpBlock2D", "UpBlock2D"]
#   block_out_channels=[320, 640, 1280], layers_per_block=2

_BLOCK_MAP = {
    # conv_in
    "input_blocks.0.0": "conv_in",
    # down_blocks.0 (DownBlock2D, no attention)
    "input_blocks.1.0": "down_blocks.0.resnets.0",
    "input_blocks.2.0": "down_blocks.0.resnets.1",
    "input_blocks.3.0": "down_blocks.0.downsamplers.0",
    # down_blocks.1 (CrossAttnDownBlock2D)
    "input_blocks.4.0": "down_blocks.1.resnets.0",
    "input_blocks.4.1": "down_blocks.1.attentions.0",
    "input_blocks.5.0": "down_blocks.1.resnets.1",
    "input_blocks.5.1": "down_blocks.1.attentions.1",
    "input_blocks.6.0": "down_blocks.1.downsamplers.0",
    # down_blocks.2 (CrossAttnDownBlock2D, no downsampler)
    "input_blocks.7.0": "down_blocks.2.resnets.0",
    "input_blocks.7.1": "down_blocks.2.attentions.0",
    "input_blocks.8.0": "down_blocks.2.resnets.1",
    "input_blocks.8.1": "down_blocks.2.attentions.1",
    # middle_block
    "middle_block.0": "mid_block.resnets.0",
    "middle_block.1": "mid_block.attentions.0",
    "middle_block.2": "mid_block.resnets.1",
    # up_blocks.0 (CrossAttnUpBlock2D)
    "output_blocks.0.0": "up_blocks.0.resnets.0",
    "output_blocks.0.1": "up_blocks.0.attentions.0",
    "output_blocks.1.0": "up_blocks.0.resnets.1",
    "output_blocks.1.1": "up_blocks.0.attentions.1",
    "output_blocks.2.0": "up_blocks.0.resnets.2",
    "output_blocks.2.1": "up_blocks.0.attentions.2",
    "output_blocks.2.2": "up_blocks.0.upsamplers.0",
    # up_blocks.1 (CrossAttnUpBlock2D)
    "output_blocks.3.0": "up_blocks.1.resnets.0",
    "output_blocks.3.1": "up_blocks.1.attentions.0",
    "output_blocks.4.0": "up_blocks.1.resnets.1",
    "output_blocks.4.1": "up_blocks.1.attentions.1",
    "output_blocks.5.0": "up_blocks.1.resnets.2",
    "output_blocks.5.1": "up_blocks.1.attentions.2",
    "output_blocks.5.2": "up_blocks.1.upsamplers.0",
    # up_blocks.2 (UpBlock2D, no attention)
    "output_blocks.6.0": "up_blocks.2.resnets.0",
    "output_blocks.7.0": "up_blocks.2.resnets.1",
    "output_blocks.8.0": "up_blocks.2.resnets.2",
}

_OTHER_MAP = {
    "time_embed.0": "time_embedding.linear_1",
    "time_embed.2": "time_embedding.linear_2",
    "label_emb.0.0": "add_embedding.linear_1",
    "label_emb.0.2": "add_embedding.linear_2",
    "out.0": "conv_norm_out",
    "out.2": "conv_out",
}

# ResNet: LDM sub-key → diffusers sub-key
_RESNET_MAP = {
    "in_layers.0": "norm1",
    "in_layers.2": "conv1",
    "emb_layers.1": "time_emb_proj",
    "out_layers.0": "norm2",
    "out_layers.3": "conv2",
    "skip_connection": "conv_shortcut",
}

# Downsampler: LDM "op" → diffusers "conv"
_DOWNSAMPLE_MAP = {"op": "conv"}


def _convert_ldm_key(ldm_key):
    """Convert a single LDM UNet key to diffusers format for SDXL."""
    key = ldm_key
    if key.startswith("diffusion_model."):
        key = key[len("diffusion_model."):]

    # time_embed, label_emb, out
    for ldm_pfx, diff_pfx in _OTHER_MAP.items():
        if key.startswith(ldm_pfx + "."):
            return diff_pfx + key[len(ldm_pfx):]

    # Block mapping (input_blocks, middle_block, output_blocks)
    for ldm_pfx, diff_pfx in _BLOCK_MAP.items():
        if key.startswith(ldm_pfx + "."):
            suffix = key[len(ldm_pfx) + 1:]

            # ResNet sub-key conversion (in_layers → norm1, etc.)
            if "resnets" in diff_pfx:
                for old, new in _RESNET_MAP.items():
                    if suffix.startswith(old + "."):
                        suffix = new + suffix[len(old):]
                        break
                    elif suffix == old:
                        suffix = new
                        break

            # Downsampler sub-key (op → conv)
            if "downsamplers" in diff_pfx:
                for old, new in _DOWNSAMPLE_MAP.items():
                    if suffix.startswith(old + "."):
                        suffix = new + suffix[len(old):]
                        break
                    elif suffix == old:
                        suffix = new
                        break

            return diff_pfx + "." + suffix

    return None


# ============================================================
# INPAINT HEAD (5ch → 320ch conv)
# ============================================================

class FooocusInpaintHead(nn.Module):
    """Conv2d(5, 320, 3) with replicate padding — matches Fooocus F.pad + F.conv2d."""

    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(5, 320, kernel_size=3, padding=0)  # no built-in padding
        self._features = None

    def forward(self, x):
        x = F.pad(x, (1, 1, 1, 1), mode="replicate")
        return self.conv(x)

    def load_head(self, path):
        sd = torch.load(path, map_location="cpu", weights_only=True)
        if "conv.weight" in sd:
            self.load_state_dict(sd)
        elif "head" in sd:
            # Fooocus format: nn.Parameter named "head" (no bias)
            self.conv.weight.data.copy_(sd["head"])
            if self.conv.bias is not None:
                self.conv.bias.data.zero_()
        elif "weight" in sd:
            self.conv.load_state_dict(sd)
        else:
            self.load_state_dict(sd)
        return self


def _make_conv_in_hook(head):
    """Create a closure-based forward hook that references the head directly."""
    def hook(module, input, output):
        if head._features is not None:
            try:
                # Safety: skip if features are meta tensors (no data)
                if head._features.device.type == "meta":
                    return output
                return output + head._features.to(device=output.device, dtype=output.dtype)
            except NotImplementedError:
                # Meta tensor fallback — cannot copy from meta
                return output
        return output
    return hook


def _register_hook(unet, head):
    """Register InpaintHead hook on unet.conv_in and store head in module-level dict."""
    _active_heads[id(unet)] = head
    unet.conv_in.register_forward_hook(_make_conv_in_hook(head))


# ============================================================
# DOWNLOAD & APPLY PATCH
# ============================================================

def download_fooocus_patch():
    """Download Fooocus inpaint patch files from HuggingFace (cached by hf_hub)."""
    from huggingface_hub import hf_hub_download
    import os
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase("download_fooocus", 62, 100, "Téléchargement patch Fooocus...")
    except Exception:
        pass

    head_path = hf_hub_download(repo_id=FOOOCUS_REPO, filename=HEAD_FILENAME, resume_download=True)
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase("download_fooocus", 70, 100, "Téléchargement poids Fooocus...")
    except Exception:
        pass
    patch_path = hf_hub_download(repo_id=FOOOCUS_REPO, filename=PATCH_FILENAME, resume_download=True)
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase("download_fooocus", 100, 100, "Patch Fooocus prêt")
    except Exception:
        pass
    return head_path, patch_path


def apply_fooocus_patch(unet, torch_dtype=None):
    """
    Download and apply the Fooocus inpaint patch to an SDXL UNet.

    1. Downloads patch files from HF (cached)
    2. Dequantizes uint8-packed deltas → float32
    3. Converts LDM keys → diffusers keys
    4. Applies deltas in-place (weight += delta)
    5. Creates InpaintHead and registers forward hook on conv_in

    MUST be called BEFORE quanto quantization (deltas need float weights).
    Only works with 4-channel SDXL UNets.

    Returns: True if patch applied successfully, False otherwise
    """
    # Safety: only patch 4-channel UNets (not 9-channel inpainting models)
    if hasattr(unet, 'config') and getattr(unet.config, 'in_channels', 4) != 4:
        print(f"[FOOOCUS] Skipping patch: UNet has {unet.config.in_channels} channels (need 4)")
        return False

    try:
        print("[FOOOCUS] Downloading inpaint patch files...")
        head_path, patch_path = download_fooocus_patch()

        # --- Load InpaintHead FIRST (small, fast — fail early before modifying weights) ---
        head = FooocusInpaintHead()
        head.load_head(head_path)
        if torch_dtype is not None:
            head = head.to(dtype=torch_dtype)
        print(f"[FOOOCUS] InpaintHead loaded ({HEAD_FILENAME})")

        # --- Apply weight deltas ---
        print("[FOOOCUS] Loading patch (1.3GB)...")
        patch_raw = torch.load(patch_path, map_location="cpu", weights_only=False)

        # Build named params dict for in-place modification
        params = {name: param for name, param in unet.named_parameters()}

        applied, skipped, unmapped = 0, 0, 0
        for ldm_key, value in patch_raw.items():
            # Dequantize: (w1_uint8, w_min, w_max) → float delta
            if isinstance(value, tuple) and len(value) >= 3:
                w1, w_min, w_max = value[0], value[1], value[2]
                delta = (w1.float() / 255.0) * (w_max - w_min) + w_min
            elif isinstance(value, torch.Tensor):
                delta = value.float()
            else:
                skipped += 1
                continue

            # Convert LDM key → diffusers key
            diff_key = _convert_ldm_key(ldm_key)
            if diff_key is None:
                unmapped += 1
                continue

            # Apply delta in-place
            if diff_key in params:
                param = params[diff_key]
                if param.is_meta:
                    # Skip meta tensors — they have no data to modify
                    skipped += 1
                    continue
                if param.shape == delta.shape:
                    with torch.no_grad():
                        param.data.add_(delta.to(param.dtype))
                    applied += 1
                else:
                    print(f"[FOOOCUS] Shape mismatch: {diff_key} param={param.shape} delta={delta.shape}")
                    skipped += 1
            else:
                skipped += 1

        del patch_raw
        print(f"[FOOOCUS] Patch applied: {applied} weights modified, {skipped} skipped, {unmapped} unmapped")

        if applied == 0:
            print("[FOOOCUS] WARNING: No weights applied! Key mapping may be incorrect.")
            return False

        # --- Register InpaintHead hook on conv_in ---
        # Head stored in _active_heads dict (NOT as submodule of conv_in)
        # This survives quanto quantization which replaces conv_in with QConv2d
        _register_hook(unet, head)
        print("[FOOOCUS] Hook registered on unet.conv_in")

        return True

    except Exception as e:
        print(f"[FOOOCUS] Patch failed (weights NOT modified): {e}")
        import traceback
        traceback.print_exc()
        return False


def reattach_fooocus_hook(unet):
    """
    Re-register InpaintHead hook after quantization.

    quanto replaces Conv2d with QConv2d, destroying the forward hook.
    This re-registers the hook on the new conv_in module.
    Must be called after quantize() + freeze().
    """
    head = _active_heads.get(id(unet))
    if head is None:
        return False
    unet.conv_in.register_forward_hook(_make_conv_in_hook(head))
    print("[FOOOCUS] Hook re-attached on conv_in (post-quantization)")
    return True


# ============================================================
# RUNTIME: Prepare/clear InpaintHead features per generation
# ============================================================

def _get_head(pipe):
    """Get the InpaintHead for a pipeline's UNet from module-level storage."""
    return _active_heads.get(id(pipe.unet))


def prepare_inpaint_head(pipe, filled_image, mask):
    """
    Pre-compute InpaintHead features before denoising.
    Call ONCE before each pipe() call.

    Fooocus feeds the InpaintHead the VAE-encoded FILL image (fooocus_fill'd),
    NOT a gray-masked version. The fill colors propagated from surrounding pixels
    give the InpaintHead proper color cues for skin tone matching.

    Args:
        pipe: diffusers StableDiffusionXLInpaintPipeline
        filled_image: PIL Image RGB — the fooocus_fill'd image (fill colors in mask area)
        mask: PIL Image L mode (255=inpaint, 0=keep)
    """
    head = _get_head(pipe)
    if head is None:
        print("[FOOOCUS] InpaintHead not found (no patch applied)")
        return

    # Safety: ensure InpaintHead weights are real tensors (not meta)
    # Meta tensors can appear on some systems due to diffusers low_cpu_mem_usage=True propagation
    if head.conv.weight.device.type == "meta":
        print("[FOOOCUS] WARNING: InpaintHead has meta tensors, re-loading from disk...")
        try:
            head_path, _ = download_fooocus_patch()
            head.load_head(head_path)
            print("[FOOOCUS] InpaintHead weights re-loaded successfully")
        except Exception as e:
            print(f"[FOOOCUS] Failed to re-load InpaintHead: {e}")
            return

    import numpy as np

    # Encode the FILL image directly — Fooocus feeds fill colors to InpaintHead,
    # not gray-masked. The fill colors give proper skin tone conditioning.
    img_np = np.array(filled_image).astype(np.float32) / 255.0
    img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)
    img_tensor = img_tensor * 2.0 - 1.0  # [0,1] → [-1,1]
    mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

    vae = pipe.vae
    vae_dtype = next(vae.parameters()).dtype
    _device = "cuda" if torch.cuda.is_available() else "cpu"

    with torch.no_grad():
        # Move input to CUDA — group offload hooks handle VAE module placement
        img_tensor = img_tensor.to(device=_device, dtype=vae_dtype)
        try:
            latent = vae.encode(img_tensor).latent_dist.mode()
        except Exception:
            # Fallback: try moving VAE to device explicitly (non-offloaded case)
            vae.to(_device)
            latent = vae.encode(img_tensor).latent_dist.mode()
            vae.to("cpu")
            torch.cuda.empty_cache()
        latent = latent * vae.config.scaling_factor

    # Mask → latent space (Fooocus-style max_pool2d)
    # max_pool2d(8,8) : si 1 pixel d'un bloc VAE 8x8 est masqué → tout le bloc latent est masqué
    # Empêche les textures vêtements de fuiter aux bords du masque
    mask_tensor = torch.from_numpy(mask_np).unsqueeze(0).unsqueeze(0)
    mask_fullres = torch.nn.functional.interpolate(
        mask_tensor, size=(latent.shape[2] * 8, latent.shape[3] * 8),
        mode='bilinear'
    ).round()
    mask_latent = torch.nn.functional.max_pool2d(mask_fullres, (8, 8)).round()

    # Compute features: [B, 5, H, W] → [B, 320, H, W]
    # CRITICAL: Fooocus channel order = [mask (1ch), latent (4ch)] — NOT [latent, mask]
    x = torch.cat([mask_latent, latent.cpu()], dim=1)  # mask first, then latent (Fooocus convention)
    # Always compute on CPU — head is small, hook handles device transfer to CUDA
    head_dtype = head.conv.weight.dtype
    with torch.no_grad():
        head._features = head(x.to(device="cpu", dtype=head_dtype))

    # Safety: verify features are real tensors
    if head._features.device.type == "meta":
        print("[FOOOCUS] WARNING: InpaintHead produced meta features, disabling")
        head._features = None
        return

    print(f"[FOOOCUS] InpaintHead features computed: {head._features.shape}")
    # Features will be moved to CUDA by the hook (.to(output.device))


def clear_inpaint_head(pipe):
    """Clear cached InpaintHead features after generation."""
    head = _get_head(pipe)
    if head is not None:
        head._features = None
