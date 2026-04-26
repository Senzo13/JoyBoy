# Packaging

JoyBoy desktop releases should keep the public core clean and keep user-owned
data outside git. The Windows package currently uses a folder-based layout with
a small `JoyBoy.exe` launcher, the app source, and an optional bundled Python
runtime.

## Windows

Generate or refresh the executable icon:

```powershell
venv\Scripts\python.exe scripts\generate_app_icons.py
```

Build the Windows package:

```powershell
venv\Scripts\python.exe scripts\package_windows.py --include-runtime --install-build-deps
```

Output:

```text
dist/JoyBoy-win-x64/
  JoyBoy.exe
  web/
  core/
  scripts/
  python312/
  venv/
  data/
```

`JoyBoy.exe` uses `packaging/assets/joyboy.ico`, generated from
`web/static/images/monogramme.png`.

The package creates a portable `data/` folder with:

```text
data/models/
data/packs/
data/cache/
data/output/
data/logs/
```

Packaged launchers also pin Hugging Face downloads to the JoyBoy model cache:

```text
HF_HOME=data/models/huggingface
HF_HUB_CACHE=data/models/huggingface
```

Model weights, generated outputs, local secrets, and private local pack sources
are not copied from the repository. Users install or import models and packs
from inside JoyBoy after launch.

For an installer-style build that stores user data in the normal user profile
instead of beside the executable, set `JOYBOY_PORTABLE=0` before starting the
launcher or avoid shipping the `data/` folder.

## macOS and Linux

Build macOS/Linux packages on their native platforms:

```bash
python scripts/package_unix.py --platform macos --package-name JoyBoy-macos --install-build-deps
python scripts/package_unix.py --platform linux --package-name JoyBoy-linux-x64 --install-build-deps
```

These packages include a small `JoyBoy` executable launcher plus the public
core. They do not include model weights or private local packs.

## Release Assets

Build release archives with:

```powershell
venv\Scripts\python.exe scripts\package_windows.py --no-runtime --install-build-deps
python scripts\package_unix.py --platform macos --package-name JoyBoy-macos --skip-launcher
python scripts\package_unix.py --platform linux --package-name JoyBoy-linux-x64 --skip-launcher
```

The first public assets are lightweight launchers plus the public core. Full
runtime installers, signed macOS `.dmg` files, Linux `.AppImage`/`.deb`
packages, and automated GitHub release uploads can build on this packaging
base once the GitHub token used for releases has workflow permissions.
