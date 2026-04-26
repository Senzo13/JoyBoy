from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import webbrowser


FALSE_VALUES = {"0", "false", "no", "off"}
TRUE_VALUES = {"1", "true", "yes", "on"}


def should_open_browser(force: bool = False) -> bool:
    env_value = os.environ.get("JOYBOY_OPEN_BROWSER", "").strip().lower()
    if env_value in FALSE_VALUES:
        return False
    if force or env_value in TRUE_VALUES:
        return True

    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return False

    return True


def wait_until_ready(url: str, timeout: float, interval: float) -> bool:
    deadline = time.time() + max(timeout, 0)
    while time.time() <= deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 500:
                    return True
        except Exception:
            time.sleep(interval)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Open JoyBoy once the local server is ready.")
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--interval", type=float, default=0.75)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not should_open_browser(args.force):
        return 0

    if wait_until_ready(args.url, args.timeout, args.interval):
        webbrowser.open(args.url, new=2, autoraise=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
