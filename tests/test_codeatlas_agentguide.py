from pathlib import Path

from core.agentguide.engine import generate_agentguide
from core.audit_modules.catalog import get_module_catalog
from core.codeatlas.engine import run_codeatlas_audit


def _write_sample_project(root: Path) -> None:
    (root / "web" / "static").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app.py").write_text(
        "from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (root / "web" / "static" / "app.js").write_text("console.log('ok')\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / "package.json").write_text(
        '{"scripts":{"test":"node --check web/static/app.js","build":"node --check web/static/app.js"},"dependencies":{"react":"latest"}}',
        encoding="utf-8",
    )


def test_catalog_exposes_code_modules():
    ids = {module["id"] for module in get_module_catalog()}
    assert "codeatlas" in ids
    assert "agentguide" in ids


def test_codeatlas_scores_local_project(tmp_path):
    _write_sample_project(tmp_path)
    audit = run_codeatlas_audit(str(tmp_path))
    assert audit["summary"]["global_score"] > 50
    score_ids = {score["id"] for score in audit["scores"]}
    assert {"backend", "frontend", "architecture", "maintainability", "regression"} <= score_ids
    assert audit["remediation_items"]


def test_agentguide_generates_agents_and_claude(tmp_path):
    _write_sample_project(tmp_path)
    result = generate_agentguide(str(tmp_path))
    generated = {item["path"]: item["content"] for item in result["generated_files"]}
    assert "AGENTS.md" in generated
    assert "CLAUDE.md" in generated
    assert "Do not duplicate code" in generated["AGENTS.md"]
    assert "Anti-Regression Checklist" in generated["CLAUDE.md"]
    assert result["summary"]["agent_readiness"] <= 100
