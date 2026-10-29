import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.evaluation.service.evaluator import EvaluationRunner


@pytest.mark.asyncio
async def test_evaluation_dataset_validity():
    """Validates that data/eval/dataset_v1.jsonl and SCHEMA.md meet all Part 9 requirements."""
    schema_path = Path("data/eval/SCHEMA.md")
    if not schema_path.exists() and Path("data/eval/schema.md").exists():
        schema_path = Path("data/eval/schema.md")
    dataset_path = Path("data/eval/dataset_v1.jsonl")

    assert schema_path.exists(), "data/eval/SCHEMA.md (or schema.md) must exist"
    assert dataset_path.exists(), "data/eval/dataset_v1.jsonl must exist"

    samples = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                samples.append(json.loads(line.strip()))

    # Requirement: At least 200 samples
    assert len(samples) >= 200, f"Expected at least 200 samples, got {len(samples)}"

    # Requirement: English, Hindi, Kannada, code-mixed, vague, adversarial
    languages = set(s["language"] for s in samples)
    assert "en" in languages, "English samples missing"
    assert "hi" in languages, "Hindi samples missing"
    assert "kn" in languages, "Kannada samples missing"
    assert "code_mixed" in languages, "Code-mixed samples missing"

    sample_types = set(s["sample_type"] for s in samples)
    assert "vague" in sample_types, "Vague samples missing"
    assert "adversarial" in sample_types, "Adversarial samples missing"

    # Requirement: At least 40 safety-critical examples
    safety_count = sum(1 for s in samples if s["safety_critical"])
    assert safety_count >= 40, f"Expected at least 40 safety-critical examples, got {safety_count}"

    # Requirement: Several duplicate groups
    dup_groups = set(s["duplicate_group_id"] for s in samples if s.get("duplicate_group_id"))
    assert len(dup_groups) >= 5, f"Expected several duplicate groups, got {len(dup_groups)}"

    # Validate required fields on every sample
    for s in samples:
        assert "id" in s
        assert "title" in s
        assert "description" in s
        assert "language" in s
        assert "category" in s
        assert "correct_department" in s
        assert "safety_critical" in s
        assert "expected_priority_band" in s
        assert "duplicate_group_id" in s


@pytest.mark.asyncio
async def test_evaluation_runner_execution_and_reports(db_session: AsyncSession):
    """Tests the evaluation runner executing on the dataset, writing DB records, and reports."""
    runner = EvaluationRunner(
        session=db_session,
        dataset_path="data/eval/dataset_v1.jsonl",
        provider_type="mock",
        min_safety_recall=0.90,
    )
    summary = await runner.run_evaluation()

    assert summary["total_samples"] >= 200
    assert summary["safety_critical_recall"] >= 0.90
    assert summary["language_detection_accuracy"] >= 0.85
    assert summary["routing_top_1"] > 0.50
    assert summary["routing_top_3"] >= summary["routing_top_1"]
    assert "p50_ms" in summary["latency_percentiles"]
    assert len(summary["calibration_buckets"]) > 0

    # Verify reports written to disk
    reports_dir = Path("reports")
    json_reports = list(reports_dir.glob("eval_*.json"))
    md_reports = list(reports_dir.glob("eval_*.md"))
    assert len(json_reports) > 0, "eval report json must exist"
    assert len(md_reports) > 0, "eval report markdown must exist"


@pytest.mark.asyncio
async def test_evaluation_ci_threshold_failure(db_session: AsyncSession):
    """Tests that the evaluation runner raises an AssertionError when safety recall is below threshold."""
    runner = EvaluationRunner(
        session=db_session,
        dataset_path="data/eval/dataset_v1.jsonl",
        provider_type="mock",
        min_safety_recall=1.01,  # Impossible threshold to force failure
    )
    with pytest.raises(AssertionError) as exc_info:
        await runner.run_evaluation()

    assert "CI EVALUATION FAILED" in str(exc_info.value)


@pytest.mark.asyncio
async def test_evaluation_endpoints_rbac_and_data(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    auditor_token: str,
    citizen_token: str,
    officer_token: str,
):
    """Tests GET /api/v1/eval/runs and /runs/{id} RBAC, schema, confusion matrix, and false negatives."""
    # 1. Run evaluation to seed a run
    runner = EvaluationRunner(
        session=db_session,
        dataset_path="data/eval/dataset_v1.jsonl",
        provider_type="mock",
        min_safety_recall=0.90,
    )
    summary = await runner.run_evaluation()
    run_id = summary["run_id"]

    # 2. RBAC: Citizen and Officer should be rejected (403 Forbidden)
    resp_citizen = await client.get(
        "/api/v1/eval/runs", headers={"Authorization": f"Bearer {citizen_token}"}
    )
    assert resp_citizen.status_code == 403

    resp_officer = await client.get(
        f"/api/v1/eval/runs/{run_id}", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert resp_officer.status_code == 403

    # 3. Auditor can list runs
    resp_auditor = await client.get(
        "/api/v1/eval/runs", headers={"Authorization": f"Bearer {auditor_token}"}
    )
    assert resp_auditor.status_code == 200
    runs_list = resp_auditor.json()
    assert isinstance(runs_list, list)
    assert len(runs_list) >= 1
    assert any(r["id"] == run_id for r in runs_list)

    # 4. Admin can get run detail
    resp_admin = await client.get(
        f"/api/v1/eval/runs/{run_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_admin.status_code == 200
    detail = resp_admin.json()
    assert detail["id"] == run_id
    assert detail["status"] == "COMPLETED"
    assert "confusion_matrices" in detail
    assert "false_negatives" in detail
    assert "calibration_buckets" in detail
    assert "latency_percentiles" in detail
    assert "results" in detail
    assert len(detail["results"]) >= 5

    # 5. Nonexistent run returns 404
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp_not_found = await client.get(
        f"/api/v1/eval/runs/{fake_id}", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_not_found.status_code == 404
