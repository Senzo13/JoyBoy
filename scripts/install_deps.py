"""
Installation des dependances avec barre de progression
"""
import subprocess
import sys

def get_packages():
    """Lit requirements.txt et retourne la liste des packages"""
    packages = []
    with open("scripts/requirements.txt", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Ignorer commentaires et lignes vides
            if line and not line.startswith("#"):
                packages.append(line)
    return packages

def progress_bar(current, total, width=40):
    """Affiche une barre de progression"""
    percent = current / total
    filled = int(width * percent)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {current}/{total}"

def install_packages():
    packages = get_packages()
    total = len(packages)
    errors = []

    print()
    print(f"    Installation de {total} packages...")
    print()

    for i, package in enumerate(packages, 1):
        # Extraire juste le nom du package pour l'affichage
        pkg_name = package.split(">=")[0].split("<")[0].split("==")[0].split("[")[0]

        # Afficher progression
        bar = progress_bar(i, total)
        print(f"\r    {bar}  {pkg_name:<25}", end="", flush=True)

        # Installer
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "--quiet"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            errors.append((pkg_name, result.stderr.strip().split('\n')[-1] if result.stderr else 'inconnu'))

    print(f"\r    {progress_bar(total, total)}  {'Termine!':<25}")
    print()

    # Afficher recap des erreurs s'il y en a
    if errors:
        print(f"    [!] {len(errors)} package(s) en erreur:")
        for pkg_name, reason in errors:
            print(f"        - {pkg_name}: {reason}")
        print()
        print("    Relance le setup pour reessayer.")
        print()

if __name__ == "__main__":
    install_packages()
