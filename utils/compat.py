"""
Compatibility patches shared across modules.
"""


def _patch_torchvision_compatibility():
    """Patch for basicsr compatibility with torchvision >= 0.18.

    The module functional_tensor was moved/removed in recent torchvision.
    We create a mock module so that basicsr can import it.
    """
    import sys

    try:
        from torchvision.transforms.functional_tensor import rgb_to_grayscale  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        import types
        from torchvision.transforms import functional as F

        mock_module = types.ModuleType('torchvision.transforms.functional_tensor')

        def rgb_to_grayscale(img, num_output_channels=1):
            return F.rgb_to_grayscale(img, num_output_channels)

        mock_module.rgb_to_grayscale = rgb_to_grayscale
        sys.modules['torchvision.transforms.functional_tensor'] = mock_module
