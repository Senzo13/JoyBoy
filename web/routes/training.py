"""
Blueprint pour l'entraînement LoRA.
Endpoints: images listing, auto-caption Florence, start/stop training, status.
"""
import os
import base64
import threading
from pathlib import Path
from io import BytesIO

from flask import Blueprint, request, jsonify
from PIL import Image

training_bp = Blueprint('training', __name__)

# ===== STATE =====
_trainer = None          # Instance LoRATrainer en cours
_training_thread = None  # Thread d'entraînement

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _resolve_folder(folder: str) -> Path:
    """Résout un chemin relatif depuis la racine du projet."""
    p = Path(folder)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _make_thumbnail_b64(img_path: Path, size=128) -> str:
    """Crée une miniature base64 d'une image."""
    try:
        img = Image.open(img_path).convert('RGB')
        img.thumbnail((size, size), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"[TRAIN] Thumbnail error {img_path.name}: {e}")
        return ""


# ===== ENDPOINTS =====

@training_bp.route('/api/training/images', methods=['GET'])
def list_training_images():
    """Liste les images d'un dossier avec miniatures."""
    folder = request.args.get('folder', '')
    if not folder:
        return jsonify({"error": "Paramètre 'folder' requis"}), 400

    folder_path = _resolve_folder(folder)
    if not folder_path.exists():
        return jsonify({"error": f"Dossier introuvable: {folder}", "images": []}), 404

    images = []
    for f in sorted(folder_path.iterdir()):
        if f.suffix.lower() in IMAGE_EXTENSIONS:
            # Vérifier si une caption existe
            caption_file = f.with_suffix('.txt')
            caption = ""
            if caption_file.exists():
                caption = caption_file.read_text(encoding='utf-8').strip()

            images.append({
                "name": f.name,
                "path": str(f.relative_to(PROJECT_ROOT)),
                "thumbnail_b64": _make_thumbnail_b64(f),
                "caption": caption,
            })

    return jsonify({"images": images, "folder": str(folder_path)})


@training_bp.route('/api/training/caption', methods=['POST'])
def auto_caption_images():
    """Auto-caption toutes les images d'un dossier via Florence-2."""
    data = request.get_json() or {}
    folder = data.get('folder', '')
    if not folder:
        return jsonify({"error": "Paramètre 'folder' requis"}), 400

    folder_path = _resolve_folder(folder)
    if not folder_path.exists():
        return jsonify({"error": f"Dossier introuvable: {folder}"}), 404

    # Lister les images
    image_files = sorted([
        f for f in folder_path.iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS
    ])
    if not image_files:
        return jsonify({"error": "Aucune image trouvée"}), 404

    # Import Florence
    from core.generation.florence import describe_image

    captions = []
    for img_path in image_files:
        try:
            img = Image.open(img_path).convert('RGB')
            caption = describe_image(img, task="<CAPTION>")

            # Sauvegarder le .txt à côté de l'image
            txt_path = img_path.with_suffix('.txt')
            txt_path.write_text(caption, encoding='utf-8')

            captions.append({
                "image": img_path.name,
                "caption": caption,
            })
            print(f"[TRAIN] Caption: {img_path.name} → {caption[:60]}...")
        except Exception as e:
            print(f"[TRAIN] Erreur caption {img_path.name}: {e}")
            captions.append({
                "image": img_path.name,
                "caption": f"[Erreur: {e}]",
            })

    return jsonify({"captions": captions})


@training_bp.route('/api/training/caption/common', methods=['POST'])
def apply_common_caption():
    """Applique la même caption à toutes les images d'un dossier."""
    data = request.get_json() or {}
    folder = data.get('folder', '')
    caption = data.get('caption', '')
    if not folder or not caption:
        return jsonify({"error": "folder et caption requis"}), 400

    folder_path = _resolve_folder(folder)
    if not folder_path.exists():
        return jsonify({"error": f"Dossier introuvable: {folder}"}), 404

    image_files = sorted([
        f for f in folder_path.iterdir()
        if f.suffix.lower() in IMAGE_EXTENSIONS
    ])
    if not image_files:
        return jsonify({"error": "Aucune image trouvée"}), 404

    count = 0
    for img_path in image_files:
        txt_path = img_path.with_suffix('.txt')
        txt_path.write_text(caption, encoding='utf-8')
        count += 1

    print(f"[TRAIN] Caption commune appliquée à {count} images: {caption[:60]}...")
    return jsonify({"success": True, "count": count})


@training_bp.route('/api/training/caption/save', methods=['POST'])
def save_caption():
    """Sauvegarde une caption éditée manuellement."""
    data = request.get_json() or {}
    image_path = data.get('image_path', '')
    caption = data.get('caption', '')

    if not image_path:
        return jsonify({"error": "image_path requis"}), 400

    img_path = _resolve_folder(image_path)
    txt_path = img_path.with_suffix('.txt')
    txt_path.write_text(caption, encoding='utf-8')

    return jsonify({"success": True})


def _validate_training_folder(folder_path):
    """Vérifie le dossier d'entraînement pour détecter les problèmes.
    Retourne (warnings[], errors[])."""
    warnings = []
    errors = []

    all_files = list(folder_path.iterdir())
    images = [f for f in all_files if f.suffix.lower() in IMAGE_EXTENSIONS]
    non_images = [f for f in all_files if f.suffix.lower() not in IMAGE_EXTENSIONS
                  and f.suffix.lower() != '.txt' and not f.name.startswith('.')]
    unsupported_img_ext = {'.avif', '.tiff', '.tif', '.svg', '.gif', '.heic', '.heif'}

    # Aucune image
    if not images:
        errors.append("Aucune image trouvée (formats: JPG, PNG, WebP, BMP)")
        return warnings, errors

    # Trop peu d'images
    if len(images) < 5:
        warnings.append(f"Seulement {len(images)} images — 10-20 recommandé pour un bon LoRA")

    # Fichiers non supportés
    unsupported = [f for f in non_images if f.suffix.lower() in unsupported_img_ext]
    if unsupported:
        names = ', '.join(f.name for f in unsupported[:5])
        errors.append(f"Format(s) non supporté(s): {names} — convertir en JPG/PNG")

    # Doublons de nom (même stem, extensions différentes → conflit caption .txt)
    stems = {}
    for img in images:
        stem = img.stem.lower()
        stems.setdefault(stem, []).append(img.name)
    duplicates = {stem: files for stem, files in stems.items() if len(files) > 1}
    if duplicates:
        for stem, files in duplicates.items():
            errors.append(f"Conflit de noms: {', '.join(files)} → même caption '{stem}.txt'. Renommer un des fichiers")

    # Images sans caption .txt
    no_caption = [img for img in images if not img.with_suffix('.txt').exists()]
    if no_caption:
        names = ', '.join(f.name for f in no_caption[:5])
        suffix = f" (+{len(no_caption)-5})" if len(no_caption) > 5 else ""
        warnings.append(f"{len(no_caption)} image(s) sans caption: {names}{suffix} — lance Auto-caption")

    # Vérifier que les images sont lisibles
    bad_images = []
    for img in images:
        try:
            with Image.open(img) as im:
                im.verify()
        except Exception:
            bad_images.append(img.name)
    if bad_images:
        names = ', '.join(bad_images[:5])
        errors.append(f"Image(s) corrompue(s): {names}")

    return warnings, errors


@training_bp.route('/api/training/validate', methods=['GET'])
def validate_training_folder():
    """Valide un dossier d'entraînement avant de lancer."""
    folder = request.args.get('folder', '')
    if not folder:
        return jsonify({"error": "Paramètre 'folder' requis"}), 400

    folder_path = _resolve_folder(folder)
    if not folder_path.exists():
        return jsonify({"error": f"Dossier introuvable: {folder}"}), 404

    warnings, errors = _validate_training_folder(folder_path)
    image_count = sum(1 for f in folder_path.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS)

    return jsonify({
        "valid": len(errors) == 0,
        "image_count": image_count,
        "warnings": warnings,
        "errors": errors,
    })


@training_bp.route('/api/training/start', methods=['POST'])
def start_training():
    """Lance l'entraînement LoRA en background."""
    global _trainer, _training_thread

    if _trainer and _trainer.status.get("running"):
        return jsonify({"error": "Un entraînement est déjà en cours"}), 409

    data = request.get_json() or {}
    folder = data.get('folder', '')
    base_model = data.get('base_model', 'sdxl')
    lora_name = data.get('lora_name', 'my_lora')
    steps = int(data.get('steps', 1000))
    rank = int(data.get('rank', 16))

    if not folder:
        return jsonify({"error": "folder requis"}), 400

    folder_path = _resolve_folder(folder)
    if not folder_path.exists():
        return jsonify({"error": f"Dossier introuvable: {folder}"}), 404

    # Validation complète avant lancement
    warnings, errors = _validate_training_folder(folder_path)
    if errors:
        return jsonify({"error": "Problèmes détectés: " + " | ".join(errors)}), 400

    # Créer la config et le trainer
    from core.training.lora_trainer import LoRATrainer, TrainingConfig

    config = TrainingConfig(
        folder=str(folder_path),
        base_model=base_model,
        lora_name=lora_name,
        steps=steps,
        rank=rank,
    )

    _trainer = LoRATrainer(config)

    # Lancer dans un thread
    _training_thread = threading.Thread(target=_trainer.train, daemon=True)
    _training_thread.start()

    return jsonify({"success": True, "training_id": lora_name})


@training_bp.route('/api/training/status', methods=['GET'])
def training_status():
    """Retourne le status de l'entraînement en cours."""
    if _trainer is None:
        return jsonify({"running": False, "progress": 0, "step": 0, "total_steps": 0, "loss": 0, "eta": "", "log_lines": []})
    return jsonify(_trainer.status)


@training_bp.route('/api/training/stop', methods=['POST'])
def stop_training():
    """Arrête l'entraînement en cours."""
    if _trainer is None or not _trainer.status.get("running"):
        return jsonify({"error": "Aucun entraînement en cours"}), 404

    _trainer.stop()
    return jsonify({"success": True})


# ===== CUSTOM LORAS =====

@training_bp.route('/api/training/loras', methods=['GET'])
def list_custom_loras():
    """Liste les LoRAs custom entraînés."""
    from core.model_manager import ModelManager
    mgr = ModelManager.get()
    return jsonify({"loras": mgr.list_custom_loras()})


@training_bp.route('/api/training/lora/activate', methods=['POST'])
def activate_custom_lora():
    """Active un custom LoRA sur le pipeline actuel."""
    data = request.get_json() or {}
    name = data.get('name', '')
    scale = float(data.get('scale', 0.8))

    if not name:
        return jsonify({"error": "name requis"}), 400

    from core.model_manager import ModelManager
    mgr = ModelManager.get()

    # Vérifier que le LoRA existe
    custom_path = mgr._find_custom_lora(name)
    if not custom_path:
        return jsonify({"error": f"LoRA '{name}' introuvable dans trained_loras/"}), 404

    if mgr._inpaint_pipe is None:
        # Pas de pipeline chargé → stocker en pending, sera chargé au prochain load
        mgr._pending_custom_loras[name] = scale
        return jsonify({"success": True, "name": name, "scale": scale, "pending": True})

    # Pipeline actif → charger directement
    success = mgr._load_custom_lora(name, custom_path, scale=scale)
    if success:
        return jsonify({"success": True, "name": name, "scale": scale})
    return jsonify({"error": f"Échec chargement LoRA '{name}'"}), 500


@training_bp.route('/api/training/lora/scale', methods=['POST'])
def set_custom_lora_scale():
    """Modifie le scale d'un custom LoRA chargé."""
    data = request.get_json() or {}
    name = data.get('name', '')
    scale = float(data.get('scale', 0.8))

    if not name:
        return jsonify({"error": "name requis"}), 400

    from core.model_manager import ModelManager
    mgr = ModelManager.get()
    mgr.set_lora_scale(name, scale)
    return jsonify({"success": True, "name": name, "scale": scale})


@training_bp.route('/api/training/lora/deactivate', methods=['POST'])
def deactivate_custom_lora():
    """Désactive un custom LoRA."""
    data = request.get_json() or {}
    name = data.get('name', '')

    if not name:
        return jsonify({"error": "name requis"}), 400

    from core.model_manager import ModelManager
    mgr = ModelManager.get()

    # Retirer du pending
    mgr._pending_custom_loras.pop(name, None)

    # Retirer du pipeline actif si chargé
    if mgr._inpaint_pipe is not None:
        try:
            mgr._inpaint_pipe.delete_adapters(name)
        except Exception:
            pass
    mgr._loras_loaded.pop(name, None)
    mgr._lora_scales.pop(name, None)
    if mgr._inpaint_pipe is not None:
        mgr._apply_lora_scales()

    return jsonify({"success": True})
