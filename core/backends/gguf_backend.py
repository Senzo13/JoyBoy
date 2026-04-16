"""
GGUF Backend - Modèles quantizés pour VRAM réduite

Utilise stable-diffusion-cpp-python pour charger les modèles GGUF.
Supporte: SDXL, Flux, Wan 2.2, LTX, CogVideoX, Hunyuan

Installation: pip install stable-diffusion-cpp-python
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Literal
from PIL import Image
import numpy as np

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform == 'linux'
IS_MAC = sys.platform == 'darwin'

# Dossier des modèles GGUF
GGUF_DIR = Path(__file__).parent.parent.parent / "models" / "gguf"

# Chemin vers le binaire sd-cli (pour conversion ET inférence)
SD_CPP_DIR = Path(__file__).parent.parent.parent / "ext_weights" / "sd_cpp"

# Platform-specific binary and URLs
if IS_WINDOWS:
    SD_CPP_EXE = SD_CPP_DIR / "sd-cli.exe"
    # Vulkan version - plus lent mais plus stable pour Kontext (CUDA crash avec --clip-on-cpu)
    SD_CPP_RELEASE_URL = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-493-65891d7/sd-master-65891d7-bin-win-avx2-x64.zip"
    SD_CPP_CUDART_URL = None  # Vulkan n'a pas besoin de DLLs CUDA
elif IS_LINUX:
    SD_CPP_EXE = SD_CPP_DIR / "sd-cli"
    # Linux AVX2 build (check stable-diffusion.cpp releases for latest)
    SD_CPP_RELEASE_URL = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-493-65891d7/sd-master-65891d7-bin-linux-avx2-x64.zip"
    SD_CPP_CUDART_URL = None
elif IS_MAC:
    SD_CPP_EXE = SD_CPP_DIR / "sd-cli"
    # Mac builds may need to be compiled from source
    SD_CPP_RELEASE_URL = None  # No pre-built Mac binaries typically
    SD_CPP_CUDART_URL = None
else:
    SD_CPP_EXE = SD_CPP_DIR / "sd-cli"
    SD_CPP_RELEASE_URL = None
    SD_CPP_CUDART_URL = None

# Quantizations disponibles (du plus lourd au plus léger)
QUANTIZATIONS = ["Q8_0", "Q6_K", "Q5_K", "Q4_K", "Q3_K", "Q2_K"]

# Mapping quantization → suffixe fichier (certains repos utilisent _S, _M, etc.)
QUANT_SUFFIXES = {
    "Q8_0": "Q8_0",
    "Q6_K": "Q6_K",
    "Q5_K": "Q5_K_S",
    "Q4_K": "Q4_K_S",
    "Q3_K": "Q3_K_S",
    "Q2_K": "Q2_K",
}

# Fichiers supplémentaires pour Flux (VAE, CLIP, T5)
FLUX_EXTRA_FILES = {
    "vae": {
        "hf_repo": "black-forest-labs/FLUX.1-dev",
        "filename": "ae.safetensors",
        "size_mb": 330,
    },
    "clip_l": {
        "hf_repo": "comfyanonymous/flux_text_encoders",
        "filename": "clip_l.safetensors",
        "size_mb": 246,
    },
    "t5xxl": {
        "hf_repo": "comfyanonymous/flux_text_encoders",
        "filename": "t5xxl_fp16.safetensors",
        "size_mb": 9800,
    },
}

# Registre des modèles GGUF avec leurs sources HuggingFace
GGUF_MODELS = {
    # === EDITING (instruction-based, pas besoin de masque) ===
    "flux-kontext": {
        "type": "edit",
        "hf_repo": "QuantStack/FLUX.1-Kontext-dev-GGUF",
        "filename": "flux1-kontext-dev-{quant_suffix}.gguf",
        "description": "Flux Kontext - editing intelligent par instruction",
        "needs_flux_extras": True,  # Besoin de VAE, CLIP, T5
    },
    "fluxkontext": {  # Alias
        "type": "edit",
        "hf_repo": "QuantStack/FLUX.1-Kontext-dev-GGUF",
        "filename": "flux1-kontext-dev-{quant_suffix}.gguf",
        "needs_flux_extras": True,
    },

    # === INPAINTING (besoin de masque) ===
    "epicrealismxl": {
        "type": "inpaint",
        "hf_repo": None,  # Pas de version pré-convertie, faut convertir
        "filename": "epicrealismxl-{quant}.gguf",
        "base_model": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
    },
    "juggernautxl": {
        "type": "inpaint",
        "hf_repo": None,
        "filename": "juggernautxl-{quant}.gguf",
        "base_model": "RunDiffusion/Juggernaut-XL-v9",
    },
    "sdxl-inpaint": {
        "type": "inpaint",
        "hf_repo": "gpustack/stable-diffusion-xl-inpainting-1.0-GGUF",
        "filename": "stable-diffusion-xl-inpainting-1.0-{quant}.gguf",
    },
    "fluxfill": {
        "type": "inpaint",
        "hf_repo": "YarvixPA/FLUX.1-Fill-dev-GGUF",
        "filename": "flux1-fill-dev-{quant}.gguf",
        "needs_flux_extras": True,  # Besoin de VAE, CLIP, T5
    },
    "flux-fill": {  # Alias
        "type": "inpaint",
        "hf_repo": "YarvixPA/FLUX.1-Fill-dev-GGUF",
        "filename": "flux1-fill-dev-{quant}.gguf",
        "needs_flux_extras": True,
    },

    # === VIDEO ===
    "wan22-ti2v": {
        "type": "video",
        "hf_repo": "QuantStack/Wan2.2-TI2V-5B-GGUF",
        "filename": "wan2.2-ti2v-5b-{quant}.gguf",
    },
    "wan21-i2v": {
        "type": "video",
        "hf_repo": "QuantStack/Wan2.1-I2V-14B-GGUF",
        "filename": "wan2.1-i2v-14b-{quant}.gguf",
    },
    "cogvideox-5b": {
        "type": "video",
        "hf_repo": None,  # À chercher
        "filename": "cogvideox-5b-{quant}.gguf",
    },
}

# État global
_sd_cpp_available = None
_current_model = None
_current_pipe = None


def _ensure_sd_cpp() -> Optional[Path]:
    """Télécharge sd-cli (platform-specific binary)."""
    import shutil

    if SD_CPP_RELEASE_URL is None:
        print("[GGUF] Pas de binaire pré-compilé pour cette plateforme")
        print("[GGUF] Compilez stable-diffusion.cpp depuis les sources: https://github.com/leejet/stable-diffusion.cpp")
        return None

    # Platform-specific checks
    if IS_WINDOWS:
        sd_dll = SD_CPP_DIR / "stable-diffusion.dll"
        cuda_dll = SD_CPP_DIR / "cudart64_12.dll"

        # Si on a stable-diffusion.dll mais PAS cudart (= version Vulkan), re-télécharger CUDA
        if sd_dll.exists() and not cuda_dll.exists():
            print("[GGUF] Version Vulkan détectée → migration vers CUDA (plus rapide)...")
            shutil.rmtree(SD_CPP_DIR, ignore_errors=True)

        # Si manque stable-diffusion.dll, re-télécharger
        if SD_CPP_EXE.exists() and not sd_dll.exists():
            print("[GGUF] Installation incomplète détectée → re-téléchargement...")
            shutil.rmtree(SD_CPP_DIR, ignore_errors=True)

        if SD_CPP_EXE.exists() and sd_dll.exists() and cuda_dll.exists():
            if SD_CPP_CUDART_URL:
                _ensure_cudart()
            return SD_CPP_EXE
    else:
        # Linux/Mac - just check if binary exists and is executable
        if SD_CPP_EXE.exists() and os.access(SD_CPP_EXE, os.X_OK):
            return SD_CPP_EXE

    # Nettoyer le dossier si le binaire n'existe pas (téléchargement raté précédent)
    if SD_CPP_DIR.exists():
        print("[GGUF] Nettoyage ancien téléchargement raté...")
        shutil.rmtree(SD_CPP_DIR, ignore_errors=True)

    print("[GGUF] Téléchargement de stable-diffusion.cpp...")
    SD_CPP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import requests
        import zipfile
        import io

        # Télécharger le zip
        resp = requests.get(SD_CPP_RELEASE_URL, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        chunks = []

        for chunk in resp.iter_content(chunk_size=1024*1024):
            chunks.append(chunk)
            downloaded += len(chunk)
            if total > 0 and downloaded % (10 * 1024 * 1024) < 8192:
                pct = downloaded * 100 // total
                print(f"[GGUF] Download: {pct}%")

        # Extraire les fichiers du zip
        zip_data = b''.join(chunks)
        found_exe = False
        exe_name = "sd-cli.exe" if IS_WINDOWS else "sd-cli"

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for name in zf.namelist():
                # Platform-specific extraction
                if IS_WINDOWS:
                    # Extract .exe and .dll files
                    if name.endswith('.exe') or name.endswith('.dll'):
                        filename = name.split('/')[-1]
                        dest_path = SD_CPP_DIR / filename
                        with zf.open(name) as src:
                            with open(dest_path, 'wb') as dst:
                                dst.write(src.read())
                        print(f"[GGUF] Extrait: {filename}")
                        if filename == exe_name:
                            found_exe = True
                else:
                    # Linux: extract all executables and .so files
                    filename = name.split('/')[-1]
                    if filename in ['sd-cli', 'sd'] or name.endswith('.so'):
                        dest_path = SD_CPP_DIR / filename
                        with zf.open(name) as src:
                            with open(dest_path, 'wb') as dst:
                                dst.write(src.read())
                        # Make executable
                        os.chmod(dest_path, 0o755)
                        print(f"[GGUF] Extrait: {filename}")
                        if filename == 'sd-cli' or filename == 'sd':
                            # Rename 'sd' to 'sd-cli' if needed
                            if filename == 'sd':
                                final_path = SD_CPP_DIR / 'sd-cli'
                                dest_path.rename(final_path)
                            found_exe = True

        if found_exe:
            print(f"[GGUF] sd-cli installé → {SD_CPP_EXE}")
            # Télécharger les DLLs CUDA (Windows only)
            if SD_CPP_CUDART_URL:
                _ensure_cudart()
            return SD_CPP_EXE

        # Debug: lister le contenu du zip
        print("[GGUF] Contenu du zip:")
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for name in zf.namelist()[:20]:
                print(f"  - {name}")
        print(f"[GGUF] {exe_name} non trouvé dans le zip")
        return None

    except Exception as e:
        print(f"[GGUF] Erreur téléchargement sd-cli: {e}")
        return None


def _ensure_cudart() -> bool:
    """Télécharge les DLLs CUDA runtime si pas présentes."""
    cudart_dll = SD_CPP_DIR / "cudart64_12.dll"
    if cudart_dll.exists():
        return True

    print("[GGUF] Téléchargement des DLLs CUDA runtime (~537MB)...")

    try:
        import requests
        import zipfile
        import tempfile
        import time

        # Stream directement sur disque pour éviter 500MB+ en RAM
        temp_zip = SD_CPP_DIR / "cudart_temp.zip"

        resp = requests.get(SD_CPP_CUDART_URL, stream=True, timeout=600)
        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        last_print = 0
        start_time = time.time()

        with open(temp_zip, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=4*1024*1024):  # 4MB chunks
                f.write(chunk)
                downloaded += len(chunk)
                # Print tous les 10%
                if total > 0:
                    pct = downloaded * 100 // total
                    if pct >= last_print + 10:
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        print(f"[GGUF] CUDA DLLs: {pct}% ({speed:.1f} MB/s)")
                        last_print = pct

        elapsed = time.time() - start_time
        print(f"[GGUF] Téléchargé en {elapsed:.1f}s")

        # Extraire les DLLs
        with zipfile.ZipFile(temp_zip) as zf:
            for name in zf.namelist():
                if name.endswith('.dll'):
                    dll_name = name.split('/')[-1]
                    dll_path = SD_CPP_DIR / dll_name
                    with zf.open(name) as src:
                        with open(dll_path, 'wb') as dst:
                            dst.write(src.read())
                    print(f"[GGUF] DLL extraite: {dll_name}")

        # Nettoyer le zip temporaire
        temp_zip.unlink()
        print("[GGUF] DLLs CUDA installées")
        return True

    except Exception as e:
        print(f"[GGUF] Erreur téléchargement CUDA DLLs: {e}")
        # Nettoyer le zip partiel si erreur
        if temp_zip.exists():
            temp_zip.unlink()
        return False


def _ensure_flux_extras() -> dict:
    """Télécharge les fichiers supplémentaires pour Flux (VAE, CLIP, T5)."""
    from huggingface_hub import hf_hub_download

    flux_dir = GGUF_DIR / "flux_extras"
    flux_dir.mkdir(parents=True, exist_ok=True)

    paths = {}
    for key, info in FLUX_EXTRA_FILES.items():
        dest_path = flux_dir / info["filename"]
        if dest_path.exists():
            paths[key] = dest_path
            continue

        print(f"[GGUF] Téléchargement {info['filename']} ({info['size_mb']}MB)...")
        try:
            downloaded = hf_hub_download(
                repo_id=info["hf_repo"],
                filename=info["filename"],
                local_dir=flux_dir,
                local_dir_use_symlinks=False,
            )
            paths[key] = Path(downloaded)
            print(f"[GGUF] ✓ {info['filename']}")
        except Exception as e:
            print(f"[GGUF] ✗ Erreur {info['filename']}: {e}")
            return None

    return paths


def is_gguf_available() -> bool:
    """Vérifie si le backend GGUF est disponible (sd-cli binary ou librairie Python)."""
    global _sd_cpp_available
    if _sd_cpp_available is not None:
        return _sd_cpp_available

    # Méthode 1: Librairie Python
    try:
        import stable_diffusion_cpp
        _sd_cpp_available = True
        print("[GGUF] Backend: stable-diffusion-cpp-python")
        return True
    except ImportError:
        pass

    # Méthode 2: Binaire sd-cli
    if SD_CPP_EXE.exists() or _ensure_sd_cpp() is not None:
        _sd_cpp_available = True
        print("[GGUF] Backend: sd-cli (binaire)")
        return True

    _sd_cpp_available = False
    return False


def ensure_gguf_backend() -> bool:
    """S'assure que le backend GGUF est disponible."""
    if is_gguf_available():
        return True

    # Essayer d'abord la librairie Python (plus rapide si ça marche)
    print("[GGUF] Installation de stable-diffusion-cpp-python...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "stable-diffusion-cpp-python"],
            check=True,
            capture_output=True
        )
        global _sd_cpp_available
        _sd_cpp_available = True
        print("[GGUF] Installation réussie")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[GGUF] Librairie Python indisponible: {e}")

    # Fallback: télécharger sd-cli binary
    print("[GGUF] Tentative avec sd-cli (binaire)...")
    if _ensure_sd_cpp() is not None:
        _sd_cpp_available = True
        return True

    print("[GGUF] Aucun backend GGUF disponible")
    return False


def get_model_path(model_name: str, quant: str = "Q6_K") -> Optional[Path]:
    """Retourne le chemin du modèle GGUF s'il existe."""
    if quant not in QUANTIZATIONS:
        quant = "Q6_K"

    model_info = GGUF_MODELS.get(model_name.lower().replace(" ", "").replace("-", ""))
    if not model_info:
        return None

    quant_suffix = QUANT_SUFFIXES.get(quant, quant)
    filename = model_info["filename"].format(quant=quant, quant_suffix=quant_suffix)
    model_path = GGUF_DIR / quant / filename

    if model_path.exists():
        return model_path
    return None


def _find_cached_safetensors(repo_id: str) -> Optional[Path]:
    """Trouve le fichier safetensors dans le cache HuggingFace."""
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()

        for repo in cache_info.repos:
            if repo.repo_id == repo_id:
                # Chercher dans les revisions
                for revision in repo.revisions:
                    for file in revision.files:
                        # Chercher un .safetensors (unet ou model)
                        if file.file_name.endswith('.safetensors'):
                            if 'unet' in str(file.file_path).lower() or 'model' in file.file_name.lower():
                                print(f"[GGUF] Trouvé dans cache: {file.file_path}")
                                return Path(file.file_path)
        return None
    except Exception as e:
        print(f"[GGUF] Erreur scan cache: {e}")
        return None


def _auto_convert_from_diffusers(model_name: str, quant: str = "Q6_K") -> Optional[Path]:
    """Convertit automatiquement depuis le cache diffusers si possible."""
    model_info = GGUF_MODELS.get(model_name.lower().replace(" ", "").replace("-", ""))
    if not model_info:
        return None

    base_model = model_info.get("base_model")
    if not base_model:
        print(f"[GGUF] Pas de modèle de base défini pour {model_name}")
        return None

    # Chercher dans le cache HuggingFace
    safetensors_path = _find_cached_safetensors(base_model)

    if safetensors_path is None:
        # Essayer de télécharger le modèle diffusers d'abord
        print(f"[GGUF] Modèle {base_model} pas en cache, téléchargement...")
        try:
            from huggingface_hub import hf_hub_download, list_repo_files

            # Chercher un fichier safetensors dans le repo
            files = list_repo_files(base_model)
            safetensors_files = [f for f in files if f.endswith('.safetensors')]

            # Préférer unet > model
            target = None
            for f in safetensors_files:
                if 'unet' in f.lower():
                    target = f
                    break
            if not target and safetensors_files:
                target = safetensors_files[0]

            if target:
                downloaded = hf_hub_download(repo_id=base_model, filename=target)
                safetensors_path = Path(downloaded)
            else:
                print(f"[GGUF] Aucun fichier safetensors trouvé dans {base_model}")
                return None

        except Exception as e:
            print(f"[GGUF] Erreur téléchargement diffusers: {e}")
            return None

    if safetensors_path and safetensors_path.exists():
        print(f"[GGUF] Auto-conversion depuis {safetensors_path.name}...")
        return convert_to_gguf(safetensors_path, model_name, quant)

    return None


def download_gguf_model(model_name: str, quant: str = "Q6_K") -> Optional[Path]:
    """Télécharge un modèle GGUF depuis HuggingFace ou convertit depuis diffusers."""
    model_info = GGUF_MODELS.get(model_name.lower().replace(" ", "").replace("-", ""))
    if not model_info:
        print(f"[GGUF] Modèle inconnu: {model_name}")
        return None

    hf_repo = model_info.get("hf_repo")
    if not hf_repo:
        # Pas de version pré-convertie → essayer auto-conversion
        print(f"[GGUF] Pas de GGUF pré-converti pour {model_name}, tentative auto-conversion...")
        return _auto_convert_from_diffusers(model_name, quant)

    # Résoudre le suffixe de quantization (Q4_K → Q4_K_S pour certains repos)
    quant_suffix = QUANT_SUFFIXES.get(quant, quant)
    filename = model_info["filename"].format(quant=quant, quant_suffix=quant_suffix)
    dest_path = GGUF_DIR / quant / filename

    if dest_path.exists():
        return dest_path

    try:
        from huggingface_hub import hf_hub_download

        print(f"[GGUF] Téléchargement {filename} depuis {hf_repo}...")

        # Chercher le fichier correspondant au quant demandé
        downloaded = hf_hub_download(
            repo_id=hf_repo,
            filename=filename,
            local_dir=str(GGUF_DIR / quant),
            local_dir_use_symlinks=False,
        )

        print(f"[GGUF] Téléchargé: {dest_path}")
        return Path(downloaded)

    except Exception as e:
        print(f"[GGUF] Erreur téléchargement: {e}")
        return None


def list_available_models(quant: str = None) -> dict:
    """Liste les modèles GGUF disponibles localement."""
    available = {"inpaint": [], "video": [], "edit": []}

    quants = [quant] if quant else QUANTIZATIONS

    for q in quants:
        quant_dir = GGUF_DIR / q
        if not quant_dir.exists():
            continue

        for model_name, model_info in GGUF_MODELS.items():
            quant_suffix = QUANT_SUFFIXES.get(q, q)
            filename = model_info["filename"].format(quant=q, quant_suffix=quant_suffix)
            if (quant_dir / filename).exists():
                model_type = model_info["type"]
                entry = {"name": model_name, "quant": q, "filename": filename}
                if entry not in available[model_type]:
                    available[model_type].append(entry)

    return available


def _has_python_backend() -> bool:
    """Vérifie si la librairie Python stable-diffusion-cpp est disponible."""
    try:
        import stable_diffusion_cpp
        return True
    except ImportError:
        return False


class GGUFInpaintPipelineExe:
    """
    Pipeline d'inpainting utilisant sd-cli (binaire) directement.
    Fallback quand stable-diffusion-cpp-python n'est pas installable.
    """

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.sd_exe = _ensure_sd_cpp()
        if self.sd_exe is None:
            raise RuntimeError("sd-cli non disponible")
        print(f"[GGUF-EXE] Pipeline initialisé: {model_path.name}")

    def __call__(
        self,
        prompt: str,
        image: Image.Image,
        mask_image: Image.Image,
        negative_prompt: str = "",
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        strength: float = 0.8,
        seed: int = -1,
        **kwargs,  # Ignorer les args supplémentaires (height, width, etc.)
    ) -> Image.Image:
        """Génère une image inpaintée via sd-cli."""
        # Ignorer kwargs non supportés (height, width, generator, etc.)
        if kwargs:
            ignored = list(kwargs.keys())
            print(f"[GGUF-EXE] Args ignorés: {ignored}")
        import tempfile
        import uuid

        # Créer un dossier temporaire pour les fichiers
        temp_dir = Path(tempfile.gettempdir()) / "gguf_inpaint"
        temp_dir.mkdir(exist_ok=True)

        job_id = str(uuid.uuid4())[:8]
        input_path = temp_dir / f"input_{job_id}.png"
        mask_path = temp_dir / f"mask_{job_id}.png"
        output_path = temp_dir / f"output_{job_id}.png"

        try:
            # Sauvegarder les images temporaires
            image.convert("RGB").save(input_path)

            # sd-cli attend mask: blanc = zone à garder, noir = zone à modifier
            # Notre convention: blanc = zone à modifier
            # Donc on inverse le masque
            mask_np = np.array(mask_image.convert("L"))
            mask_inverted = Image.fromarray(255 - mask_np)
            mask_inverted.save(mask_path)

            # Construire la commande sd-cli
            # sd-cli -M img2img -m model.gguf -i input.png --mask mask.png -o output.png -p "prompt" -n "negative" --steps 30 --cfg-scale 7.5 --strength 0.8
            cmd = [
                str(self.sd_exe),
                "-M", "img2img",
                "-m", str(self.model_path),
                "-i", str(input_path),
                "--mask", str(mask_path),
                "-o", str(output_path),
                "-p", prompt,
                "-n", negative_prompt,
                "--steps", str(num_inference_steps),
                "--cfg-scale", str(guidance_scale),
                "--strength", str(strength),
            ]

            if seed >= 0:
                cmd.extend(["--seed", str(seed)])

            print(f"[GGUF-EXE] Exécution inpainting ({num_inference_steps} steps)...")
            print(f"[GGUF-EXE] CWD: {SD_CPP_DIR}")
            print(f"[GGUF-EXE] DLLs présentes: {[f.name for f in SD_CPP_DIR.glob('*.dll')]}")

            # Ajouter le dossier sd_cpp au PATH pour les DLLs
            env = os.environ.copy()
            env['PATH'] = str(SD_CPP_DIR) + os.pathsep + env.get('PATH', '')

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max
                cwd=str(SD_CPP_DIR),
                env=env,
            )

            if result.returncode != 0:
                print(f"[GGUF-EXE] Erreur (code {result.returncode})")
                if result.stdout:
                    print(f"[GGUF-EXE] stdout: {result.stdout[:500]}")
                if result.stderr:
                    print(f"[GGUF-EXE] stderr: {result.stderr[:500]}")
                # Code 3221225781 = 0xC0000135 = STATUS_DLL_NOT_FOUND
                if result.returncode == 3221225781:
                    print(f"[GGUF-EXE] DLL manquante! Vérifiez que CUDA 12 est installé sur le système.")
                raise RuntimeError(f"sd-cli failed: {result.stderr[:200] if result.stderr else 'DLL not found (code 3221225781)'}")

            if not output_path.exists():
                raise RuntimeError("Output image not created")

            # Charger le résultat
            output_image = Image.open(output_path).convert("RGB")

            print(f"[GGUF-EXE] Génération terminée")

            # Wrapper pour compatibilité avec diffusers (pipe().images[0])
            class PipelineOutput:
                def __init__(self, img):
                    self.images = [img]

            return PipelineOutput(output_image)

        finally:
            # Nettoyer les fichiers temporaires
            for p in [input_path, mask_path, output_path]:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

    def unload(self):
        """Rien à décharger pour le mode EXE."""
        pass


class GGUFEditPipelineExe:
    """
    Pipeline d'editing (img2img) utilisant sd-cli.
    Pour Flux Kontext - editing intelligent SANS masque.
    """

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.sd_exe = _ensure_sd_cpp()
        if self.sd_exe is None:
            raise RuntimeError("sd-cli non disponible")

        # Télécharger les fichiers supplémentaires Flux (VAE, CLIP, T5)
        print(f"[GGUF-EDIT] Vérification des fichiers Flux...")
        self.flux_extras = _ensure_flux_extras()
        if not self.flux_extras:
            raise RuntimeError("Impossible de télécharger les fichiers Flux (VAE, CLIP, T5)")

        print(f"[GGUF-EDIT] Pipeline Kontext initialisé: {model_path.name}")

    def __call__(
        self,
        prompt: str,
        image: Image.Image,
        negative_prompt: str = "",
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        strength: float = 0.95,
        seed: int = -1,
        **kwargs,
    ):
        """
        Édite une image via instruction textuelle (Flux Kontext).
        PAS de masque - le modèle comprend quoi modifier.
        """
        if kwargs:
            print(f"[GGUF-EDIT] Args ignorés: {list(kwargs.keys())}")

        import tempfile
        import uuid

        temp_dir = Path(tempfile.gettempdir()) / "gguf_edit"
        temp_dir.mkdir(exist_ok=True)

        job_id = str(uuid.uuid4())[:8]
        input_path = temp_dir / f"input_{job_id}.png"
        output_path = temp_dir / f"output_{job_id}.png"

        try:
            # Sauvegarder l'image
            image.convert("RGB").save(input_path)

            # DEBUG: vérifier que l'image est bien sauvegardée
            if input_path.exists():
                size_kb = input_path.stat().st_size / 1024
                print(f"[GGUF-EDIT] Image sauvegardée: {input_path} ({size_kb:.1f} KB)")
                print(f"[GGUF-EDIT] Dimensions: {image.size}, Mode: {image.mode}")
            else:
                print(f"[GGUF-EDIT] ERREUR: Image non sauvegardée!")

            # Commande sd-cli avec tous les fichiers Flux
            # --diffusion-model: le transformer GGUF
            # --vae, --clip_l, --t5xxl: fichiers supplémentaires
            # -r: image de RÉFÉRENCE pour Kontext (PAS --init-img!)
            # --cfg-scale 1.0: valeur officielle pour Kontext
            # PAS de --strength: Kontext gère lui-même
            # Commande EXACTE de la doc officielle Kontext
            # https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/kontext.md
            cmd = [
                str(self.sd_exe),
                "-r", str(input_path),  # Reference image pour Kontext editing
                "--diffusion-model", str(self.model_path),
                "--vae", str(self.flux_extras["vae"]),
                "--clip_l", str(self.flux_extras["clip_l"]),
                "--t5xxl", str(self.flux_extras["t5xxl"]),
                "-o", str(output_path),
                "-p", prompt,
                "--cfg-scale", "1.0",  # Valeur officielle pour Kontext
                "--sampling-method", "euler",
                "-v",  # Verbose
                "--clip-on-cpu",  # Réactivé pour Vulkan (crashait sur CUDA)
            ]

            if seed >= 0:
                cmd.extend(["--seed", str(seed)])

            print(f"[GGUF-EDIT] Editing Kontext...")
            print(f"[GGUF-EDIT] Prompt: {prompt[:80]}...")
            # DEBUG: afficher la commande COMPLÈTE
            print(f"[GGUF-EDIT] Commande complète:")
            print(f"  {' '.join(cmd)}")

            env = os.environ.copy()
            env['PATH'] = str(SD_CPP_DIR) + os.pathsep + env.get('PATH', '')

            # Afficher la sortie en temps réel
            import sys
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(SD_CPP_DIR),
                env=env,
                bufsize=1,
            )

            output_lines = []
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    print(f"[SD-CLI] {line}")
                    output_lines.append(line)
                    sys.stdout.flush()

            process.wait()

            if process.returncode != 0:
                print(f"[GGUF-EDIT] Erreur (code {process.returncode})")
                raise RuntimeError(f"sd-cli edit failed: {output_lines[-1] if output_lines else 'unknown error'}")

            if not output_path.exists():
                raise RuntimeError("Output image not created")

            output_image = Image.open(output_path).convert("RGB")
            print(f"[GGUF-EDIT] Editing terminé")

            class PipelineOutput:
                def __init__(self, img):
                    self.images = [img]

            return PipelineOutput(output_image)

        finally:
            for p in [input_path, output_path]:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

    def unload(self):
        """Rien à décharger pour le mode EXE."""
        pass


class GGUFFluxFillPipelineExe:
    """
    Pipeline Flux Fill inpainting via sd-cli (GGUF quantifié).
    Comme GGUFEditPipelineExe mais avec support du masque pour inpainting.
    Utilise --diffusion-model + flux extras (VAE, CLIP, T5).
    """

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.sd_exe = _ensure_sd_cpp()
        if self.sd_exe is None:
            raise RuntimeError("sd-cli non disponible")

        # Télécharger les fichiers supplémentaires Flux (VAE, CLIP, T5)
        print(f"[GGUF-FLUXFILL] Vérification des fichiers Flux...")
        self.flux_extras = _ensure_flux_extras()
        if not self.flux_extras:
            raise RuntimeError("Impossible de télécharger les fichiers Flux (VAE, CLIP, T5)")

        print(f"[GGUF-FLUXFILL] Pipeline initialisé: {model_path.name}")

    def __call__(
        self,
        prompt: str,
        image: Image.Image,
        mask_image: Image.Image,
        negative_prompt: str = "",
        num_inference_steps: int = 28,
        guidance_scale: float = 30.0,
        strength: float = 0.95,
        seed: int = -1,
        **kwargs,
    ):
        """Génère une image inpaintée via sd-cli avec Flux Fill GGUF."""
        if kwargs:
            ignored = list(kwargs.keys())
            print(f"[GGUF-FLUXFILL] Args ignorés: {ignored}")

        import tempfile
        import uuid

        temp_dir = Path(tempfile.gettempdir()) / "gguf_fluxfill"
        temp_dir.mkdir(exist_ok=True)

        job_id = str(uuid.uuid4())[:8]
        input_path = temp_dir / f"input_{job_id}.png"
        mask_path = temp_dir / f"mask_{job_id}.png"
        output_path = temp_dir / f"output_{job_id}.png"

        try:
            # Sauvegarder les images temporaires
            image.convert("RGB").save(input_path)

            # sd-cli attend mask: blanc = zone à garder, noir = zone à modifier
            # Notre convention: blanc = zone à modifier → inverser
            mask_np = np.array(mask_image.convert("L"))
            mask_inverted = Image.fromarray(255 - mask_np)
            mask_inverted.save(mask_path)

            print(f"[GGUF-FLUXFILL] Image: {image.size}, Mask sauvegardé")

            # Commande sd-cli avec fichiers Flux + masque
            cmd = [
                str(self.sd_exe),
                "-M", "img2img",
                "-i", str(input_path),
                "--mask", str(mask_path),
                "--diffusion-model", str(self.model_path),
                "--vae", str(self.flux_extras["vae"]),
                "--clip_l", str(self.flux_extras["clip_l"]),
                "--t5xxl", str(self.flux_extras["t5xxl"]),
                "-o", str(output_path),
                "-p", prompt,
                "--cfg-scale", str(guidance_scale),
                "--steps", str(num_inference_steps),
                "--strength", str(strength),
                "--sampling-method", "euler",
                "--clip-on-cpu",  # Encodeurs texte en CPU → économise VRAM
                "-v",
            ]

            if negative_prompt:
                cmd.extend(["-n", negative_prompt])

            if seed >= 0:
                cmd.extend(["--seed", str(seed)])

            print(f"[GGUF-FLUXFILL] Inpainting Flux Fill ({num_inference_steps} steps, guidance={guidance_scale})...")
            print(f"[GGUF-FLUXFILL] Prompt: {prompt[:80]}...")

            env = os.environ.copy()
            env['PATH'] = str(SD_CPP_DIR) + os.pathsep + env.get('PATH', '')

            # Afficher la sortie en temps réel
            import sys
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(SD_CPP_DIR),
                env=env,
                bufsize=1,
            )

            output_lines = []
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    print(f"[SD-CLI] {line}")
                    output_lines.append(line)
                    sys.stdout.flush()

            process.wait()

            if process.returncode != 0:
                print(f"[GGUF-FLUXFILL] Erreur (code {process.returncode})")
                if process.returncode == 3221225781:
                    print(f"[GGUF-FLUXFILL] DLL manquante! Vérifiez que CUDA 12 est installé.")
                raise RuntimeError(f"sd-cli flux fill failed: {output_lines[-1] if output_lines else 'unknown error'}")

            if not output_path.exists():
                raise RuntimeError("Output image not created")

            output_image = Image.open(output_path).convert("RGB")
            print(f"[GGUF-FLUXFILL] Génération terminée")

            class PipelineOutput:
                def __init__(self, img):
                    self.images = [img]

            return PipelineOutput(output_image)

        finally:
            for p in [input_path, mask_path, output_path]:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

    def unload(self):
        """Rien à décharger pour le mode EXE."""
        pass


class GGUFInpaintPipeline:
    """Pipeline d'inpainting utilisant stable-diffusion.cpp avec GGUF."""

    def __init__(self, model_path: Path, n_threads: int = -1):
        """
        Initialise le pipeline GGUF.

        Args:
            model_path: Chemin vers le fichier .gguf
            n_threads: Nombre de threads CPU (-1 = auto)
        """
        if not is_gguf_available():
            raise RuntimeError("stable-diffusion-cpp-python n'est pas installé")

        from stable_diffusion_cpp import StableDiffusion

        self.model_path = model_path
        self.model = StableDiffusion(
            model_path=str(model_path),
            n_threads=n_threads,
            wtype="default",  # Auto-detect from GGUF
        )
        print(f"[GGUF] Modèle chargé: {model_path.name}")

    def __call__(
        self,
        prompt: str,
        image: Image.Image,
        mask_image: Image.Image,
        negative_prompt: str = "",
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        strength: float = 0.8,
        seed: int = -1,
    ) -> Image.Image:
        """
        Génère une image inpaintée.

        Args:
            prompt: Prompt positif
            image: Image source (PIL)
            mask_image: Masque (blanc = zone à modifier)
            negative_prompt: Prompt négatif
            num_inference_steps: Nombre de steps
            guidance_scale: CFG scale
            strength: Force de dénoising
            seed: Seed (-1 = random)

        Returns:
            Image générée (PIL)
        """
        # Convertir les images en format attendu par stable-diffusion.cpp
        init_img = np.array(image.convert("RGB"))
        mask_img = np.array(mask_image.convert("L"))

        # Inverser le masque (sd.cpp attend 0=masked, 255=unmasked)
        mask_img = 255 - mask_img

        result = self.model.img_to_img(
            image=init_img,
            mask_image=mask_img,
            prompt=prompt,
            negative_prompt=negative_prompt,
            cfg_scale=guidance_scale,
            sample_steps=num_inference_steps,
            strength=strength,
            seed=seed,
        )

        return Image.fromarray(result)

    def unload(self):
        """Libère la mémoire."""
        if hasattr(self, 'model') and self.model is not None:
            del self.model
            self.model = None

        import gc
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


class GGUFText2ImgPipeline:
    """Pipeline text-to-image utilisant stable-diffusion.cpp avec GGUF."""

    def __init__(self, model_path: Path, n_threads: int = -1):
        if not is_gguf_available():
            raise RuntimeError("stable-diffusion-cpp-python n'est pas installé")

        from stable_diffusion_cpp import StableDiffusion

        self.model_path = model_path
        self.model = StableDiffusion(
            model_path=str(model_path),
            n_threads=n_threads,
            wtype="default",
        )
        print(f"[GGUF] Modèle chargé: {model_path.name}")

    def __call__(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: int = -1,
    ) -> Image.Image:
        """Génère une image depuis un prompt."""
        result = self.model.txt_to_img(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            cfg_scale=guidance_scale,
            sample_steps=num_inference_steps,
            seed=seed,
        )

        return Image.fromarray(result)

    def unload(self):
        """Libère la mémoire."""
        if hasattr(self, 'model') and self.model is not None:
            del self.model
            self.model = None

        import gc
        gc.collect()


def load_gguf_inpaint(model_name: str, quant: str = "Q6_K") -> Optional[GGUFInpaintPipeline]:
    """
    Charge un pipeline d'inpainting GGUF.

    Args:
        model_name: Nom du modèle (epicrealismxl, juggernautxl, flux-fill, etc.)
        quant: Niveau de quantization (Q8_0, Q6_K, Q5_K, Q4_K)

    Returns:
        Pipeline GGUF ou None si échec
    """
    global _current_model, _current_pipe

    # Vérifier si déjà chargé
    model_key = f"{model_name}_{quant}"
    if _current_model == model_key and _current_pipe is not None:
        return _current_pipe

    # Décharger l'ancien
    if _current_pipe is not None:
        _current_pipe.unload()
        _current_pipe = None
        _current_model = None

    # Installer le backend si nécessaire
    if not ensure_gguf_backend():
        return None

    # Chercher le modèle local
    model_path = get_model_path(model_name, quant)

    # Télécharger si pas présent
    if model_path is None:
        model_path = download_gguf_model(model_name, quant)

    if model_path is None:
        print(f"[GGUF] Modèle non disponible: {model_name} {quant}")
        return None

    try:
        # Flux Fill GGUF → pipeline spécialisé avec flux extras
        model_config = GGUF_MODELS.get(model_name, {})
        if model_config.get("needs_flux_extras"):
            print(f"[GGUF] Flux Fill détecté → pipeline avec VAE/CLIP/T5")
            _current_pipe = GGUFFluxFillPipelineExe(model_path)
        # Utiliser la librairie Python si disponible, sinon sd-cli
        elif _has_python_backend():
            _current_pipe = GGUFInpaintPipeline(model_path)
        else:
            print("[GGUF] Librairie Python indisponible, utilisation de sd-cli...")
            _current_pipe = GGUFInpaintPipelineExe(model_path)
        _current_model = model_key
        return _current_pipe
    except Exception as e:
        print(f"[GGUF] Erreur chargement: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_gguf_edit(model_name: str = "flux-kontext", quant: str = "Q4_K") -> Optional[GGUFEditPipelineExe]:
    """
    Charge un pipeline d'editing GGUF (Flux Kontext).
    Editing par instruction - PAS de masque.

    Args:
        model_name: Nom du modèle (flux-kontext)
        quant: Niveau de quantization (Q4_K, Q6_K, Q8_0)

    Returns:
        Pipeline GGUF ou None si échec
    """
    global _current_model, _current_pipe

    model_key = f"edit_{model_name}_{quant}"
    if _current_model == model_key and _current_pipe is not None:
        return _current_pipe

    # Décharger l'ancien
    if _current_pipe is not None:
        _current_pipe.unload()
        _current_pipe = None
        _current_model = None

    if not ensure_gguf_backend():
        return None

    model_path = get_model_path(model_name, quant)

    if model_path is None:
        model_path = download_gguf_model(model_name, quant)

    if model_path is None:
        print(f"[GGUF] Modèle Kontext non disponible: {model_name} {quant}")
        return None

    try:
        # Kontext = toujours via sd-cli (pas de binding Python)
        _current_pipe = GGUFEditPipelineExe(model_path)
        _current_model = model_key
        return _current_pipe
    except Exception as e:
        print(f"[GGUF] Erreur chargement Kontext: {e}")
        import traceback
        traceback.print_exc()
        return None


def is_kontext_model(model_name: str) -> bool:
    """Vérifie si c'est un modèle Kontext (editing sans masque)."""
    model_info = GGUF_MODELS.get(model_name.lower().replace(" ", "").replace("-", ""))
    if not model_info:
        # Essayer avec le nom original
        model_info = GGUF_MODELS.get(model_name.lower())
    return model_info is not None and model_info.get("type") == "edit"


def load_gguf_text2img(model_name: str, quant: str = "Q6_K") -> Optional[GGUFText2ImgPipeline]:
    """Charge un pipeline text2img GGUF."""
    global _current_model, _current_pipe

    model_key = f"t2i_{model_name}_{quant}"
    if _current_model == model_key and _current_pipe is not None:
        return _current_pipe

    if _current_pipe is not None:
        _current_pipe.unload()
        _current_pipe = None
        _current_model = None

    if not ensure_gguf_backend():
        return None

    model_path = get_model_path(model_name, quant)
    if model_path is None:
        model_path = download_gguf_model(model_name, quant)

    if model_path is None:
        return None

    try:
        _current_pipe = GGUFText2ImgPipeline(model_path)
        _current_model = model_key
        return _current_pipe
    except Exception as e:
        print(f"[GGUF] Erreur chargement: {e}")
        return None


def unload_gguf():
    """Décharge le modèle GGUF actuel."""
    global _current_model, _current_pipe

    if _current_pipe is not None:
        _current_pipe.unload()
        _current_pipe = None
        _current_model = None
        print("[GGUF] Modèle déchargé")


def get_gguf_status() -> dict:
    """Retourne le statut du backend GGUF."""
    return {
        "available": is_gguf_available(),
        "current_model": _current_model,
        "models_dir": str(GGUF_DIR),
        "quantizations": QUANTIZATIONS,
        "local_models": list_available_models(),
    }


# ============================================================
# CONVERSION SAFETENSORS → GGUF
# ============================================================

def convert_to_gguf(
    source_path: Path,
    output_name: str,
    quant: str = "Q6_K",
    model_type: str = "sdxl",
) -> Optional[Path]:
    """
    Convertit un modèle safetensors en GGUF via stable-diffusion.cpp.

    Args:
        source_path: Chemin vers le fichier .safetensors
        output_name: Nom du fichier de sortie (sans extension)
        quant: Niveau de quantization (Q8_0, Q6_K, Q5_K, Q4_K)
        model_type: Type de modèle (sdxl, sd15, flux) - ignoré, auto-détecté

    Returns:
        Chemin vers le fichier GGUF créé ou None si échec
    """
    if not source_path.exists():
        print(f"[GGUF] Fichier source non trouvé: {source_path}")
        return None

    if quant not in QUANTIZATIONS:
        quant = "Q6_K"

    output_dir = GGUF_DIR / quant
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{output_name}-{quant}.gguf"

    if output_path.exists():
        print(f"[GGUF] Fichier existe déjà: {output_path}")
        return output_path

    # S'assurer que sd-cli est disponible
    sd_exe = _ensure_sd_cpp()
    if sd_exe is None:
        print("[GGUF] Impossible de télécharger sd-cli, conversion impossible")
        return None

    # Mapper les noms de quantization
    quant_map = {
        "Q8_0": "q8_0",
        "Q6_K": "q6_k",
        "Q5_K": "q5_k",
        "Q4_K": "q4_k",
        "Q5_0": "q5_0",
        "Q5_1": "q5_1",
        "Q4_0": "q4_0",
        "Q4_1": "q4_1",
    }
    quant_type = quant_map.get(quant, "q6_k")

    print(f"[GGUF] Conversion {source_path.name} → {output_path.name} ({quant_type})...")
    print(f"[GGUF] ⚠️ La conversion peut prendre 5-20 minutes et utilise beaucoup de RAM")

    try:
        # Commande: sd-cli -M convert -m input.safetensors -o output.gguf --type q6_k
        cmd = [
            str(sd_exe),
            "-M", "convert",
            "-m", str(source_path),
            "-o", str(output_path),
            "--type", quant_type,
        ]

        print(f"[GGUF] Commande: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes max
            cwd=str(SD_CPP_DIR),
        )

        if result.returncode == 0 and output_path.exists():
            size_gb = output_path.stat().st_size / (1024**3)
            print(f"[GGUF] ✓ Conversion réussie: {output_path.name} ({size_gb:.2f} GB)")
            return output_path
        else:
            print(f"[GGUF] Erreur conversion (code {result.returncode})")
            if result.stdout:
                print(f"[GGUF] stdout: {result.stdout[:500]}")
            if result.stderr:
                print(f"[GGUF] stderr: {result.stderr[:500]}")
            return None

    except subprocess.TimeoutExpired:
        print("[GGUF] Timeout: conversion trop longue (>30 min)")
        return None
    except Exception as e:
        print(f"[GGUF] Erreur conversion: {e}")
        import traceback
        traceback.print_exc()
        return None


def list_convertible_models() -> list:
    """
    Liste les modèles qui peuvent être convertis en GGUF.

    Cherche dans le cache HuggingFace les modèles safetensors.
    """
    convertible = []

    # Chercher dans le cache HuggingFace
    try:
        from huggingface_hub import scan_cache_dir
        cache = scan_cache_dir()

        for repo in cache.repos:
            # Chercher les fichiers safetensors
            for rev in repo.revisions:
                for file in rev.files:
                    if file.file_name.endswith('.safetensors'):
                        convertible.append({
                            "repo": repo.repo_id,
                            "file": file.file_name,
                            "size": file.blob_size,
                            "path": str(file.file_path),
                        })
    except Exception as e:
        print(f"[GGUF] Erreur scan cache: {e}")

    return convertible


def get_conversion_status() -> dict:
    """Retourne le statut des conversions disponibles."""
    return {
        "convertible_models": list_convertible_models(),
        "output_dir": str(GGUF_DIR),
        "quantizations": QUANTIZATIONS,
    }
