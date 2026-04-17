"""
Audit déterministe du harness JoyBoy.

L'objectif n'est pas de "juger" le projet mais de remonter les points
qui comptent avant une ouverture publique: install, secrets, packaging,
surface de config, et clarté de la surface publique.
"""

from __future__ import annotations

from pathlib import Path

from core.infra.local_config import get_local_config_overview


PROJECT_DIR = Path(__file__).resolve().parents[2]

PUBLIC_RISK_FILES = [
    "docs/NSFW_BYPASS.md",
]

COMMUNITY_FILES = [
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
]

PUBLIC_DOCS = [
    "docs/GETTING_STARTED.md",
    "docs/ONBOARDING.md",
    "docs/DOCTOR.md",
    "docs/LOCAL_PACKS.md",
    "docs/ARCHITECTURE.md",
    "docs/SEO_AND_DISCOVERY.md",
    "docs/RELEASES.md",
]


def _read_text(relative_path: str) -> str:
    path = PROJECT_DIR / relative_path
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _exists(relative_path: str) -> bool:
    return (PROJECT_DIR / relative_path).exists()


def _check(check_id: str, section: str, label: str, weight: int, status: str,
           detail: str, action: str = "") -> dict:
    return {
        "id": check_id,
        "section": section,
        "label": label,
        "weight": weight,
        "status": status,
        "detail": detail,
        "action": action,
    }


def _status_factor(status: str) -> float:
    return {
        "pass": 1.0,
        "warn": 0.5,
        "fail": 0.0,
    }.get(status, 0.0)


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def _section_score(checks: list[dict], section: str) -> int:
    section_checks = [check for check in checks if check["section"] == section]
    if not section_checks:
        return 0
    total = sum(check["weight"] for check in section_checks)
    gained = sum(check["weight"] * _status_factor(check["status"]) for check in section_checks)
    return round((gained / total) * 100)


def run_harness_audit() -> dict:
    gitignore_text = _read_text(".gitignore")
    settings_routes_text = _read_text("web/routes/settings.py")
    system_routes_text = _read_text("web/routes/system.py")
    models_routes_text = _read_text("web/routes/models.py")
    settings_js_text = _read_text("web/static/js/settings.js")
    index_text = _read_text("web/templates/index.html")
    readme_text = _read_text("README.md")

    local_config = get_local_config_overview()

    docker_files = [
        relative_path for relative_path in ("Dockerfile", "docker-compose.yml", "compose.yml")
        if _exists(relative_path)
    ]
    public_risk_hits = [
        relative_path
        for relative_path in PUBLIC_RISK_FILES
        if _exists(relative_path)
    ]
    tests_present = any(_exists(relative_path) for relative_path in ("tests", "pytest.ini", "pyproject.toml"))
    community_ready = all(_exists(relative_path) for relative_path in COMMUNITY_FILES)
    public_docs_ready = all(_exists(relative_path) for relative_path in PUBLIC_DOCS)
    bootstrap_present = _exists("scripts/bootstrap.py")
    version_file_ready = _exists("VERSION")
    update_surface_ready = version_file_ready and "/api/version/status" in system_routes_text
    release_ignores_ready = all(
        entry in gitignore_text
        for entry in ("output/", "models/", "venv/", ".env", ".joyboy/")
    )

    launchers = [
        relative_path for relative_path in ("start_windows.bat", "start_mac.command", "start_linux.sh")
        if _exists(relative_path)
    ]

    checks = [
        _check(
            "env_template",
            "install",
            "Template d'environnement",
            8,
            "pass" if _exists(".env.example") else "fail",
            ".env.example est présent pour documenter les variables supportées."
            if _exists(".env.example")
            else "Aucun .env.example trouvé pour guider les nouveaux utilisateurs.",
            "Ajouter un .env.example minimal et commenté."
        ),
        _check(
            "launcher",
            "install",
            "Bootstrap local",
            10,
            "pass" if len(launchers) == 3 else ("warn" if launchers else "fail"),
            f"Launchers détectés: {', '.join(launchers)}."
            if launchers
            else "Aucun launcher simple détecté à la racine.",
            "Prévoir un chemin d'installation simple et documenté pour les nouveaux utilisateurs."
        ),
        _check(
            "docker_packaging",
            "install",
            "Packaging Docker",
            12,
            "pass" if docker_files or (bootstrap_present and len(launchers) == 3) else "warn",
            f"Docker détecté: {', '.join(docker_files)}."
            if docker_files
            else (
                "Pas de Docker, mais bootstrap + launchers locaux sont présents."
                if bootstrap_present and len(launchers) == 3
                else "Ni Docker ni bootstrap unifié détectés pour un premier lancement reproductible."
            ),
            "Ajouter un packaging Docker/Compose ou assumer clairement un autre chemin d'onboarding avec bootstrap."
        ),
        _check(
            "bootstrap_helper",
            "install",
            "Bootstrap Python partagé",
            8,
            "pass" if bootstrap_present else "warn",
            "Le setup passe par un helper Python partagé (scripts/bootstrap.py)."
            if bootstrap_present
            else "Aucun helper bootstrap partagé détecté.",
            "Ajouter un helper bootstrap pour éviter que chaque launcher réimplémente le setup."
        ),
        _check(
            "provider_secrets_local",
            "secrets",
            "Secrets fournisseurs hors git",
            14,
            "pass" if _exists("core/infra/local_config.py") else "fail",
            f"Stockage local prévu via {local_config['config_path']}."
            if _exists("core/infra/local_config.py")
            else "Aucun stockage local non versionné détecté pour les clés providers.",
            "Prévoir un stockage local hors repo pour les clés et tokens."
        ),
        _check(
            "gitignore_secrets",
            "secrets",
            "Protection Git des secrets",
            8,
            "pass" if all(entry in gitignore_text for entry in (".env", ".env.local", ".joyboy/")) else "warn",
            "Les chemins secrets principaux sont ignorés par Git."
            if all(entry in gitignore_text for entry in (".env", ".env.local", ".joyboy/"))
            else "Le .gitignore ne couvre pas encore toute la surface des secrets locaux.",
            "Ignorer .env, .env.local et la config locale UI."
        ),
        _check(
            "provider_api_surface",
            "secrets",
            "API secrets/settings",
            10,
            "pass" if "/api/providers/status" in settings_routes_text else "warn",
            "Le backend expose une surface dédiée pour les providers."
            if "/api/providers/status" in settings_routes_text
            else "Aucune surface API dédiée détectée pour les providers.",
            "Ajouter des routes dédiées pour lire/enregistrer les clés fournisseurs sans passer par le code."
        ),
        _check(
            "provider_ui_surface",
            "ux",
            "UI providers dans les settings",
            10,
            "pass" if "provider-settings-list" in index_text and "loadProviderSettings" in settings_js_text else "warn",
            "Les providers sont gérables depuis l'interface."
            if "provider-settings-list" in index_text and "loadProviderSettings" in settings_js_text
            else "Les providers ne semblent pas encore exposés proprement dans l'interface.",
            "Ajouter une section providers dans les settings sans créer une nouvelle UX parallèle."
        ),
        _check(
            "audit_surface",
            "ux",
            "Audit du harness",
            10,
            "pass" if "/api/harness/audit" in settings_routes_text else "warn",
            "Le projet expose déjà un audit déterministe du harness."
            if "/api/harness/audit" in settings_routes_text
            else "Aucun audit déterministe du harness détecté.",
            "Ajouter un audit simple pour mesurer install, packaging, secrets et readiness open source."
        ),
        _check(
            "docs_surface",
            "release",
            "README / onboarding",
            8,
            "pass" if readme_text and public_docs_ready else "warn",
            "README et docs publiques de base détectés."
            if readme_text and public_docs_ready
            else "La doc publique n'est pas encore complète pour une release open source propre.",
            "Documenter clairement ce qu'est JoyBoy, comment le lancer et quelles extensions restent locales."
        ),
        _check(
            "release_ignore_rules",
            "release",
            "Hygiène fichiers locaux",
            8,
            "pass" if release_ignores_ready else "warn",
            "Les principaux dossiers locaux/générés sont ignorés par Git."
            if release_ignores_ready
            else "Le .gitignore ne couvre pas encore tous les dossiers locaux/générés importants.",
            "Vérifier que outputs, modèles, caches, venv et secrets locaux restent hors git."
        ),
        _check(
            "version_update_surface",
            "release",
            "Version et update checker",
            8,
            "pass" if update_surface_ready else "warn",
            "VERSION et endpoint /api/version/status détectés."
            if update_surface_ready
            else "Le projet n'expose pas encore de version locale + checker de release.",
            "Ajouter VERSION et une surface de vérification des releases GitHub."
        ),
        _check(
            "public_surface_review",
            "release",
            "Review surface publique",
            10,
            "warn" if public_risk_hits else "pass",
            "Des fichiers de surface publique à revoir existent encore: "
            + ", ".join(public_risk_hits)
            if public_risk_hits
            else "Pas de fichier public à haut risque détecté dans la liste ciblée.",
            "Garder les extensions locales séparées du core public et des releases."
        ),
        _check(
            "community_health",
            "release",
            "Community health files",
            10,
            "pass" if community_ready else "warn",
            "Contributing guide, security policy, code of conduct et templates sont présents."
            if community_ready
            else "La surface community health n'est pas encore complète.",
            "Ajouter CONTRIBUTING, SECURITY, CODE_OF_CONDUCT et les templates GitHub."
        ),
        _check(
            "tests_presence",
            "release",
            "Filets de sécurité",
            10,
            "pass" if tests_present else "warn",
            "Une surface de tests/config de tests est présente."
            if tests_present
            else "Peu ou pas de tests détectés pour sécuriser les refactors d'installation.",
            "Ajouter quelques smoke tests ciblés sur setup, providers et audit."
        ),
    ]

    total_weight = sum(check["weight"] for check in checks)
    gained_weight = sum(check["weight"] * _status_factor(check["status"]) for check in checks)
    score = round((gained_weight / total_weight) * 100) if total_weight else 0

    top_actions = [
        check["action"]
        for check in sorted(
            [check for check in checks if check["status"] != "pass" and check["action"]],
            key=lambda item: (-item["weight"], item["label"])
        )
    ][:4]

    sections = {
        "install": _section_score(checks, "install"),
        "secrets": _section_score(checks, "secrets"),
        "ux": _section_score(checks, "ux"),
        "release": _section_score(checks, "release"),
    }

    return {
        "score": score,
        "grade": _grade(score),
        "summary": (
            "Bon socle local."
            if score >= 80
            else "Socle solide mais plusieurs points restent à verrouiller avant une ouverture publique facile."
        ),
        "sections": sections,
        "checks": checks,
        "top_actions": top_actions,
        "local_config": local_config,
    }
