"""Install JoyBoy Python dependencies.

The setup used to install each requirement one by one. That made first install
look throttled because pip had to resolve, connect, and check metadata dozens of
times. This installer groups packages so pip can reuse one resolver pass.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = PROJECT_DIR / "scripts" / "requirements.txt"
TORCH_PACKAGES = {"torch", "torchvision", "torchaudio"}
PY312_MAX_OPTIONAL_PACKAGES = {"basicsr", "realesrgan", "gfpgan"}
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
HUGGINGFACE_HUB_PIN = "huggingface_hub>=0.34.0,<1.0"


def _requirement_name(requirement: str) -> str:
    name = requirement.split(";", 1)[0].strip()
    for token in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        name = name.split(token, 1)[0]
    return name.split("[", 1)[0].strip().lower().replace("_", "-")


def _read_requirements() -> list[str]:
    packages: list[str] = []
    with REQUIREMENTS_PATH.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                packages.append(line)
    return packages


def _has_nvidia_gpu() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        result = subprocess.run(
            [nvidia_smi, "-L"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0 and "GPU" in result.stdout


def _run_pip(args: list[str], title: str, *, timeout: int = 1800) -> int:
    print()
    print(f"    {title}")
    print(f"    > python -m pip {' '.join(args)}")
    env = os.environ.copy()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_DEFAULT_TIMEOUT", "120")
    env.setdefault("PIP_PROGRESS_BAR", "on")
    result = subprocess.run(
        [sys.executable, "-m", "pip", *args],
        cwd=str(PROJECT_DIR),
        env=env,
        timeout=timeout,
    )
    return int(result.returncode or 0)


def _install_individual(requirements: list[str]) -> list[str]:
    failed: list[str] = []
    for requirement in requirements:
        code = _run_pip(
            ["install", "--upgrade", "--prefer-binary", requirement],
            f"Fallback install: {requirement}",
            timeout=900,
        )
        if code != 0:
            failed.append(requirement)
    return failed


def install_packages() -> int:
    requirements = _read_requirements()
    torch_requirements = [
        requirement
        for requirement in requirements
        if _requirement_name(requirement) in TORCH_PACKAGES
    ]
    base_requirements = [
        requirement
        for requirement in requirements
        if _requirement_name(requirement) not in TORCH_PACKAGES
    ]

    skipped_optional: list[str] = []
    if sys.version_info >= (3, 13):
        filtered_base_requirements: list[str] = []
        for requirement in base_requirements:
            req_name = _requirement_name(requirement)
            if req_name in PY312_MAX_OPTIONAL_PACKAGES:
                skipped_optional.append(requirement)
            else:
                filtered_base_requirements.append(requirement)
        base_requirements = filtered_base_requirements

    print()
    print("    Installing JoyBoy Python dependencies")
    print(f"    Requirements: {len(requirements)} package entries")
    print("    Tip: big wheels can still be limited by PyPI/Hugging Face/CDN speed, not your local fiber.")
    if skipped_optional:
        print("    Skipping optional upscaling packages (Python >3.12):")
        for requirement in skipped_optional:
            print(f"      - {requirement}")

    if torch_requirements:
        if _has_nvidia_gpu():
            torch_code = _run_pip(
                [
                    "install",
                    "--upgrade",
                    "--prefer-binary",
                    "torch==2.8.0",
                    "torchvision==0.23.0",
                    "torchaudio==2.8.0",
                    "--index-url",
                    PYTORCH_CUDA_INDEX,
                ],
                "Installing PyTorch CUDA wheels (NVIDIA detected)",
            )
            if torch_code != 0:
                print("    [WARN] CUDA PyTorch install failed; trying default PyPI wheels.")
                torch_code = _run_pip(
                    ["install", "--upgrade", "--prefer-binary", *torch_requirements],
                    "Installing PyTorch from default PyPI",
                )
        else:
            torch_code = _run_pip(
                ["install", "--upgrade", "--prefer-binary", *torch_requirements],
                "Installing PyTorch wheels",
            )

        if torch_code != 0:
            print("    [WARN] PyTorch installation failed during the fast pass.")
            print("    The dependency checker will try to repair it next.")

    if base_requirements:
        base_code = _run_pip(
            ["install", "--upgrade", "--prefer-binary", *base_requirements],
            f"Installing remaining packages in one pass ({len(base_requirements)} entries)",
        )
        if base_code != 0:
            print()
            print("    [WARN] Bulk dependency install failed; falling back to one-by-one install.")
            failed = _install_individual(base_requirements)
            if failed:
                print()
                print("    [WARN] Some packages still failed during bootstrap:")
                for requirement in failed:
                    print(f"        - {requirement}")
                print("    The dependency checker will try targeted repairs next.")

        _run_pip(
            ["install", "--upgrade", "--force-reinstall", HUGGINGFACE_HUB_PIN],
            "Pinning Hugging Face Hub below 1.0 for transformers/diffusers compatibility",
            timeout=900,
        )

    print()
    print("    Dependencies installed.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(install_packages())
