"""
Fonctions utilitaires
"""
from pathlib import Path

OUTPUT_DIR = Path("output")


def ensure_output_dir():
    """Cree le dossier output si necessaire"""
    OUTPUT_DIR.mkdir(exist_ok=True)
