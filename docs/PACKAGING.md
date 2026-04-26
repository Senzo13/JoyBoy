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

Model weights, generated outputs, local secrets, and private local pack sources
are not copied from the repository. Users install or import models and packs
from inside JoyBoy after launch.

For an installer-style build that stores user data in the normal user profile
instead of beside the executable, set `JOYBOY_PORTABLE=0` before starting the
launcher or avoid shipping the `data/` folder.

## macOS and Linux

The same split should be kept for future packages:

- app bundle or launcher contains the public JoyBoy core and runtime;
- models, packs, cache, output, and secrets stay in a user data directory;
- model packs remain optional downloads/imports.
