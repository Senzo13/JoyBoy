"""
Workspace Tools - Permet à l'IA d'explorer des dossiers locaux
Inspiré par Claude Code - outils: list_files, read_file, search, glob
"""
import os
import re
import fnmatch
from typing import List, Dict, Optional, Tuple
from config import TOOL_CAPABLE_MODELS, TOOL_EXCLUDED_MODELS

# Extensions de fichiers lisibles
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.svelte',
    '.html', '.css', '.scss', '.sass', '.less',
    '.json', '.yaml', '.yml', '.toml', '.xml',
    '.md', '.txt', '.rst', '.csv',
    '.sh', '.bash', '.zsh', '.bat', '.ps1', '.cmd',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.java', '.kt', '.go', '.rs', '.rb',
    '.php', '.sql', '.graphql', '.prisma',
    '.env', '.gitignore', '.dockerignore', '.editorconfig',
    'Dockerfile', 'Makefile', 'CMakeLists.txt'
}

# Dossiers à ignorer
IGNORE_DIRS = {
    'node_modules', '__pycache__', '.git', '.svn', '.hg',
    'venv', 'env', '.venv', '.env',
    'dist', 'build', 'target', 'out', '.next', '.nuxt',
    '.cache', '.parcel-cache', '.turbo',
    'coverage', '.nyc_output', 'htmlcov',
    '.idea', '.vscode', '.vs',
    'vendor', 'bower_components'
}

# Fichiers à ignorer
IGNORE_FILES = {
    '.DS_Store', 'Thumbs.db', 'desktop.ini',
    '*.pyc', '*.pyo', '*.exe', '*.dll', '*.so', '*.dylib',
    '*.jpg', '*.jpeg', '*.png', '*.gif', '*.bmp', '*.ico', '*.webp',
    '*.mp3', '*.mp4', '*.avi', '*.mov', '*.wav',
    '*.zip', '*.tar', '*.gz', '*.rar', '*.7z',
    '*.pdf', '*.doc', '*.docx', '*.xls', '*.xlsx',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '*.min.js', '*.min.css', '*.map'
}

# TOOL_CAPABLE_MODELS et TOOL_EXCLUDED_MODELS importés depuis config.py


def is_model_tool_capable(model_name: str) -> bool:
    """Vérifie si le modèle supporte le function calling"""
    model_lower = model_name.lower()
    if any(excl in model_lower for excl in TOOL_EXCLUDED_MODELS):
        return False
    return any(cap in model_lower for cap in TOOL_CAPABLE_MODELS)


def should_ignore(name: str, is_dir: bool = False) -> bool:
    """Vérifie si un fichier/dossier doit être ignoré"""
    if is_dir:
        return name in IGNORE_DIRS

    # Vérifier les patterns
    for pattern in IGNORE_FILES:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def is_text_file(filepath: str) -> bool:
    """Vérifie si c'est un fichier texte lisible"""
    name = os.path.basename(filepath)
    ext = os.path.splitext(name)[1].lower()

    # Extension connue
    if ext in TEXT_EXTENSIONS:
        return True

    # Fichiers sans extension mais connus
    if name in TEXT_EXTENSIONS:
        return True

    # Petits fichiers sans extension (probablement du texte)
    if not ext:
        try:
            size = os.path.getsize(filepath)
            if size < 100000:  # < 100KB
                with open(filepath, 'rb') as f:
                    chunk = f.read(1024)
                    # Vérifier si c'est du texte (pas trop de bytes nuls)
                    null_count = chunk.count(b'\x00')
                    return null_count < 5
        except Exception:
            pass

    return False


def _resolve_workspace_path(workspace_path: str, relative_path: str = "") -> Optional[str]:
    """Resolve a path and guarantee it stays inside the workspace.

    A simple ``startswith(workspace_path)`` check is not enough on Windows:
    ``C:\\repo-other`` starts with ``C:\\repo``. ``commonpath`` plus ``realpath``
    keeps terminal tools from reading or writing through path traversal or
    symlink escapes.
    """
    if not workspace_path:
        return None

    root = os.path.realpath(os.path.abspath(workspace_path))
    candidate = os.path.realpath(os.path.abspath(os.path.join(root, relative_path or "")))

    try:
        common = os.path.commonpath([os.path.normcase(root), os.path.normcase(candidate)])
    except ValueError:
        return None

    if common != os.path.normcase(root):
        return None
    return candidate


def _workspace_relpath(path: str, workspace_path: str) -> str:
    root = os.path.realpath(os.path.abspath(workspace_path))
    return os.path.relpath(path, root).replace('\\', '/')


def list_files(workspace_path: str, relative_path: str = "", max_depth: int = 3, max_files: int = 200) -> Dict:
    """
    Liste les fichiers d'un dossier

    Returns:
        {
            "success": True,
            "path": "relative/path",
            "items": [
                {"name": "file.py", "type": "file", "size": 1234},
                {"name": "subdir", "type": "dir", "items_count": 5}
            ]
        }
    """
    try:
        full_path = _resolve_workspace_path(workspace_path, relative_path)
        if not full_path:
            return {"success": False, "error": "Chemin hors du workspace"}

        if not os.path.isdir(full_path):
            return {"success": False, "error": f"Dossier non trouvé: {relative_path}"}

        items = []
        count = 0

        for entry in sorted(os.listdir(full_path)):
            if count >= max_files:
                items.append({"name": "...", "type": "truncated", "remaining": "trop de fichiers"})
                break

            entry_path = os.path.join(full_path, entry)
            is_dir = os.path.isdir(entry_path)

            if should_ignore(entry, is_dir):
                continue

            if is_dir:
                # Compter les items dans le sous-dossier
                try:
                    sub_count = len([e for e in os.listdir(entry_path) if not should_ignore(e, os.path.isdir(os.path.join(entry_path, e)))])
                except Exception:
                    sub_count = 0
                items.append({
                    "name": entry,
                    "type": "dir",
                    "items_count": sub_count
                })
            else:
                # Montrer tous les fichiers, pas seulement les fichiers texte
                try:
                    size = os.path.getsize(entry_path)
                    is_text = is_text_file(entry_path)
                    items.append({
                        "name": entry,
                        "type": "file",
                        "size": size,
                        "size_display": format_size(size),
                        "readable": is_text  # Indique si le fichier peut être lu
                    })
                except Exception:
                    items.append({"name": entry, "type": "file", "size": 0, "readable": False})

            count += 1

        return {
            "success": True,
            "path": relative_path or ".",
            "items": items,
            "total": len(items)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(workspace_path: str, relative_path: str, max_lines: int = 500) -> Dict:
    """
    Lit le contenu d'un fichier

    Returns:
        {
            "success": True,
            "path": "relative/path/file.py",
            "content": "file content...",
            "lines": 123,
            "truncated": False
        }
    """
    try:
        full_path = _resolve_workspace_path(workspace_path, relative_path)
        if not full_path:
            return {"success": False, "error": "Chemin hors du workspace"}

        if not os.path.isfile(full_path):
            return {"success": False, "error": f"Fichier non trouvé: {relative_path}"}

        if not is_text_file(full_path):
            return {"success": False, "error": f"Fichier non lisible (binaire): {relative_path}"}

        # Lire le fichier
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        total_lines = len(lines)
        truncated = total_lines > max_lines

        if truncated:
            lines = lines[:max_lines]

        # Ajouter les numéros de ligne
        numbered_content = ""
        for i, line in enumerate(lines, 1):
            numbered_content += f"{i:4d} | {line}"

        if truncated:
            numbered_content += f"\n... (tronqué, {total_lines - max_lines} lignes restantes)"

        return {
            "success": True,
            "path": relative_path,
            "content": numbered_content,
            "lines": total_lines,
            "truncated": truncated
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def search_files(workspace_path: str, pattern: str, file_pattern: str = "*", max_results: int = 50) -> Dict:
    """
    Recherche un pattern dans les fichiers (comme grep)

    Args:
        pattern: regex ou texte à chercher
        file_pattern: glob pattern pour filtrer les fichiers (ex: "*.py")

    Returns:
        {
            "success": True,
            "pattern": "search pattern",
            "results": [
                {"file": "path/to/file.py", "line": 42, "content": "matching line..."}
            ]
        }
    """
    try:
        results = []
        files_searched = 0
        workspace_root = _resolve_workspace_path(workspace_path, "")
        if not workspace_root:
            return {"success": False, "error": "Workspace invalide"}

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            # Pattern invalide, chercher en texte brut
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        for root, dirs, files in os.walk(workspace_root):
            # Filtrer les dossiers ignorés
            dirs[:] = [d for d in dirs if not should_ignore(d, True)]

            for filename in files:
                if should_ignore(filename):
                    continue

                # Appliquer le filtre de fichier
                if file_pattern != "*" and not fnmatch.fnmatch(filename, file_pattern):
                    continue

                filepath = os.path.join(root, filename)
                rel_path = _workspace_relpath(filepath, workspace_root)

                if not is_text_file(filepath):
                    continue

                files_searched += 1

                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append({
                                    "file": rel_path.replace('\\', '/'),
                                    "line": line_num,
                                    "content": line.strip()[:200]
                                })

                                if len(results) >= max_results:
                                    return {
                                        "success": True,
                                        "pattern": pattern,
                                        "results": results,
                                        "files_searched": files_searched,
                                        "truncated": True
                                    }
                except Exception:
                    continue

        return {
            "success": True,
            "pattern": pattern,
            "results": results,
            "files_searched": files_searched,
            "truncated": False
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def glob_files(workspace_path: str, pattern: str, max_results: int = 100) -> Dict:
    """
    Trouve des fichiers par pattern glob (ex: "**/*.py", "src/**/*.js")

    Returns:
        {
            "success": True,
            "pattern": "**/*.py",
            "files": ["path/to/file1.py", "path/to/file2.py"]
        }
    """
    try:
        import glob as glob_module

        # Construire le pattern complet
        workspace_root = _resolve_workspace_path(workspace_path, "")
        if not workspace_root:
            return {"success": False, "error": "Workspace invalide"}
        full_pattern = os.path.join(workspace_root, pattern)

        matches = []
        for match in glob_module.glob(full_pattern, recursive=True):
            try:
                rel_from_root = os.path.relpath(match, workspace_root)
            except ValueError:
                continue
            if not _resolve_workspace_path(workspace_root, rel_from_root):
                continue
            # Vérifier que c'est un fichier et pas ignoré
            if os.path.isfile(match):
                rel_path = rel_from_root.replace('\\', '/')

                # Vérifier les dossiers parents
                parts = rel_path.replace('\\', '/').split('/')
                skip = False
                for part in parts[:-1]:
                    if should_ignore(part, True):
                        skip = True
                        break

                if skip or should_ignore(parts[-1]):
                    continue

                matches.append(rel_path.replace('\\', '/'))

                if len(matches) >= max_results:
                    break

        return {
            "success": True,
            "pattern": pattern,
            "files": matches,
            "total": len(matches),
            "truncated": len(matches) >= max_results
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_workspace_summary(workspace_path: str) -> Dict:
    """
    Retourne un résumé du workspace (structure, fichiers principaux)
    """
    try:
        workspace_root = _resolve_workspace_path(workspace_path, "")
        if not workspace_root or not os.path.isdir(workspace_root):
            return {"success": False, "error": "Workspace non trouvé"}

        # Compter les fichiers par extension
        ext_counts = {}
        total_files = 0

        # Trouver les fichiers racine importants
        root_files = []
        important_files = {'README.md', 'readme.md', 'package.json', 'requirements.txt',
                          'setup.py', 'pyproject.toml', 'Cargo.toml', 'go.mod',
                          '.gitignore', 'Makefile', 'Dockerfile'}

        for item in os.listdir(workspace_root):
            item_path = os.path.join(workspace_root, item)
            if os.path.isfile(item_path) and item in important_files:
                root_files.append(item)

        # Parcourir pour les stats
        for root, dirs, files in os.walk(workspace_root):
            dirs[:] = [d for d in dirs if not should_ignore(d, True)]

            for f in files:
                if should_ignore(f):
                    continue
                ext = os.path.splitext(f)[1].lower() or '(no ext)'
                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                total_files += 1

        # Top extensions
        top_extensions = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Dossiers racine
        root_dirs = [d for d in os.listdir(workspace_root)
                     if os.path.isdir(os.path.join(workspace_root, d)) and not should_ignore(d, True)]

        return {
            "success": True,
            "name": os.path.basename(workspace_root),
            "path": workspace_root,
            "total_files": total_files,
            "root_dirs": root_dirs[:20],
            "root_files": root_files,
            "top_extensions": top_extensions,
            "summary": f"Workspace '{os.path.basename(workspace_root)}' avec {total_files} fichiers"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def format_size(size: int) -> str:
    """Formate une taille en bytes en format lisible"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f}{unit}" if unit != 'B' else f"{size}B"
        size /= 1024
    return f"{size:.1f}TB"


def write_file(workspace_path: str, relative_path: str, content: str, create_dirs: bool = True) -> Dict:
    """
    Écrit ou crée un fichier dans le workspace

    Args:
        workspace_path: Chemin racine du workspace
        relative_path: Chemin relatif du fichier
        content: Contenu à écrire
        create_dirs: Si True, crée les dossiers parents si nécessaire

    Returns:
        {
            "success": True,
            "path": "relative/path/file.py",
            "created": True/False,  # True si nouveau fichier
            "bytes_written": 1234
        }
    """
    try:
        full_path = _resolve_workspace_path(workspace_path, relative_path)
        if not full_path:
            return {"success": False, "error": "Chemin hors du workspace"}

        # Vérifier si c'est une nouvelle création
        is_new = not os.path.exists(full_path)

        # Créer les dossiers parents si nécessaire
        if create_dirs:
            dir_path = os.path.dirname(full_path)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)

        # Écrire le fichier
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

        bytes_written = len(content.encode('utf-8'))

        print(f"[WORKSPACE] {'Created' if is_new else 'Updated'}: {relative_path} ({bytes_written} bytes)")

        return {
            "success": True,
            "path": relative_path,
            "created": is_new,
            "bytes_written": bytes_written
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def edit_file(workspace_path: str, relative_path: str, old_text: str, new_text: str, replace_all: bool = False) -> Dict:
    """
    Modifie une partie d'un fichier (recherche/remplace)

    Args:
        workspace_path: Chemin racine du workspace
        relative_path: Chemin relatif du fichier
        old_text: Texte à remplacer
        new_text: Nouveau texte
        replace_all: Si True, remplace toutes les occurrences

    Returns:
        {
            "success": True,
            "path": "relative/path/file.py",
            "replacements": 1,
            "diff_preview": "..."
        }
    """
    try:
        full_path = _resolve_workspace_path(workspace_path, relative_path)
        if not full_path:
            return {"success": False, "error": "Chemin hors du workspace"}

        if not os.path.isfile(full_path):
            return {"success": False, "error": f"Fichier non trouvé: {relative_path}"}

        # Lire le contenu actuel
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Vérifier que le texte à remplacer existe
        if old_text not in content:
            return {
                "success": False,
                "error": f"Texte non trouvé dans le fichier. Assurez-vous que le texte correspond exactement (espaces, indentation, etc.)"
            }

        # Compter les occurrences
        count = content.count(old_text)

        if count > 1 and not replace_all:
            return {
                "success": False,
                "error": f"Plusieurs occurrences trouvées ({count}). Utilisez replace_all=True ou fournissez plus de contexte."
            }

        # Remplacer
        if replace_all:
            new_content = content.replace(old_text, new_text)
            replacements = count
        else:
            new_content = content.replace(old_text, new_text, 1)
            replacements = 1

        # Écrire le fichier modifié
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # Générer un aperçu du diff
        diff_preview = f"- {old_text[:100]}{'...' if len(old_text) > 100 else ''}\n+ {new_text[:100]}{'...' if len(new_text) > 100 else ''}"

        print(f"[WORKSPACE] Edited: {relative_path} ({replacements} replacement(s))")

        return {
            "success": True,
            "path": relative_path,
            "replacements": replacements,
            "diff_preview": diff_preview
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(workspace_path: str, relative_path: str) -> Dict:
    """
    Supprime un fichier du workspace

    Returns:
        {
            "success": True,
            "path": "relative/path/file.py",
            "deleted": True
        }
    """
    try:
        full_path = _resolve_workspace_path(workspace_path, relative_path)
        if not full_path:
            return {"success": False, "error": "Chemin hors du workspace"}

        if not os.path.exists(full_path):
            return {"success": False, "error": f"Fichier non trouvé: {relative_path}"}

        if os.path.isdir(full_path):
            return {"success": False, "error": "Impossible de supprimer un dossier (sécurité)"}

        os.remove(full_path)

        print(f"[WORKSPACE] Deleted: {relative_path}")

        return {
            "success": True,
            "path": relative_path,
            "deleted": True
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ===== TOOL DEFINITIONS FOR FUNCTION CALLING =====

WORKSPACE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Liste les fichiers et dossiers dans un chemin du workspace. Utilise pour explorer la structure du projet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif dans le workspace (ex: 'src', 'src/components'). Vide pour la racine."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lit le contenu d'un fichier dans le workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier à lire (ex: 'src/main.py')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Recherche un pattern (texte ou regex) dans tous les fichiers du workspace. Comme grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Texte ou regex à rechercher"
                    },
                    "file_filter": {
                        "type": "string",
                        "description": "Filtre les fichiers par pattern (ex: '*.py', '*.js'). Par défaut: tous."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Trouve des fichiers par pattern glob (ex: '**/*.py' pour tous les fichiers Python)",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern glob (ex: '**/*.py', 'src/**/*.js', '*.md')"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crée ou écrase un fichier avec le contenu spécifié. Utilise pour créer de nouveaux fichiers ou réécrire entièrement un fichier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier à créer/écrire (ex: 'src/utils.py', 'README.md')"
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenu complet du fichier"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Modifie une partie d'un fichier existant en remplaçant du texte. IMPORTANT: Tu dois d'abord lire le fichier avec read_file pour connaître le contenu exact à remplacer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier à modifier"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Texte exact à remplacer (doit correspondre exactement, avec indentation)"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Nouveau texte qui remplacera l'ancien"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Si true, remplace toutes les occurrences. Par défaut false (une seule)."
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Supprime un fichier du workspace. Attention: action irréversible!",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin relatif du fichier à supprimer"
                    }
                },
                "required": ["path"]
            }
        }
    }
]


def execute_tool(tool_name: str, arguments: dict, workspace_path: str) -> Dict:
    """
    Exécute un outil avec les arguments donnés
    """
    if tool_name == "list_files":
        path = arguments.get("path", "")
        return list_files(workspace_path, path)

    elif tool_name == "read_file":
        path = arguments.get("path", "")
        return read_file(workspace_path, path)

    elif tool_name == "search":
        pattern = arguments.get("pattern", "")
        file_filter = arguments.get("file_filter", "*")
        return search_files(workspace_path, pattern, file_filter)

    elif tool_name == "glob":
        pattern = arguments.get("pattern", "**/*")
        return glob_files(workspace_path, pattern)

    elif tool_name == "write_file":
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        return write_file(workspace_path, path, content)

    elif tool_name == "edit_file":
        path = arguments.get("path", "")
        old_text = arguments.get("old_text", "")
        new_text = arguments.get("new_text", "")
        replace_all = arguments.get("replace_all", False)
        return edit_file(workspace_path, path, old_text, new_text, replace_all)

    elif tool_name == "delete_file":
        path = arguments.get("path", "")
        return delete_file(workspace_path, path)

    else:
        return {"success": False, "error": f"Outil inconnu: {tool_name}"}
