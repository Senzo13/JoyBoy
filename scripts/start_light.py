"""Portable launcher for the small, external JoyBoy Light environment."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description="Start JoyBoy Light or its MCP server")
    parser.add_argument("--mcp", action="store_true", help="Run the stdio MCP server")
    args, forwarded = parser.parse_known_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    project = Path(__file__).resolve().parents[1]
    runtime_home = Path(os.environ.get("JOYBOY_HOME", "~/.joyboy")).expanduser()
    environment = runtime_home / "venvs" / "light"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = project / "scripts" / "requirements-light.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = environment / ".requirements-sha256"
    # In MCP mode every setup message must go to stderr, never the JSONL channel.
    if not python.exists():
        print("[JoyBoy Light] Creating a small environment outside the repository…", file=sys.stderr)
        venv.EnvBuilder(with_pip=True).create(environment)
    if not stamp.exists() or stamp.read_text() != digest:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)],
                       stdout=sys.stderr, stderr=sys.stderr, check=True)
        stamp.write_text(digest)
    os.chdir(project)
    module = "core.bridge.mcp_server" if args.mcp else "web.light"
    os.execv(str(python), [str(python), "-m", module, *forwarded])


if __name__ == "__main__":
    main()
