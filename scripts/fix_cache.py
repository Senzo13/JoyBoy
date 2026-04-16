"""Repare le cache HuggingFace en supprimant uniquement les fichiers corrompus"""
import os
import json
from pathlib import Path

def check_json_file(filepath):
    """Verifie si un fichier JSON est valide"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content.strip():
                return False, "vide"
            json.loads(content)
            return True, "ok"
    except json.JSONDecodeError:
        return False, "JSON invalide"
    except Exception as e:
        return False, str(e)

def scan_cache(cache_dir, name):
    """Scanne un dossier cache"""
    if not cache_dir.exists():
        print(f"  {name}: pas trouve")
        return []

    print(f"\n=== {name} ===")
    print(f"Dossier: {cache_dir}\n")

    corrupted = []
    checked = 0

    for json_file in cache_dir.rglob("*.json"):
        checked += 1
        valid, reason = check_json_file(json_file)
        if not valid:
            size = json_file.stat().st_size
            corrupted.append((json_file, reason, size))
            print(f"  [CORROMPU] {json_file.name} ({reason}, {size} bytes)")

    print(f"{checked} fichiers JSON verifies, {len(corrupted)} corrompu(s)")
    return corrupted

def main():
    print("\n========================================")
    print("  Reparation du cache HuggingFace")
    print("========================================")

    # Cache du PROJET (prioritaire)
    project_dir = Path(__file__).parent
    project_cache = project_dir / "models" / "huggingface"

    # Cache SYSTEME (backup)
    system_cache = Path.home() / ".cache" / "huggingface"

    all_corrupted = []

    # Scanner les deux emplacements
    all_corrupted.extend(scan_cache(project_cache, "Cache PROJET (models/huggingface)"))
    all_corrupted.extend(scan_cache(system_cache, "Cache SYSTEME (~/.cache/huggingface)"))

    print(f"\n========================================")
    print(f"TOTAL: {len(all_corrupted)} fichier(s) corrompu(s)")
    print(f"========================================")

    if all_corrupted:
        print("\nFichiers corrompus:")
        for f, reason, size in all_corrupted:
            print(f"  - {f} ({reason})")

        print("\nSupprimer ces fichiers? (les gros modeles seront gardes)")
        response = input("O/N: ").strip().lower()

        if response == 'o':
            for f, _, _ in all_corrupted:
                try:
                    f.unlink()
                    print(f"  Supprime: {f.name}")
                except Exception as e:
                    print(f"  Erreur: {f.name} - {e}")

            print("\nFichiers corrompus supprimes!")
            print("Les configs seront retelechargees au prochain lancement.")
        else:
            print("Annule.")
    else:
        print("\nAucun fichier JSON corrompu trouve!")
        print("\nLe probleme vient peut-etre d'un telechargement interrompu.")
        print("Veux-tu supprimer le cache du modele SDXL Inpainting? (sera retelechage)")
        response = input("O/N: ").strip().lower()

        if response == 'o':
            # Supprimer le dossier du modele problematique
            sdxl_patterns = ["stable-diffusion-xl-1.0-inpainting", "diffusers--stable-diffusion"]
            deleted = False

            for cache in [project_cache, system_cache]:
                if not cache.exists():
                    continue
                for folder in cache.rglob("*"):
                    if folder.is_dir():
                        for pattern in sdxl_patterns:
                            if pattern in folder.name:
                                print(f"  Suppression: {folder}")
                                import shutil
                                shutil.rmtree(folder, ignore_errors=True)
                                deleted = True

            if deleted:
                print("\nCache SDXL supprime! Relance launch_web.bat")
            else:
                print("\nModele SDXL non trouve dans le cache.")

if __name__ == "__main__":
    main()
    input("\nAppuyez sur Entree...")
