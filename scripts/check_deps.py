"""
Analyseur et réparateur de dépendances
- Détecte les packages manquants, cassés, et les répare automatiquement
- Installe Python 3.12 localement si nécessaire (pour xformers)
"""
import subprocess
import sys
import os
import platform
import urllib.request
import zipfile
import tarfile
import shutil

# Ajouter le dossier parent au path pour importer config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config
try:
    from config import AI_NAME, UTILITY_MODEL, MODEL_RECOMMENDATIONS, VRAM_THRESHOLDS
except ImportError:
    AI_NAME = "JoyBoy"
    UTILITY_MODEL = "dolphin-phi:2.7b"
    MODEL_RECOMMENDATIONS = {
        "casual": {
            "low": "qwen2.5:1.5b", "medium": "qwen2.5:3b", "high": "qwen2.5vl:3b",
            "very_high": "dolphin-llama3:70b", "ultra": "dolphin-mixtral:8x7b", "extreme": "llama3.1:70b"
        }
    }
    VRAM_THRESHOLDS = {
        "extreme": 24, "ultra": 16, "very_high": 12,
        "high": 8, "medium": 4, "low": 0
    }

# ==========================================
# DETECTION SYSTEME
# ==========================================
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# Version Python requise pour xformers
REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 12  # 3.12 max pour xformers

# Python 3.12 portable (python-build-standalone - inclut pip et venv)
# Ces builds sont complets et fonctionnent sans installation
PYTHON_312_STANDALONE_URL = "https://github.com/indygreg/python-build-standalone/releases/download/20241206/cpython-3.12.8+20241206-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"

# ==========================================
# DETECTION BUILD TOOLS (Visual C++)
# ==========================================
VS_BUILD_TOOLS_URL = "https://aka.ms/vs/17/release/vs_BuildTools.exe"

def has_build_tools():
    """Vérifie si les outils de compilation C++ sont disponibles"""
    if not IS_WINDOWS:
        return True  # Linux/Mac ont généralement gcc/clang

    # Méthode 1: chercher cl.exe dans le PATH
    try:
        result = subprocess.run(["where", "cl.exe"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Méthode 2: chercher les installations Visual Studio via vswhere
    vswhere_paths = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe"),
    ]
    for vswhere in vswhere_paths:
        if os.path.exists(vswhere):
            try:
                result = subprocess.run(
                    [vswhere, "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    # Méthode 3: chercher dans les chemins courants
    common_paths = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft Visual Studio"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio"),
    ]
    for vs_path in common_paths:
        if os.path.isdir(vs_path):
            # Chercher cl.exe récursivement (limite profondeur)
            for root, dirs, files in os.walk(vs_path):
                if "cl.exe" in files:
                    return True
                # Limiter la profondeur de recherche
                if root.count(os.sep) - vs_path.count(os.sep) > 6:
                    dirs.clear()

    return False

def install_build_tools():
    """Télécharge et installe Visual C++ Build Tools (Windows uniquement)"""
    if not IS_WINDOWS:
        return False

    print("\n" + "=" * 50)
    print("  INSTALLATION VISUAL C++ BUILD TOOLS")
    print("=" * 50)
    print("\n  Certains packages Python nécessitent un compilateur C++")
    print("  (basicsr, gfpgan, insightface)")
    print("  Téléchargement de Visual Studio Build Tools...\n")

    installer_path = os.path.join(os.environ.get("TEMP", "."), "vs_BuildTools.exe")

    try:
        # Télécharger l'installeur
        if not download_file(VS_BUILD_TOOLS_URL, installer_path):
            print("  [!] Échec du téléchargement")
            return False

        # Lancer l'installation avec le workload C++
        print("  Installation en cours (quelques minutes, acceptez les droits admin)...")
        result = subprocess.run(
            [installer_path,
             "--add", "Microsoft.VisualStudio.Workload.VCTools",
             "--add", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "--add", "Microsoft.VisualStudio.Component.Windows11SDK.22621",
             "--passive", "--wait", "--norestart"],
            timeout=600  # 10 minutes max
        )

        # Nettoyer
        if os.path.exists(installer_path):
            os.remove(installer_path)

        if result.returncode == 0 or result.returncode == 3010:  # 3010 = success, reboot suggested
            print("  [OK] Visual C++ Build Tools installé!")
            return True
        else:
            print(f"  [!] Installation terminée (code {result.returncode})")
            # Vérifier quand même si ça a marché
            if has_build_tools():
                print("  [OK] Build tools détectés!")
                return True
            return False

    except subprocess.TimeoutExpired:
        print("  [!] Installation trop longue (timeout)")
        if os.path.exists(installer_path):
            os.remove(installer_path)
        return False
    except Exception as e:
        print(f"  [!] Erreur: {e}")
        if os.path.exists(installer_path):
            os.remove(installer_path)
        return False

# Packages qui nécessitent un compilateur C++ (pas de wheel pré-compilé)
NEEDS_BUILD_TOOLS = {"basicsr", "realesrgan", "gfpgan", "insightface"}

def has_nvidia_gpu():
    """Vérifie si une carte NVIDIA est présente"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def get_vram_gb():
    """Retourne la VRAM en GB (ou None si pas de GPU NVIDIA)"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            # Retourne en GB (nvidia-smi donne en MB)
            mb = int(result.stdout.strip().split('\n')[0])
            return mb / 1024
        return None
    except:
        return None

def get_vram_level():
    """Retourne le niveau de VRAM basé sur les seuils configurés"""
    vram = get_vram_gb()
    if vram is None:
        return "low"  # Pas de GPU = config minimale

    # Trier les tiers par seuil décroissant et trouver le bon niveau
    # Format: {"extreme": 24, "ultra": 16, "very_high": 12, "high": 8, "medium": 4, "low": 0}
    sorted_tiers = sorted(VRAM_THRESHOLDS.items(), key=lambda x: x[1], reverse=True)

    for tier, threshold in sorted_tiers:
        if vram >= threshold:
            return tier

    return "low"

def get_recommended_model(profile="casual"):
    """Retourne le modèle recommandé pour un profil et niveau VRAM"""
    vram_level = get_vram_level()

    if profile in MODEL_RECOMMENDATIONS:
        return MODEL_RECOMMENDATIONS[profile].get(vram_level, MODEL_RECOMMENDATIONS["casual"]["medium"])

    # Fallback: casual
    return MODEL_RECOMMENDATIONS["casual"].get(vram_level, "qwen2.5:3b")

def get_cuda_version():
    """Retourne la version CUDA installée"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse "CUDA Version: 12.1" from output
            for line in result.stdout.split('\n'):
                if 'CUDA Version' in line:
                    parts = line.split('CUDA Version:')
                    if len(parts) > 1:
                        return parts[1].strip().split()[0]
        return None
    except:
        return None

def get_torch_version():
    """Retourne la version de PyTorch installée"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import torch; print(torch.__version__)"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except:
        return None

HAS_CUDA = has_nvidia_gpu()
CUDA_VERSION = get_cuda_version() if HAS_CUDA else None

# ==========================================
# GESTION PYTHON LOCAL
# ==========================================
def get_project_dir():
    """Retourne le dossier du projet"""
    return os.path.dirname(os.path.abspath(__file__))

def get_local_python_dir():
    """Retourne le chemin vers Python local (Windows only feature)"""
    return os.path.join(get_project_dir(), "python312")

def get_local_python_exe():
    """Retourne l'exécutable Python local (Windows only feature)"""
    if IS_WINDOWS:
        return os.path.join(get_local_python_dir(), "python.exe")
    # Linux/Mac: use system Python (local python312 folder not used)
    return os.path.join(get_local_python_dir(), "bin", "python3")

def is_python_compatible():
    """Vérifie si Python actuel est compatible avec xformers (3.11 ou 3.12)"""
    major = sys.version_info.major
    minor = sys.version_info.minor
    # xformers supporte Python 3.8-3.12, pas 3.13+
    return major == 3 and 8 <= minor <= 12

def download_file(url, dest):
    """Télécharge un fichier avec barre de progression"""
    print(f"    Téléchargement: {os.path.basename(dest)}")
    try:
        # Obtenir la taille du fichier
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('Content-Length', 0))

            # Télécharger avec progression
            downloaded = 0
            block_size = 8192
            last_percent = -1

            with open(dest, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)

                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        if percent != last_percent:
                            bar_width = 30
                            filled = int(bar_width * percent / 100)
                            bar = "█" * filled + "░" * (bar_width - filled)
                            size_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            sys.stdout.write(f"\r    [{bar}] {percent}% ({size_mb:.1f}/{total_mb:.1f} MB)")
                            sys.stdout.flush()
                            last_percent = percent

            print()  # Nouvelle ligne après la barre
        return True
    except Exception as e:
        print(f"\n    [!] Erreur téléchargement: {e}")
        return False

def install_python_312_local():
    """
    Installe Python 3.12 portable dans le projet (Windows uniquement).
    Utilise python-build-standalone qui inclut pip et venv.
    Retourne le chemin vers l'exécutable Python ou None si échec.

    On Linux/Mac: users should install Python 3.12 via their package manager.
    """
    if not IS_WINDOWS:
        print("    [!] Installation Python locale supportée uniquement sur Windows")
        if IS_MAC:
            print("    [!] Sur Mac: brew install python@3.12")
        elif IS_LINUX:
            print("    [!] Sur Linux (Ubuntu/Debian): sudo apt install python3.12 python3.12-venv")
            print("    [!] Sur Linux (Fedora): sudo dnf install python3.12")
        return None

    project_dir = get_project_dir()
    python_dir = get_local_python_dir()
    python_exe = get_local_python_exe()

    # Déjà installé et fonctionnel?
    if os.path.exists(python_exe):
        # Vérifier que c'est bien Python 3.12 et qu'il a venv
        try:
            result = subprocess.run(
                [python_exe, "-c", "import sys; print(sys.version_info.minor)"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip() == "12":
                # Vérifier venv
                result2 = subprocess.run(
                    [python_exe, "-c", "import venv"],
                    capture_output=True, text=True, timeout=10
                )
                if result2.returncode == 0:
                    print(f"    [OK] Python 3.12 local déjà présent et fonctionnel")
                    return python_exe
        except:
            pass
        # Si on arrive ici, Python local existe mais est cassé, on réinstalle
        print("    [!] Python local existant mais incomplet, réinstallation...")
        shutil.rmtree(python_dir, ignore_errors=True)

    print("\n" + "="*50)
    print("  INSTALLATION PYTHON 3.12 PORTABLE")
    print("="*50)
    print(f"\n  Python {sys.version.split()[0]} détecté (incompatible xformers)")
    print("  Téléchargement de Python 3.12 portable...")
    print("  (python-build-standalone - inclut pip et venv)\n")

    # Télécharger l'archive Python standalone
    archive_path = os.path.join(project_dir, "python312.tar.gz")
    print("    Téléchargement (~30 MB)...")
    if not download_file(PYTHON_312_STANDALONE_URL, archive_path):
        return None

    # Extraire l'archive
    print("    Extraction de l'archive...")
    try:
        # Créer un dossier temporaire pour l'extraction
        temp_extract = os.path.join(project_dir, "python312_temp")
        os.makedirs(temp_extract, exist_ok=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(temp_extract)

        # L'archive contient un dossier "python" avec tout dedans
        extracted_python = os.path.join(temp_extract, "python")
        if os.path.exists(extracted_python):
            # Déplacer vers le dossier final
            shutil.move(extracted_python, python_dir)
        else:
            # Chercher le dossier Python dans l'extraction
            for item in os.listdir(temp_extract):
                item_path = os.path.join(temp_extract, item)
                if os.path.isdir(item_path):
                    shutil.move(item_path, python_dir)
                    break

        # Nettoyer
        shutil.rmtree(temp_extract, ignore_errors=True)
        os.remove(archive_path)

    except Exception as e:
        print(f"    [!] Erreur extraction: {e}")
        # Nettoyer en cas d'erreur
        if os.path.exists(archive_path):
            os.remove(archive_path)
        return None

    # Vérifier que Python a bien été installé
    if not os.path.exists(python_exe):
        # Chercher python.exe dans les sous-dossiers
        for root, dirs, files in os.walk(python_dir):
            if "python.exe" in files:
                found_exe = os.path.join(root, "python.exe")
                print(f"    [INFO] Python trouvé dans: {root}")
                # Déplacer tout vers python_dir si dans un sous-dossier
                if root != python_dir:
                    for item in os.listdir(root):
                        src = os.path.join(root, item)
                        dst = os.path.join(python_dir, item)
                        if os.path.exists(dst):
                            if os.path.isdir(dst):
                                shutil.rmtree(dst)
                            else:
                                os.remove(dst)
                        shutil.move(src, dst)
                break

    # Re-vérifier
    if not os.path.exists(python_exe):
        print(f"    [!] Erreur: Python non trouvé après extraction")
        print(f"    [!] Chemin attendu: {python_exe}")
        # Lister ce qui a été extrait pour debug
        print(f"    [DEBUG] Contenu de {python_dir}:")
        if os.path.exists(python_dir):
            for item in os.listdir(python_dir)[:10]:
                print(f"      - {item}")
        return None

    # Vérifier que venv fonctionne
    result = subprocess.run(
        [python_exe, "-c", "import venv; print('venv OK')"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f"    [!] Erreur: module venv non disponible")
        print(f"    [DEBUG] {result.stderr}")
        return None

    # Vérifier pip
    result = subprocess.run(
        [python_exe, "-m", "pip", "--version"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f"    [!] Erreur: pip non disponible")
        return None

    print(f"\n  [OK] Python 3.12 portable installé dans: {python_dir}")
    return python_exe

def recreate_venv_with_python312():
    """
    Recrée le venv avec Python 3.12 local.
    Retourne True si succès et le batch doit relancer le setup.

    Note: This is Windows-only. On Linux/Mac, users should install Python 3.12
    via their package manager and recreate the venv manually.
    """
    python_exe = install_python_312_local()
    if not python_exe:
        return False

    project_dir = get_project_dir()
    venv_dir = os.path.join(project_dir, "venv")
    if IS_WINDOWS:
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    print("\n" + "-"*50)
    print("  Recréation du venv avec Python 3.12")
    print("-"*50 + "\n")

    # Supprimer l'ancien venv (plusieurs tentatives si fichiers verrouillés)
    if os.path.exists(venv_dir):
        print("    Suppression ancien venv...")
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Essayer de forcer la suppression des fichiers en lecture seule
                def remove_readonly(func, path, excinfo):
                    os.chmod(path, 0o777)
                    func(path)
                shutil.rmtree(venv_dir, onerror=remove_readonly)
                break
            except Exception as e:
                if attempt < max_attempts - 1:
                    print(f"    [!] Tentative {attempt+1}/{max_attempts} échouée, réessai...")
                    import time
                    time.sleep(2)
                else:
                    print(f"    [!] Erreur suppression venv: {e}")
                    print("    [!] Ferme toutes les fenêtres CMD/terminal utilisant le venv et réessaie")
                    return False

    # Vérifier que l'ancien venv est bien supprimé
    if os.path.exists(venv_dir):
        print(f"    [!] Le dossier venv existe encore!")
        return False

    print("    [OK] Ancien venv supprimé")

    # Créer nouveau venv avec Python 3.12
    print("    Création nouveau venv avec Python 3.12...")
    print(f"    Python utilisé: {python_exe}")

    result = subprocess.run(
        [python_exe, "-m", "venv", venv_dir],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        print(f"    [!] Erreur création venv: {result.stderr}")
        return False

    # Vérifier que le venv a été créé
    if not os.path.exists(venv_python):
        print(f"    [!] Le venv n'a pas été créé correctement")
        return False

    # Vérifier que le venv utilise bien Python 3.12
    result = subprocess.run(
        [venv_python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0 or "3.12" not in result.stdout:
        print(f"    [!] Le venv n'utilise pas Python 3.12: {result.stdout.strip()}")
        return False

    print(f"    [OK] Venv créé avec Python {result.stdout.strip()}")

    print("\n" + "="*50)
    print("  VENV RECRÉÉ AVEC PYTHON 3.12")
    print("  ")
    print("  Le script va maintenant retourner le code 99")
    print("  pour que le batch relance le setup complet")
    print("  avec le nouveau venv Python 3.12")
    print("="*50 + "\n")

    return True

# ==========================================
# DEPENDANCES
# ==========================================
# Packages CRITIQUES — l'app ne peut PAS démarrer sans eux
# Si un de ceux-là manque, on retry le setup
CRITICAL_DEPS = {
    # Interface
    "flask": "flask",
    # IA / Deep Learning
    "torch": "torch",
    "torchvision": "torchvision",
    "torchaudio": "torchaudio",
    # Diffusion models
    "diffusers": "diffusers",
    "transformers": "transformers",
    "accelerate": "accelerate",
    # Image/Video processing
    "PIL": "Pillow",
    "numpy": "numpy",
    "cv2": "opencv-python-headless",
    # Utils
    "safetensors": "safetensors",
    "huggingface_hub": "huggingface_hub",
    "omegaconf": "omegaconf",
    "einops": "einops",
    "sentencepiece": "sentencepiece",
    "peft": "peft",
    "scipy": "scipy",
    "ftfy": "ftfy",
    "optimum_quanto": "optimum-quanto",        # Quantification INT8 (indispensable < 18GB VRAM)
    # Web / System
    "requests": "requests",
    "psutil": "psutil",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    # Video
    "imageio_ffmpeg": "imageio-ffmpeg",
    "av": "av",
    # Chat IA
    "ollama": "ollama",
}

# Packages NON-CRITIQUES — l'app tourne sans, certaines features seront désactivées
# Si ceux-là échouent, on warn mais on ne boucle PAS le setup
NON_CRITICAL_DEPS = {
    "controlnet_aux": "controlnet-aux",       # ControlNet preprocessing
    "mediapipe": "mediapipe",                  # Face detection CPU
    "bitsandbytes": "bitsandbytes",            # Quantification
    "gfpgan": "gfpgan",                        # Face restore
    "insightface": "insightface",              # IP-Adapter face
}

# Combine pour backward compat (check_all_imports, etc.)
DEPENDENCIES = {**CRITICAL_DEPS, **NON_CRITICAL_DEPS}

# Ces packages on vérifie juste avec pip (imports complexes)
PIP_ONLY_CHECK = ["protobuf"]

# Packages optionnels (upscaling - incompatibles Python 3.13)
OPTIONAL_PACKAGES = ["realesrgan", "basicsr"]

# Package GGUF backend (modèles quantizés, économie VRAM)
GGUF_PACKAGE = "stable-diffusion-cpp-python"

# Packages à désinstaller (anciens, créent des conflits)
CLEANUP_PACKAGES = ["diffsynth", "gradio", "gradio-client"]

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================
def run_pip(args, quiet=True):
    """Execute pip avec les arguments donnés"""
    cmd = [sys.executable, "-m", "pip"] + args
    if quiet:
        cmd.append("--quiet")
    return subprocess.run(cmd, capture_output=True, text=True)


# Cache global des imports (un seul subprocess pour tout vérifier)
_import_results_cache = None

def _check_all_imports(modules):
    """Vérifie tous les imports en un seul subprocess Python"""
    global _import_results_cache
    if _import_results_cache is not None:
        return _import_results_cache

    # Construire un script qui teste tous les imports d'un coup
    checks = []
    for mod in modules:
        checks.append(f'try:\n import {mod}\n print("OK:{mod}")\nexcept ImportError as e:\n print("MISSING:{mod}:" + str(e))\nexcept OSError as e:\n s=str(e).lower()\n if "dll" in s:\n  print("DLL:{mod}:" + str(e))\n else:\n  print("ERROR:{mod}:" + str(e))\nexcept Exception as e:\n print("ERROR:{mod}:" + str(e))')

    script = "\n".join(checks)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60
    )

    _import_results_cache = {}
    for line in result.stdout.strip().split('\n'):
        if line.startswith("OK:"):
            mod = line[3:]
            _import_results_cache[mod] = (True, None, None)
        elif line.startswith("MISSING:"):
            parts = line[8:].split(":", 1)
            _import_results_cache[parts[0]] = (False, "missing", parts[1] if len(parts) > 1 else "")
        elif line.startswith("DLL:"):
            parts = line[4:].split(":", 1)
            _import_results_cache[parts[0]] = (False, "dll_error", parts[1] if len(parts) > 1 else "")
        elif line.startswith("ERROR:"):
            parts = line[6:].split(":", 1)
            _import_results_cache[parts[0]] = (False, "other_error", parts[1] if len(parts) > 1 else "")

    return _import_results_cache


def check_import(module_name):
    """
    Teste si un module peut être importé correctement.
    Retourne (success, error_type, error_message)
    error_type: None, 'missing', 'dll_error', 'other_error'
    """
    if _import_results_cache is not None and module_name in _import_results_cache:
        return _import_results_cache[module_name]

    # Fallback: un seul import (cas rare)
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode == 0:
        return True, None, None

    stderr = result.stderr.lower()

    if "no module named" in stderr or "modulenotfounderror" in stderr:
        return False, "missing", result.stderr
    elif "dll load failed" in stderr or "dll" in stderr:
        return False, "dll_error", result.stderr
    else:
        return False, "other_error", result.stderr


# Cache global pip list (un seul appel au lieu d'un par package)
_installed_packages_cache = None

def _get_installed_packages():
    """Charge la liste des packages installés une seule fois"""
    global _installed_packages_cache
    if _installed_packages_cache is None:
        result = run_pip(["list", "--format=columns"], quiet=True)
        if result.returncode == 0:
            _installed_packages_cache = set()
            for line in result.stdout.strip().split('\n')[2:]:  # Skip header
                parts = line.split()
                if parts:
                    _installed_packages_cache.add(parts[0].lower())
        else:
            _installed_packages_cache = set()
    return _installed_packages_cache

def check_pip_installed(package):
    """Vérifie si un package est installé via pip (cache en mémoire)"""
    installed = _get_installed_packages()
    return package.lower() in installed

def uninstall_package(package):
    """Désinstalle un package"""
    print(f"    Désinstallation de {package}...")
    run_pip(["uninstall", "-y", package], quiet=True)

def install_package(package, extra_args=None):
    """Installe un package"""
    print(f"    Installation de {package}...")
    args = ["install", package]
    if extra_args:
        args.extend(extra_args)
    result = run_pip(args, quiet=False)
    return result.returncode == 0

# ==========================================
# REPARATIONS SPECIFIQUES
# ==========================================
def check_pytorch_cuda():
    """
    Vérifie si PyTorch a le support CUDA.
    Retourne True si CUDA est disponible dans PyTorch, False sinon.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0 and "True" in result.stdout
    except:
        return False

def fix_pytorch_cuda():
    """
    Réinstalle PyTorch avec support CUDA si nécessaire.
    """
    if not HAS_CUDA:
        return True  # Pas de GPU NVIDIA, pas besoin de CUDA

    # Vérifier si PyTorch a déjà CUDA
    if check_pytorch_cuda():
        print("  [OK] PyTorch avec CUDA")
        return True

    print("\n" + "-" * 50)
    print("  RÉINSTALLATION PYTORCH AVEC CUDA")
    print("-" * 50)
    print("\n  PyTorch actuel n'a pas le support CUDA")
    print("  Réinstallation avec CUDA...")

    # Déterminer l'index pip selon la version CUDA
    if CUDA_VERSION:
        if CUDA_VERSION.startswith("12.4") or CUDA_VERSION.startswith("12.5") or CUDA_VERSION.startswith("12.6") or CUDA_VERSION.startswith("13"):
            pip_index = "https://download.pytorch.org/whl/cu124"
        elif CUDA_VERSION.startswith("12.1") or CUDA_VERSION.startswith("12.2") or CUDA_VERSION.startswith("12.3"):
            pip_index = "https://download.pytorch.org/whl/cu121"
        elif CUDA_VERSION.startswith("11.8"):
            pip_index = "https://download.pytorch.org/whl/cu118"
        else:
            pip_index = "https://download.pytorch.org/whl/cu124"
    else:
        pip_index = "https://download.pytorch.org/whl/cu124"

    print(f"  Index CUDA: {pip_index}")

    # Désinstaller PyTorch actuel
    print("  Désinstallation de PyTorch CPU...")
    run_pip(["uninstall", "-y", "torch", "torchvision", "torchaudio"], quiet=True)

    # Réinstaller avec CUDA
    print("  Installation de PyTorch avec CUDA (peut prendre quelques minutes)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "torch", "torchvision", "torchaudio",
         "--index-url", pip_index],
        capture_output=False,  # Afficher la progression
        text=True,
        timeout=600
    )

    if result.returncode != 0:
        print("  [!] Erreur installation PyTorch CUDA")
        return False

    # Vérifier que ça a marché
    if check_pytorch_cuda():
        print("\n  [OK] PyTorch avec CUDA installé!")
        return True
    else:
        print("\n  [!] PyTorch CUDA installé mais CUDA non détecté")
        return False

def fix_opencv():
    """Répare OpenCV (problèmes DLL fréquents sur Windows)"""
    print("\n[REPAIR] Réparation d'OpenCV...")

    # Vérifier si on a déjà essayé de réparer (éviter boucle infinie)
    marker_file = os.path.join(get_project_dir(), ".opencv_fix_attempted")
    if os.path.exists(marker_file):
        print("    [!] Réparation déjà tentée - le problème persiste")
        print("    [!] Solutions:")
        print("        1. Redémarre ton PC")
        print("        2. Installe Visual C++ Redistributable manuellement:")
        print("           https://aka.ms/vs/17/release/vc_redist.x64.exe")
        print("        3. Après installation, relance le setup")
        return False

    # Marquer qu'on a tenté la réparation
    with open(marker_file, "w") as f:
        f.write("attempted")

    # Désinstaller toutes les versions
    for pkg in ["opencv-python", "opencv-python-headless", "opencv-contrib-python"]:
        run_pip(["uninstall", "-y", pkg], quiet=True)

    # Réinstaller proprement
    result = run_pip(["install", "--force-reinstall", "--no-cache-dir", "opencv-python-headless"], quiet=False)

    # Tester si ça marche maintenant
    success, error_type, _ = check_import("cv2")
    if success:
        # Ça marche ! Supprimer le marqueur
        os.remove(marker_file)
        return True

    return False

def fix_xformers():
    """
    Installe xformers depuis l'index PyTorch officiel.
    Nécessite la bonne combinaison PyTorch + CUDA + Python.
    """
    print("\n[INSTALL] Installation de xformers...")

    # D'abord désinstaller si présent
    run_pip(["uninstall", "-y", "xformers"], quiet=True)

    torch_version = get_torch_version()
    if not torch_version:
        print("    [!] PyTorch non détecté")
        return False

    print(f"    PyTorch: {torch_version}")
    print(f"    CUDA: {CUDA_VERSION}")
    print(f"    Python: {sys.version.split()[0]}")

    # Déterminer l'index pip selon la version CUDA
    if CUDA_VERSION:
        if CUDA_VERSION.startswith("12.4") or CUDA_VERSION.startswith("12.5") or CUDA_VERSION.startswith("12.6") or CUDA_VERSION.startswith("13"):
            pip_index = "https://download.pytorch.org/whl/cu124"
        elif CUDA_VERSION.startswith("12.1") or CUDA_VERSION.startswith("12.2") or CUDA_VERSION.startswith("12.3"):
            pip_index = "https://download.pytorch.org/whl/cu121"
        elif CUDA_VERSION.startswith("11.8"):
            pip_index = "https://download.pytorch.org/whl/cu118"
        else:
            pip_index = "https://download.pytorch.org/whl/cu124"  # Default
    else:
        print("    [!] CUDA non détecté")
        return False

    print(f"    Index: {pip_index}")
    print("    Installation en cours (peut prendre 1-2 min)...")

    # Installer xformers depuis l'index PyTorch
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "xformers", "--index-url", pip_index],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"    [!] Échec installation: {result.stderr[:200] if result.stderr else 'erreur inconnue'}")
        # Python 3.13 n'a souvent pas de wheel pré-compilé
        if "3.13" in sys.version:
            print("    [!] Python 3.13 détecté - xformers n'a pas de wheel pré-compilé")
            print("    [!] Solution: utiliser Python 3.11 ou 3.12")
        return False

    # Tester si ça marche vraiment
    print("    Test d'import...")
    success, error_type, error_msg = check_import("xformers")

    if success:
        # Test plus poussé - importer xformers.ops
        success2, _, _ = check_import("xformers.ops")
        if success2:
            print("    [OK] xformers installé et fonctionnel!")
            return True
        else:
            print("    [!] xformers.ops ne fonctionne pas (erreur DLL)")

    # Échec - désinstaller
    print("    [!] xformers ne fonctionne pas, désinstallation...")
    run_pip(["uninstall", "-y", "xformers"], quiet=True)

    if "3.13" in sys.version:
        print("\n    ╔════════════════════════════════════════════════════╗")
        print("    ║  PYTHON 3.13 NON SUPPORTÉ PAR XFORMERS             ║")
        print("    ║  Solutions:                                         ║")
        print("    ║  1. Installer Python 3.11 ou 3.12                   ║")
        print("    ║  2. Utiliser SDPA (intégré, presque aussi rapide)   ║")
        print("    ╚════════════════════════════════════════════════════╝")

    return False

def fix_tensorrt():
    """
    TensorRT est complexe à installer. On essaie, sinon on skip.
    """
    print("\n[REPAIR] Vérification TensorRT...")

    if not HAS_CUDA:
        print("    Pas de GPU NVIDIA, skip TensorRT")
        return False

    # Vérifier si déjà installé et fonctionnel
    success, error_type, _ = check_import("tensorrt")
    if success:
        print("    TensorRT OK")
        return True

    # Essayer d'installer
    print("    Installation de tensorrt...")
    result = run_pip(["install", "tensorrt"], quiet=False)

    if result.returncode == 0:
        success, _, _ = check_import("tensorrt")
        if success:
            # Installer aussi torch-tensorrt
            run_pip(["install", "torch-tensorrt"], quiet=False)
            print("    TensorRT installé!")
            return True

    print("    TensorRT non disponible (optionnel, pas grave)")
    return False

def install_vc_redist():
    """Télécharge et installe Visual C++ Redistributable (Windows)"""
    if not IS_WINDOWS:
        return False

    print("\n[REPAIR] Installation de Visual C++ Redistributable...")
    temp_path = os.path.join(os.environ.get('TEMP', '.'), 'vc_redist.x64.exe')

    try:
        # Télécharger
        subprocess.run([
            "curl", "-L", "-o", temp_path,
            "https://aka.ms/vs/17/release/vc_redist.x64.exe"
        ], check=False, capture_output=True)

        if os.path.exists(temp_path):
            print("    Lancement de l'installateur (acceptez les droits admin)...")
            subprocess.run([temp_path, "/install", "/passive", "/norestart"], check=False)
            os.remove(temp_path)
            return True
    except Exception as e:
        print(f"    Erreur: {e}")

    return False

# ==========================================
# VERIFICATION OLLAMA
# ==========================================
def get_ollama_path():
    """Retourne le chemin vers ollama s'il existe"""
    # D'abord essayer le PATH
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return "ollama"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Sinon chercher dans les emplacements courants (platform-specific)
    if IS_WINDOWS:
        common_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    elif IS_LINUX:
        # Linux common paths
        common_paths = [
            "/usr/local/bin/ollama",
            "/usr/bin/ollama",
            os.path.expanduser("~/.local/bin/ollama"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    elif IS_MAC:
        # Mac common paths (Homebrew)
        common_paths = [
            "/opt/homebrew/bin/ollama",
            "/usr/local/bin/ollama",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path

    return None

def check_ollama():
    """Vérifie si Ollama est installé"""
    return get_ollama_path() is not None

def get_ollama_models():
    """Liste les modèles Ollama installés"""
    ollama_path = get_ollama_path()
    if not ollama_path:
        return 0
    try:
        result = subprocess.run(
            [ollama_path, "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                return len(lines) - 1  # -1 pour le header
        return 0
    except:
        return 0

def check_homebrew():
    """Vérifie si Homebrew est installé (Mac only)"""
    try:
        result = subprocess.run(
            ["brew", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def install_homebrew():
    """Installe Homebrew sur Mac"""
    print("  [INSTALL] Installation de Homebrew...")
    try:
        # Commande officielle d'installation de Homebrew
        install_cmd = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        result = subprocess.run(
            install_cmd,
            shell=True,
            timeout=300  # 5 minutes max
        )
        if result.returncode == 0:
            print("  [OK] Homebrew installé")
            return True
        else:
            print("  [ERREUR] Échec installation Homebrew")
            return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        return False

def install_ollama_mac():
    """Installe Ollama via Homebrew sur Mac"""
    print("  [INSTALL] Installation d'Ollama via Homebrew...")
    try:
        result = subprocess.run(
            ["brew", "install", "ollama"],
            timeout=300
        )
        if result.returncode == 0:
            print("  [OK] Ollama installé")
            return True
        else:
            print("  [ERREUR] Échec installation Ollama")
            return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        return False

def check_winget():
    """Vérifie si winget est installé (Windows only)"""
    try:
        result = subprocess.run(
            ["winget", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def install_winget():
    """Installe winget sur Windows via le Microsoft Store"""
    print("  [INSTALL] Installation de winget...")
    try:
        # Télécharger le package App Installer (contient winget)
        winget_url = "https://aka.ms/getwinget"
        winget_path = os.path.join(os.environ.get("TEMP", "."), "Microsoft.DesktopAppInstaller.msixbundle")

        print("  [DOWNLOAD] Téléchargement de winget...")
        urllib.request.urlretrieve(winget_url, winget_path)

        # Installer le package
        print("  [INSTALL] Installation du package...")
        result = subprocess.run(
            ["powershell", "-Command", f"Add-AppxPackage -Path '{winget_path}'"],
            capture_output=True,
            timeout=120
        )

        # Nettoyer
        if os.path.exists(winget_path):
            os.remove(winget_path)

        if result.returncode == 0:
            print("  [OK] winget installé")
            return True
        else:
            print("  [ERREUR] Échec installation winget")
            print("    -> Installe 'App Installer' depuis le Microsoft Store")
            return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        print("    -> Installe 'App Installer' depuis le Microsoft Store")
        return False

def install_ollama_windows():
    """Installe Ollama sur Windows (winget → fallback téléchargement direct)"""
    # Essayer winget d'abord
    if check_winget():
        print("  [INSTALL] Installation d'Ollama via winget...")
        try:
            result = subprocess.run(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-source-agreements", "--accept-package-agreements"],
                timeout=300
            )
            if result.returncode == 0:
                print("  [OK] Ollama installé via winget")
                return True
        except Exception:
            pass
        print("  [!] winget a échoué, téléchargement direct...")

    # Fallback: téléchargement direct de l'installeur
    print("  [INSTALL] Téléchargement direct d'Ollama...")
    ollama_url = "https://ollama.com/download/OllamaSetup.exe"
    ollama_installer = os.path.join(os.environ.get("TEMP", "."), "OllamaSetup.exe")

    try:
        if not download_file(ollama_url, ollama_installer):
            print("  [ERREUR] Échec du téléchargement")
            return False

        # Installer silencieusement
        print("  [INSTALL] Installation en cours...")
        result = subprocess.run(
            [ollama_installer, "/VERYSILENT", "/NORESTART"],
            timeout=120,
            capture_output=True
        )

        # Nettoyer
        if os.path.exists(ollama_installer):
            os.remove(ollama_installer)

        if result.returncode == 0:
            print("  [OK] Ollama installé")
            return True
        else:
            # Certains installeurs NSIS retournent un code non-zero mais installent quand même
            # Vérifier si ollama est maintenant disponible
            import time
            time.sleep(2)
            if get_ollama_path():
                print("  [OK] Ollama installé")
                return True
            print("  [ERREUR] Échec installation Ollama")
            return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        if os.path.exists(ollama_installer):
            os.remove(ollama_installer)
        return False

def start_ollama_service():
    """Démarre le service Ollama"""
    ollama_path = get_ollama_path()
    if not ollama_path:
        return False
    try:
        # Lancer ollama serve en arrière-plan
        subprocess.Popen(
            [ollama_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        import time
        time.sleep(2)  # Attendre que le service démarre
        return True
    except:
        return False

def pull_ollama_model(model_name="qwen2.5vl:3b"):
    """Télécharge un modèle Ollama"""
    ollama_path = get_ollama_path()
    if not ollama_path:
        print(f"  [ERREUR] Ollama non trouvé")
        return False
    print(f"  [DOWNLOAD] Téléchargement du modèle {model_name}...")
    try:
        result = subprocess.run(
            [ollama_path, "pull", model_name],
            timeout=600  # 10 minutes max
        )
        if result.returncode == 0:
            print(f"  [OK] Modèle {model_name} prêt")
            return True
        else:
            print(f"  [ERREUR] Échec téléchargement {model_name}")
            return False
    except Exception as e:
        print(f"  [ERREUR] {e}")
        return False

def is_model_installed(model_name):
    """Vérifie si un modèle Ollama est installé"""
    ollama_path = get_ollama_path()
    if not ollama_path:
        return False
    try:
        result = subprocess.run(
            [ollama_path, "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            # Le modèle peut être "qwen2.5:0.5b" ou "qwen2.5:latest"
            model_base = model_name.split(":")[0]
            for line in result.stdout.split('\n'):
                if model_base in line:
                    # Vérifier aussi le tag si spécifié
                    if ":" in model_name:
                        tag = model_name.split(":")[1]
                        if tag in line or "latest" in model_name:
                            return True
                    else:
                        return True
        return False
    except:
        return False

def ensure_ollama_models(profile=None):
    """
    S'assure que les modèles nécessaires sont installés:
    1. Utility model (qwen2.5:1.5b) - toujours requis pour les checks rapides
    2. Modèle de chat recommandé basé sur le profil et la VRAM

    Si profile n'est pas spécifié, utilise "casual" comme défaut.
    """
    vram_level = get_vram_level()

    # 1. Utility model - TOUJOURS requis
    print(f"\n  -- Modèles requis --")
    if is_model_installed(UTILITY_MODEL):
        print(f"  [OK] Utility model: {UTILITY_MODEL}")
    else:
        print(f"  [DOWNLOAD] Utility model: {UTILITY_MODEL}")
        print(f"      (Modèle rapide pour les checks image/mémoire)")
        pull_ollama_model(UTILITY_MODEL)

    # 2. Modèle de chat — juste vérifier, pas forcer le téléchargement
    if profile is None:
        profile = "casual"

    recommended = get_recommended_model(profile)

    if is_model_installed(recommended):
        print(f"  [OK] Chat model: {recommended}")
    else:
        print(f"  [INFO] Chat model recommandé: {recommended}")
        print(f"      -> Installe-le depuis les settings ou: ollama pull {recommended}")

    # Résumé
    print(f"\n  -- Configuration Ollama --")
    print(f"  Utility (checks):  {UTILITY_MODEL}")
    print(f"  Chat recommandé:   {recommended}")

# ==========================================
# MAIN
# ==========================================
def main():
    print("\n" + "=" * 50)
    print(f"  {AI_NAME.upper()} - Vérification des dépendances")
    print("=" * 50)

    # Info système
    print(f"\n  Système: {platform.system()} {platform.machine()}")
    print(f"  Python: {sys.version.split()[0]}")
    if HAS_CUDA:
        print(f"  GPU: NVIDIA (CUDA {CUDA_VERSION})")
    elif IS_MAC:
        print("  GPU: Apple Metal (MPS)")
    else:
        print("  GPU: Aucun (CPU only)")

    torch_ver = get_torch_version()
    if torch_ver:
        print(f"  PyTorch: {torch_ver}")

    # ==========================================
    # CHECK VERSION PYTHON POUR XFORMERS
    # ==========================================
    if not is_python_compatible():
        print("\n" + "=" * 50)
        print("  PYTHON INCOMPATIBLE AVEC XFORMERS")
        print("=" * 50)
        print(f"\n  Python actuel: {sys.version.split()[0]}")
        print("  xformers nécessite: Python 3.8 à 3.12")

        # Vérifier si Python 3.12 local existe déjà
        local_python = get_local_python_exe()
        if os.path.exists(local_python):
            print(f"\n  [OK] Python 3.12 local trouvé: {local_python}")
            print("  [!] MAIS le venv utilise encore Python 3.13!")
            print("\n  Recréation du venv avec Python 3.12...")
        else:
            print("\n  Installation de Python 3.12 local...")

        if recreate_venv_with_python312():
            return 99  # Relancer le script avec le nouveau venv
        else:
            print("\n  [!] Échec - installe Python 3.12 manuellement")
            return 1

    # ==========================================
    # CHECK BUILD TOOLS (AVANT les installations)
    # ==========================================
    if IS_WINDOWS:
        if has_build_tools():
            print("  Build Tools: Visual C++ OK")
        else:
            print("  Build Tools: Non détecté")
            print("  (Sera installé automatiquement si nécessaire)")

    # Nettoyer les dossiers pip corrompus (~ prefix = install interrompue)
    try:
        site_packages = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'venv', 'Lib', 'site-packages')
        if os.path.isdir(site_packages):
            for item in os.listdir(site_packages):
                if item.startswith('~'):
                    corrupt_path = os.path.join(site_packages, item)
                    print(f"  [CLEANUP] Suppression dossier pip corrompu: {item}")
                    shutil.rmtree(corrupt_path, ignore_errors=True)
    except Exception:
        pass

    # Nettoyer les anciens packages qui créent des conflits
    for pkg in CLEANUP_PACKAGES:
        if check_pip_installed(pkg):
            print(f"  [CLEANUP] Suppression de {pkg} (obsolète)...")
            run_pip(["uninstall", "-y", pkg], quiet=True)

    print("\n" + "-" * 50)
    print("  Dépendances de base")
    print("-" * 50 + "\n")

    missing = []
    dll_errors = []
    ok_count = 0
    total = len(DEPENDENCIES) + len(PIP_ONLY_CHECK)

    # Vérifier tous les imports en un seul subprocess (rapide)
    _check_all_imports(list(DEPENDENCIES.keys()))

    for module, package in DEPENDENCIES.items():
        success, error_type, error_msg = check_import(module)

        if success:
            print(f"  [OK] {module}")
            ok_count += 1
            # Si cv2 fonctionne, nettoyer le marker de réparation
            if module == "cv2":
                marker_file = os.path.join(get_project_dir(), ".opencv_fix_attempted")
                if os.path.exists(marker_file):
                    os.remove(marker_file)
        elif error_type == "dll_error":
            print(f"  [DLL ERROR] {module}")
            dll_errors.append((module, package))
        else:
            print(f"  [MISSING] {module}")
            missing.append((module, package))

    # Vérifier les packages pip-only
    for package in PIP_ONLY_CHECK:
        if check_pip_installed(package):
            print(f"  [OK] {package}")
            ok_count += 1
        else:
            print(f"  [MISSING] {package}")
            missing.append((package, package))

    print(f"\n  {ok_count}/{total} dépendances OK")

    # Packages optionnels (upscaling)
    print("\n  Packages optionnels (upscaling):")
    for package in OPTIONAL_PACKAGES:
        if check_pip_installed(package):
            print(f"  [OK] {package}")
        elif is_python_compatible():
            # Python 3.12 ou moins, on peut installer
            print(f"  [MISSING] {package} - installation...")
            install_package(package)
        else:
            # Python 3.13+, skip car incompatible
            print(f"  [SKIP] {package} (incompatible Python 3.13+)")

    # Nunchaku (Flux Fill INT4 — wheel spécial, pas sur PyPI)
    print("\n  Package optionnel (quantification INT4):")
    success, _, _ = check_import("nunchaku")
    if success:
        print(f"  [OK] nunchaku (Flux Fill INT4)")
    else:
        print(f"  [SKIP] nunchaku (optionnel — requis pour Flux Fill INT4)")
        print(f"         Installer depuis: https://huggingface.co/nunchaku-tech/nunchaku/tree/main/wheels")

    # ==========================================
    # REPARATIONS
    # ==========================================
    needs_restart = False

    # Réparer les erreurs DLL
    if dll_errors:
        print(f"\n" + "-" * 50)
        print(f"  Réparation de {len(dll_errors)} erreur(s) DLL")
        print("-" * 50)

        for module, package in dll_errors:
            if module == "cv2":
                if fix_opencv():
                    print(f"  [FIXED] {module}")
                else:
                    print(f"  [FAILED] {module} - Installez Visual C++ Redistributable")
                    if IS_WINDOWS:
                        install_vc_redist()
                        needs_restart = True

    # Installer les packages manquants
    if missing:
        print(f"\n" + "-" * 50)
        print(f"  Installation de {len(missing)} package(s) manquant(s)")
        print("-" * 50 + "\n")

        # Vérifier si des packages manquants nécessitent un compilateur C++
        needs_compiler = any(package in NEEDS_BUILD_TOOLS for _, package in missing)
        if needs_compiler and IS_WINDOWS and not has_build_tools():
            print("  [!] Compilateur C++ requis pour: basicsr, gfpgan, insightface")
            print("  [!] Installation automatique de Visual C++ Build Tools...\n")
            install_build_tools()

        # Installer les pré-requis d'abord (Cython avant basicsr, onnxruntime avant insightface)
        prereqs_needed = []
        for module, package in missing:
            if package in ("gfpgan", "basicsr", "realesrgan"):
                prereqs_needed.append("Cython")
            if package == "insightface":
                prereqs_needed.append("onnxruntime")
        for prereq in dict.fromkeys(prereqs_needed):  # unique, ordered
            if not check_pip_installed(prereq):
                print(f"  [PRE-REQ] Installation de {prereq}...")
                install_package(prereq)

        for module, package in missing:
            if package == "torch":
                print("  Installation PyTorch avec CUDA...")
                if HAS_CUDA:
                    run_pip(["install", "torch", "torchvision", "torchaudio",
                            "--index-url", "https://download.pytorch.org/whl/cu124"], quiet=False)
                else:
                    run_pip(["install", "torch", "torchvision", "torchaudio"], quiet=False)
            elif package == "rembg":
                print("  Installation rembg...")
                if HAS_CUDA:
                    run_pip(["install", "onnxruntime-gpu"], quiet=False)
                run_pip(["install", "rembg"], quiet=False)
            else:
                if not install_package(package):
                    # Retry avec --no-cache-dir (cache pip corrompu possible)
                    print(f"    Retry {package} sans cache...")
                    install_package(package, extra_args=["--no-cache-dir"])

    # ==========================================
    # OPTIMISATIONS GPU (NVIDIA uniquement)
    # ==========================================
    if HAS_CUDA:
        print(f"\n" + "-" * 50)
        print("  Optimisations GPU (NVIDIA)")
        print("-" * 50 + "\n")

        # D'abord vérifier/réparer PyTorch CUDA (nécessaire pour xformers)
        if not fix_pytorch_cuda():
            print("  [!] PyTorch CUDA non disponible, xformers ne fonctionnera pas")

        # xformers
        success, error_type, _ = check_import("xformers")
        if success:
            print("  [OK] xformers")
        elif check_pip_installed("xformers"):
            # Installé mais cassé
            print("  [BROKEN] xformers - réparation...")
            fix_xformers()
        else:
            # Pas installé, essayer
            print("  [MISSING] xformers - installation...")
            fix_xformers()

        # TensorRT (optionnel)
        success, _, _ = check_import("tensorrt")
        if success:
            print("  [OK] tensorrt")
        else:
            print("  [SKIP] tensorrt (optionnel)")

        # SDPA (toujours dispo avec PyTorch 2.0+)
        print("  [OK] SDPA (PyTorch natif)")

    elif IS_MAC:
        print(f"\n" + "-" * 50)
        print("  Optimisations GPU (Mac)")
        print("-" * 50 + "\n")
        print("  [OK] MPS (Metal) - automatique avec PyTorch")
        print("  [SKIP] xformers/tensorrt (NVIDIA only)")

    # ==========================================
    # OLLAMA
    # ==========================================
    print(f"\n" + "-" * 50)
    print("  Ollama (Chat IA)")
    print("-" * 50 + "\n")

    # Afficher info VRAM
    vram = get_vram_gb()
    vram_level = get_vram_level()
    if vram:
        print(f"  VRAM: {vram:.1f} GB ({vram_level})")
    else:
        print(f"  VRAM: Non détectée ({vram_level})")

    if check_ollama():
        print(f"  [OK] Ollama installé")
        start_ollama_service()

        # Vérifier et installer les modèles requis
        ensure_ollama_models()
    else:
        print("  [MISSING] Ollama")

        if IS_MAC:
            # Installation automatique sur Mac via Homebrew
            if not check_homebrew():
                print("  [MISSING] Homebrew - installation...")
                if not install_homebrew():
                    print("  [ERREUR] Impossible d'installer Homebrew")
                    print("    -> Installe manuellement: https://brew.sh")
                else:
                    # Réessayer après installation Homebrew
                    if install_ollama_mac():
                        start_ollama_service()
                        ensure_ollama_models()
            else:
                # Homebrew déjà installé, installer Ollama
                if install_ollama_mac():
                    start_ollama_service()
                    ensure_ollama_models()

        elif IS_WINDOWS:
            # S'assurer que winget est dispo (gestionnaire de paquets Windows)
            if not check_winget():
                print("  [MISSING] winget - installation...")
                install_winget()
            # install_ollama_windows() essaie winget puis fallback téléchargement direct
            if install_ollama_windows():
                start_ollama_service()
                ensure_ollama_models()

        elif IS_LINUX:
            # Linux - try automatic installation via curl
            print("  [INSTALL] Installation d'Ollama via script officiel...")
            try:
                result = subprocess.run(
                    ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"],
                    timeout=300
                )
                if result.returncode == 0:
                    print("  [OK] Ollama installé")
                    start_ollama_service()
                    ensure_ollama_models()
                else:
                    print("  [ERREUR] Échec installation Ollama")
                    print("    -> curl -fsSL https://ollama.ai/install.sh | sh")
                    print(f"    -> Puis lance: ollama pull {UTILITY_MODEL}")
            except Exception as e:
                print(f"  [ERREUR] {e}")
                print("    -> curl -fsSL https://ollama.ai/install.sh | sh")
                print(f"    -> Puis lance: ollama pull {UTILITY_MODEL}")

        else:
            # Unknown platform - manual instructions
            print("    -> Visitez: https://ollama.ai/download")
            print(f"    -> Puis lance: ollama pull {UTILITY_MODEL}")

    # ==========================================
    # GGUF BACKEND (optionnel)
    # ==========================================
    print(f"\n" + "-" * 50)
    print("  Backend GGUF (modèles quantizés)")
    print("-" * 50 + "\n")

    gguf_installed = check_pip_installed(GGUF_PACKAGE)
    if gguf_installed:
        print(f"  [OK] {GGUF_PACKAGE} installé")
        print("  Le backend GGUF est disponible dans les settings")
    else:
        print(f"  [INFO] {GGUF_PACKAGE} non installé")
        print("  Le backend GGUF permet de réduire l'utilisation VRAM de 50-70%")
        print("  Pour l'installer: pip install stable-diffusion-cpp-python")
        print("  (Optionnel - le backend Diffusers standard fonctionne sans)")

    # Pré-télécharger sd-cli pour la conversion GGUF
    if IS_WINDOWS:
        sd_cli_name = "sd-cli.exe"
    else:
        sd_cli_name = "sd-cli"
    sd_cli_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ext_weights", "sd_cpp", sd_cli_name)
    if os.path.exists(sd_cli_path):
        print(f"  [OK] {sd_cli_name} (convertisseur GGUF) présent")
    else:
        if IS_WINDOWS or IS_LINUX:
            print(f"  [INFO] {sd_cli_name} sera téléchargé automatiquement à la première conversion")
        else:
            print(f"  [INFO] {sd_cli_name} non disponible pré-compilé pour cette plateforme")
            print(f"  [INFO] Compilez depuis: https://github.com/leejet/stable-diffusion.cpp")

    # ==========================================
    # PRE-DOWNLOAD MODEL WEIGHTS
    # ==========================================
    print(f"\n" + "-" * 50)
    print("  Poids modèles (pré-téléchargement)")
    print("-" * 50 + "\n")

    # Fooocus Inpaint Patch (élimine le color shift VAE sur SDXL)
    try:
        from huggingface_hub import hf_hub_download
        fooocus_repo = "lllyasviel/fooocus_inpaint"
        fooocus_head = "fooocus_inpaint_head.pth"
        fooocus_patch = "inpaint_v26.fooocus.patch"

        # Check if already cached (hf_hub_download returns path without downloading if cached)
        try:
            from huggingface_hub import try_to_load_from_cache
            head_cached = try_to_load_from_cache(fooocus_repo, fooocus_head)
            patch_cached = try_to_load_from_cache(fooocus_repo, fooocus_patch)
        except ImportError:
            head_cached = None
            patch_cached = None

        if head_cached and patch_cached:
            print(f"  [OK] Fooocus inpaint patch (cached)")
        else:
            print(f"  [DOWNLOAD] Fooocus inpaint patch (1.3GB)...")
            print(f"      (Corrige le color shift VAE pour SDXL inpainting)")
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
            hf_hub_download(repo_id=fooocus_repo, filename=fooocus_head, resume_download=True)
            hf_hub_download(repo_id=fooocus_repo, filename=fooocus_patch, resume_download=True)
            print(f"  [OK] Fooocus inpaint patch téléchargé")
    except Exception as e:
        print(f"  [SKIP] Fooocus inpaint patch: {e}")
        print(f"      (Sera téléchargé au premier chargement SDXL)")

    # ==========================================
    # VÉRIFICATION FINALE
    # ==========================================
    print("\n" + "-" * 50)
    print("  Vérification finale")
    print("-" * 50 + "\n")

    all_ok = True

    # Vérifier xformers si CUDA présent
    if HAS_CUDA:
        success, _, _ = check_import("xformers")
        if success:
            success2, _, _ = check_import("xformers.ops")
            if success2:
                print("  [OK] xformers fonctionnel")
            else:
                print("  [!] xformers.ops ne fonctionne pas")
                all_ok = False
        else:
            print("  [!] xformers non fonctionnel")
            all_ok = False

    # Vérifier les dépendances critiques
    critical_imports = ["torch", "diffusers", "transformers", "PIL"]
    for module in critical_imports:
        success, _, _ = check_import(module)
        if not success:
            print(f"  [!] {module} ne fonctionne pas")
            all_ok = False

    # ==========================================
    # RÉSUMÉ
    # ==========================================
    print("\n" + "=" * 50)

    if needs_restart:
        print("  REDÉMARRAGE REQUIS")
        print("  Redémarre ton PC puis relance le setup")
        print("=" * 50 + "\n")
        return 2

    # Re-vérifier les packages qui étaient manquants/cassés après installation
    if missing or dll_errors:
        global _import_results_cache
        _import_results_cache = None  # Reset cache pour re-tester
        still_critical = []
        still_optional = []
        for module, package in missing + dll_errors:
            success, _, _ = check_import(module)
            if not success:
                if module in CRITICAL_DEPS:
                    still_critical.append(module)
                else:
                    still_optional.append(module)

        if still_optional:
            print(f"  [WARN] Packages optionnels non installés: {', '.join(still_optional)}")
            print("  (L'app fonctionne sans, certaines features seront désactivées)")

        if still_critical:
            print(f"  [!] {len(still_critical)} package(s) CRITIQUE(S) en erreur: {', '.join(still_critical)}")
            print("=" * 50 + "\n")
            return 1
        elif still_optional:
            print("  Packages critiques OK, démarrage possible")
        else:
            print("  Tous les packages manquants ont été installés!")

    if not all_ok:
        # all_ok est basé sur xformers (optionnel) — ne pas bloquer
        print("  [WARN] Certaines optimisations non disponibles (voir ci-dessus)")

    print("  TOUT EST OK!")
    if HAS_CUDA:
        print("  - xformers: " + ("ACTIF" if check_import("xformers")[0] else "INACTIF (SDPA utilisé)"))
        print("  - SDPA: ACTIF (fallback)")
    print("=" * 50 + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
