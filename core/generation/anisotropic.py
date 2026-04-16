"""
Anisotropic sharpness filter — port exact de Fooocus modules/anisotropic.py

Bilateral blur guidé: lisse le bruit (epsilon) en utilisant la prédiction x0
comme guide pour préserver les edges. Résultat: transitions masque/original
plus nettes et couleurs plus harmonieuses pendant l'inpainting.
"""
import torch
import torch.nn.functional as F

Tensor = torch.Tensor


def _unpack_2d_ks(kernel_size):
    if isinstance(kernel_size, int):
        return kernel_size, kernel_size
    assert len(kernel_size) == 2
    return int(kernel_size[0]), int(kernel_size[1])


def _compute_zero_padding(kernel_size):
    ky, kx = _unpack_2d_ks(kernel_size)
    return (ky - 1) // 2, (kx - 1) // 2


def _gaussian(window_size, sigma):
    """1D Gaussian kernel."""
    # sigma: [B, 1] tensor
    x = torch.arange(window_size, device=sigma.device, dtype=sigma.dtype) - window_size // 2
    x = x.expand(sigma.shape[0], -1)
    if window_size % 2 == 0:
        x = x + 0.5
    gauss = torch.exp(-x.pow(2.0) / (2 * sigma.pow(2.0)))
    return gauss / gauss.sum(-1, keepdim=True)


def _get_gaussian_kernel2d(kernel_size, sigma, device=None, dtype=None):
    """2D Gaussian spatial kernel."""
    sigma_t = torch.tensor([[sigma, sigma]], device=device, dtype=dtype)
    ky, kx = _unpack_2d_ks(kernel_size)
    sigma_y, sigma_x = sigma_t[:, 0, None], sigma_t[:, 1, None]
    kernel_y = _gaussian(ky, sigma_y)[..., None]
    kernel_x = _gaussian(kx, sigma_x)[..., None]
    return kernel_y * kernel_x.view(-1, 1, kx)


def _bilateral_blur(x, guidance, kernel_size, sigma_color, sigma_space):
    """Bilateral blur: spatial Gaussian * range Gaussian (L1 distance on guidance)."""
    ky, kx = _unpack_2d_ks(kernel_size)
    pad_y, pad_x = _compute_zero_padding(kernel_size)

    # Pad + unfold → patches
    x_padded = F.pad(x, (pad_x, pad_x, pad_y, pad_y), mode='reflect')
    x_unfolded = x_padded.unfold(2, ky, 1).unfold(3, kx, 1).flatten(-2)

    g_padded = F.pad(guidance, (pad_x, pad_x, pad_y, pad_y), mode='reflect')
    g_unfolded = g_padded.unfold(2, ky, 1).unfold(3, kx, 1).flatten(-2)

    # Range kernel: L1 color distance → Gaussian
    diff = g_unfolded - guidance.unsqueeze(-1)
    color_distance_sq = diff.abs().sum(1, keepdim=True).square()
    color_kernel = (-0.5 / (sigma_color ** 2) * color_distance_sq).exp()

    # Spatial kernel
    space_kernel = _get_gaussian_kernel2d(kernel_size, sigma_space,
                                          device=x.device, dtype=x.dtype)
    space_kernel = space_kernel.view(-1, 1, 1, 1, kx * ky)

    # Combined weight + normalize
    kernel = space_kernel * color_kernel
    out = (x_unfolded * kernel).sum(-1) / kernel.sum(-1)
    return out


def adaptive_anisotropic_filter(x, g=None):
    """Point d'entrée — normalise le guide puis applique le bilateral blur.

    Args:
        x: noise prediction (epsilon) [B, C, H, W]
        g: x0 prediction (edge guide) [B, C, H, W], si None utilise x
    """
    if g is None:
        g = x
    s, m = torch.std_mean(g, dim=(1, 2, 3), keepdim=True)
    guidance = (g - m) / (s + 1e-5)
    return _bilateral_blur(x, guidance, kernel_size=(13, 13),
                           sigma_color=3.0, sigma_space=3.0)
