"""Install the optional LightX2V backend pack.

This intentionally does not install LightX2V's full requirements.txt because
that file can downgrade JoyBoy's Torch/CUDA stack. The backend adapter installs
only safe Python deps and pins the external repo under ~/.joyboy/packs.
"""

from __future__ import annotations

import json

from core.models.lightx2v_backend import install_lightx2v_backend


def main() -> int:
    status = install_lightx2v_backend(upgrade=True)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
