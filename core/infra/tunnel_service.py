"""
Service Cloudflare Tunnel — Quick Tunnel via cloudflared
Télécharge cloudflared automatiquement et lance un tunnel vers localhost:7860
"""
import subprocess
import sys
import os
import time
import json
import threading
import re
import urllib.request
import urllib.error

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform == 'linux'
IS_MAC = sys.platform == 'darwin'

# Chemins
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BIN_DIR = os.path.join(BASE_DIR, "bin")
CONFIG_PATH = os.path.join(BASE_DIR, "tunnel_config.json")

# Platform-specific paths and URLs
if IS_WINDOWS:
    CLOUDFLARED_PATH = os.path.join(BIN_DIR, "cloudflared.exe")
    CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
elif IS_LINUX:
    CLOUDFLARED_PATH = os.path.join(BIN_DIR, "cloudflared")
    CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
elif IS_MAC:
    CLOUDFLARED_PATH = os.path.join(BIN_DIR, "cloudflared")
    CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
else:
    CLOUDFLARED_PATH = os.path.join(BIN_DIR, "cloudflared")
    CLOUDFLARED_URL = None  # Unsupported platform

# State
_tunnel_process = None
_tunnel_url = None
_tunnel_lock = threading.Lock()


def is_cloudflared_installed():
    """Vérifie si cloudflared.exe est présent"""
    return os.path.isfile(CLOUDFLARED_PATH)


def download_cloudflared():
    """
    Télécharge cloudflared depuis GitHub Releases.
    Retry 3x en cas d'échec. Barre de progression console.
    """
    if CLOUDFLARED_URL is None:
        print("[TUNNEL] Plateforme non supportée pour cloudflared")
        return False

    os.makedirs(BIN_DIR, exist_ok=True)

    print("[TUNNEL] Téléchargement de cloudflared...")
    import urllib.request
    import tempfile

    for attempt in range(1, 4):
        try:
            print(f"[TUNNEL] Tentative {attempt}/3...")

            # For Mac, we download a .tgz archive
            if IS_MAC:
                temp_archive = os.path.join(tempfile.gettempdir(), "cloudflared.tgz")
                download_path = temp_archive
            else:
                download_path = CLOUDFLARED_PATH

            with urllib.request.urlopen(CLOUDFLARED_URL) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                block_size = 8192
                last_percent = -1

                with open(download_path, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded += len(buffer)

                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            if percent != last_percent:
                                filled = int(30 * percent / 100)
                                bar = "█" * filled + "░" * (30 - filled)
                                size_mb = downloaded / (1024 * 1024)
                                total_mb = total_size / (1024 * 1024)
                                sys.stdout.write(f"\r[TUNNEL] [{bar}] {percent}% ({size_mb:.1f}/{total_mb:.1f} MB)")
                                sys.stdout.flush()
                                last_percent = percent

                print()  # Nouvelle ligne après la barre

            # Extract .tgz for Mac
            if IS_MAC:
                import tarfile
                with tarfile.open(temp_archive, 'r:gz') as tar:
                    tar.extractall(BIN_DIR)
                os.remove(temp_archive)

            # Make executable on Linux/Mac
            if not IS_WINDOWS:
                os.chmod(CLOUDFLARED_PATH, 0o755)

            size_mb = os.path.getsize(CLOUDFLARED_PATH) / (1024 * 1024)
            print(f"[TUNNEL] cloudflared téléchargé ({size_mb:.1f} MB)")
            return True
        except Exception as e:
            print(f"\n[TUNNEL] Erreur tentative {attempt}: {e}")
            if os.path.exists(CLOUDFLARED_PATH):
                os.remove(CLOUDFLARED_PATH)
            if attempt < 3:
                time.sleep(2)

    print("[TUNNEL] Échec du téléchargement après 3 tentatives")
    return False


def start_tunnel(port=7860):
    """
    Lance un Quick Tunnel cloudflared vers localhost:port.
    Parse stderr via PIPE pour capturer l'URL trycloudflare.com.
    """
    global _tunnel_process, _tunnel_url

    with _tunnel_lock:
        if _tunnel_process and _tunnel_process.poll() is None:
            if _tunnel_url:
                return {"success": True, "url": _tunnel_url, "message": "Tunnel déjà actif"}
            stop_tunnel()

        if not is_cloudflared_installed():
            if not download_cloudflared():
                return {"success": False, "error": "Impossible de télécharger cloudflared"}

        _tunnel_url = None

        # Tuer les anciens cloudflared qui traînent
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/f", "/im", "cloudflared.exe"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["pkill", "-f", "cloudflared"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
        except Exception:
            pass

        try:
            # Lancer cloudflared avec PIPE pour capturer stderr directement
            popen_kwargs = {
                'stdout': subprocess.DEVNULL,
                'stderr': subprocess.PIPE,
                'bufsize': 1,
                'universal_newlines': True,
                'encoding': 'utf-8',
                'errors': 'ignore'
            }
            if IS_WINDOWS:
                popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

            _tunnel_process = subprocess.Popen(
                [CLOUDFLARED_PATH, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                **popen_kwargs
            )
        except Exception as e:
            print(f"[TUNNEL] Erreur lancement: {e}")
            return {"success": False, "error": str(e)}

    # Lire stderr ligne par ligne pour capturer l'URL
    url_found = False
    collected_output = []
    start_time = time.time()

    while time.time() - start_time < 30:  # Max 30 secondes
        # Vérifier si le process est mort
        if _tunnel_process.poll() is not None:
            break

        try:
            # Lire une ligne (blocking avec universal_newlines=True)
            line = _tunnel_process.stderr.readline()

            if line:
                collected_output.append(line)
                # Chercher l'URL dans la ligne
                match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
                if match:
                    _tunnel_url = match.group(1)
                    url_found = True
                    break
        except Exception:
            time.sleep(0.1)

    if url_found:
        # Lancer un thread qui continue à lire stderr (évite buffer plein)
        def _drain_stderr():
            try:
                while _tunnel_process and _tunnel_process.poll() is None:
                    _tunnel_process.stderr.readline()
            except Exception:
                pass
        drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
        drain_thread.start()

        # Lancer le watchdog
        _start_watchdog(port)
        return {"success": True, "url": _tunnel_url}
    else:
        if _tunnel_process and _tunnel_process.poll() is not None:
            stop_tunnel()
            return {"success": False, "error": "cloudflared s'est arrêté prématurément"}
        return {"success": False, "error": "Timeout: URL non reçue après 30s"}


_watchdog_active = False

def _check_tunnel_health():
    """Vérifie si le tunnel est encore valide côté Cloudflare (pas juste le process local)."""
    if not _tunnel_url:
        return False
    try:
        req = urllib.request.Request(_tunnel_url, method='HEAD')
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status < 500
    except urllib.error.HTTPError as e:
        # 530 = "origin unregistered from Argo Tunnel"
        if e.code == 530:
            print(f"[TUNNEL] Health check: 530 — tunnel désenregistré côté Cloudflare")
            return False
        # 4xx = le tunnel fonctionne (l'app répond)
        return e.code < 500
    except Exception:
        return False


def _start_watchdog(port):
    """Thread watchdog qui relance le tunnel s'il crash ou si Cloudflare le désenregistre (530)."""
    global _watchdog_active
    if _watchdog_active:
        return
    _watchdog_active = True

    def _watch():
        global _tunnel_process, _tunnel_url, _watchdog_active
        # Attendre un peu avant de commencer à surveiller
        time.sleep(15)
        health_check_counter = 0
        while _watchdog_active:
            time.sleep(10)
            if not _watchdog_active:
                break

            needs_restart = False

            # 1. Process cloudflared mort
            if _tunnel_process is None or _tunnel_process.poll() is not None:
                print("[TUNNEL] Process cloudflared mort, relance...")
                needs_restart = True

            # 2. Health check HTTP toutes les ~60s (6 cycles de 10s)
            health_check_counter += 1
            if not needs_restart and health_check_counter >= 6:
                health_check_counter = 0
                if not _check_tunnel_health():
                    print("[TUNNEL] Tunnel non-fonctionnel (530 ou timeout), relance...")
                    needs_restart = True

            if needs_restart:
                # Tuer le process existant proprement
                stop_tunnel()
                _watchdog_active = True  # stop_tunnel désactive le watchdog, on le réactive
                result = start_tunnel(port)
                if result.get("success"):
                    print(f"[TUNNEL] Relancé: {result['url']}")
                else:
                    print(f"[TUNNEL] Relance échouée: {result.get('error')}")
                    time.sleep(30)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()


def stop_tunnel():
    """Arrête le tunnel cloudflared"""
    global _tunnel_process, _tunnel_url, _watchdog_active

    _watchdog_active = False  # Stopper le watchdog d'abord

    with _tunnel_lock:
        if _tunnel_process:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=5)
            except Exception:
                try:
                    _tunnel_process.kill()
                except Exception:
                    pass
            _tunnel_process = None

        _tunnel_url = None
        print("[TUNNEL] Tunnel arrêté")
    return {"success": True}


def is_tunnel_running():
    """Vérifie si le tunnel est actif"""
    return _tunnel_process is not None and _tunnel_process.poll() is None


def get_tunnel_status():
    """Retourne le status complet du tunnel"""
    running = is_tunnel_running()
    return {
        "running": running,
        "url": _tunnel_url if running else None
    }


def save_tunnel_config(enabled):
    """Sauvegarde la config tunnel (enabled: true/false)"""
    config = {"enabled": enabled}
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        print(f"[TUNNEL] Erreur sauvegarde config: {e}")


def load_tunnel_config():
    """Charge la config tunnel"""
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[TUNNEL] Erreur lecture config: {e}")
    return {"enabled": False}
