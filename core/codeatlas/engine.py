"""Deterministic code audit engine for CodeAtlas."""

from __future__ import annotations

from typing import Any, Dict, List

from core.audit_modules.workspace_scan import scan_workspace


SEVERITY_WEIGHT = {
    "critical": 22,
    "high": 14,
    "medium": 8,
    "low": 4,
}


def _finding(fid: str, category: str, severity: str, title: str, detail: str, **extra: Any) -> Dict[str, Any]:
    return {
        "id": fid,
        "category": category,
        "severity": severity,
        "title": title,
        "detail": detail,
        **extra,
    }


def _score(base: int, penalties: List[int], floor: int = 0) -> int:
    return max(floor, min(100, int(base - sum(penalties))))


def _category_penalties(findings: List[Dict[str, Any]], *categories: str) -> List[int]:
    wanted = set(categories)
    return [
        SEVERITY_WEIGHT.get(str(item.get("severity") or "low"), 4)
        for item in findings
        if str(item.get("category") or "") in wanted
    ]


def _build_code_findings(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = scan.get("metrics") or {}
    stack = scan.get("stack") or {}
    commands = scan.get("commands") or []
    findings = list(scan.get("findings") or [])

    if metrics.get("backend_files", 0) and metrics.get("test_files", 0) == 0:
        findings.append(_finding(
            "regression:no-tests",
            "regression",
            "high",
            "Aucun test détecté",
            "Le projet contient du code mais aucun dossier/fichier de test détecté. Les régressions seront difficiles à éviter.",
        ))
    if metrics.get("large_code_files", 0):
        findings.append(_finding(
            "maintainability:large-files",
            "maintainability",
            "medium",
            "Fichiers de code volumineux",
            f"{metrics.get('large_code_files')} fichier(s) de code dépassent 250KB. Découper en modules plus ciblés.",
            files=[item.get("path") for item in scan.get("large_files", [])[:8]],
        ))
    if scan.get("duplication", {}).get("repeated_blocks", 0):
        findings.append(_finding(
            "maintainability:duplication-total",
            "maintainability",
            "medium",
            "Duplication détectée",
            f"{scan['duplication']['repeated_blocks']} bloc(s) similaires détectés. Extraire des helpers/composants partagés.",
        ))
    if metrics.get("generated_dirs_present"):
        findings.append(_finding(
            "architecture:generated-dirs",
            "architecture",
            "medium",
            "Dossiers générés présents dans le workspace",
            "Des dossiers comme build/dist/models/output/node_modules existent. Vérifier qu'ils sont ignorés et jamais audités comme source.",
            dirs=metrics.get("generated_dirs_present"),
        ))
    if metrics.get("frontend_files", 0) and not any(command.get("kind") in {"lint", "build", "typecheck"} for command in commands):
        findings.append(_finding(
            "frontend:no-static-check",
            "frontend",
            "medium",
            "Pas de check frontend évident",
            "Aucune commande lint/build/typecheck détectée pour le frontend.",
        ))
    if metrics.get("frontend_files", 0) and "React" in stack.get("frameworks", []) and not metrics.get("extensions", {}).get(".tsx") and not metrics.get("extensions", {}).get(".jsx"):
        findings.append(_finding(
            "frontend:react-without-components",
            "frontend",
            "low",
            "React détecté mais peu de composants visibles",
            "Vérifier que les composants UI ne sont pas concentrés dans un seul fichier JS/HTML.",
        ))
    if metrics.get("agent_files", 0) == 0:
        findings.append(_finding(
            "agents:no-agent-docs",
            "regression",
            "low",
            "Pas de guide agent détecté",
            "Ajouter AGENTS.md/CLAUDE.md améliore la qualité des interventions IA et limite les régressions.",
        ))
    return findings


def _scores(scan: Dict[str, Any], findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    metrics = scan.get("metrics") or {}
    backend_penalties = _category_penalties(findings, "backend", "security")
    frontend_penalties = _category_penalties(findings, "frontend")
    architecture_penalties = _category_penalties(findings, "architecture")
    maintainability_penalties = _category_penalties(findings, "maintainability")
    regression_penalties = _category_penalties(findings, "regression", "security")

    if metrics.get("backend_files", 0) == 0:
        backend_base = 78
        backend_penalties.append(8)
    else:
        backend_base = 94
    if metrics.get("frontend_files", 0) == 0:
        frontend_base = 78
        frontend_penalties.append(8)
    else:
        frontend_base = 94

    return [
        {"id": "backend", "label": "Backend", "score": _score(backend_base, backend_penalties), "max": 100},
        {"id": "frontend", "label": "Frontend", "score": _score(frontend_base, frontend_penalties), "max": 100},
        {"id": "architecture", "label": "Architecture", "score": _score(92, architecture_penalties), "max": 100},
        {"id": "maintainability", "label": "Maintenabilité", "score": _score(92, maintainability_penalties), "max": 100},
        {"id": "regression", "label": "Risque de régression", "score": _score(90, regression_penalties), "max": 100},
    ]


def _global_score(scores: List[Dict[str, Any]]) -> int:
    if not scores:
        return 0
    return round(sum(int(item.get("score") or 0) for item in scores) / len(scores))


def _remediation_plan(findings: List[Dict[str, Any]], scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    priority_map = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}
    items = []
    for index, finding in enumerate(findings[:24], start=1):
        severity = str(finding.get("severity") or "low")
        category = str(finding.get("category") or "general")
        items.append({
            "id": f"fix-{index}",
            "priority": priority_map.get(severity, "P3"),
            "category": category,
            "title": finding.get("title") or "Correction",
            "why": finding.get("detail") or "",
            "actions": [
                "Identifier l'emplacement exact et vérifier l'existant avant d'ajouter du code.",
                "Extraire un helper/composant/service partagé si la logique existe déjà ailleurs.",
                "Ajouter ou mettre à jour un test ciblé qui échoue sans la correction.",
            ],
            "validation": _validation_commands(scan),
            "risk": "Risque moyen si la correction touche des routes, du routing UI ou des helpers partagés.",
        })
    if not items:
        items.append({
            "id": "fix-maintenance",
            "priority": "P3",
            "category": "maintenance",
            "title": "Maintenir la qualité actuelle",
            "why": "Aucun problème majeur détecté par l'audit déterministe.",
            "actions": ["Garder les tests à jour", "Éviter la duplication lors des prochaines features"],
            "validation": _validation_commands(scan),
            "risk": "Faible",
        })
    return items


def _validation_commands(scan: Dict[str, Any]) -> List[str]:
    return [item["command"] for item in scan.get("commands", [])[:8]]


def _build_comparison(current: Dict[str, Any], previous: Dict[str, Any] | None) -> Dict[str, Any]:
    if not previous:
        return {"available": False}
    previous_scores = {item.get("id"): item for item in previous.get("scores") or []}
    deltas = []
    for item in current.get("scores") or []:
        old = int((previous_scores.get(item.get("id")) or {}).get("score") or 0)
        new = int(item.get("score") or 0)
        deltas.append({"id": item.get("id"), "label": item.get("label"), "before": old, "after": new, "delta": new - old})
    return {
        "available": True,
        "previous_audit_id": previous.get("id"),
        "global_before": previous.get("summary", {}).get("global_score"),
        "global_after": current.get("summary", {}).get("global_score"),
        "deltas": deltas,
    }


def run_codeatlas_audit(project_path: str, *, previous: Dict[str, Any] | None = None) -> Dict[str, Any]:
    scan = scan_workspace(project_path)
    findings = _build_code_findings(scan)
    scores = _scores(scan, findings)
    global_score = _global_score(scores)
    summary = {
        "global_score": global_score,
        "top_risk": findings[0]["title"] if findings else "Aucun risque critique détecté",
        "backend_score": next(item["score"] for item in scores if item["id"] == "backend"),
        "frontend_score": next(item["score"] for item in scores if item["id"] == "frontend"),
        "architecture_score": next(item["score"] for item in scores if item["id"] == "architecture"),
        "maintainability_score": next(item["score"] for item in scores if item["id"] == "maintainability"),
        "regression_score": next(item["score"] for item in scores if item["id"] == "regression"),
        "files_scanned": scan.get("metrics", {}).get("total_files", 0),
        "stack": scan.get("stack", {}),
    }
    audit = {
        "target": scan["target"],
        "summary": summary,
        "snapshot": {
            "metrics": scan.get("metrics", {}),
            "stack": scan.get("stack", {}),
            "commands": scan.get("commands", []),
            "comparison": {},
        },
        "findings": findings,
        "scores": scores,
        "remediation_items": _remediation_plan(findings, scan),
    }
    audit["snapshot"]["comparison"] = _build_comparison(audit, previous)
    return audit
