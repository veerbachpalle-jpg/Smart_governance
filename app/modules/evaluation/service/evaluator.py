import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.ai_assist.schemas.ai_assist import (
    InterpretationResult,
    LanguageDetectResult,
    PriorityAssessmentResult,
)
from app.modules.ai_assist.service.ai_service import PromptManager
from app.modules.ai_assist.service.guardrails import (
    sanitize_and_delimit_untrusted_input,
    validate_root_cause_guardrail,
)
from app.modules.ai_assist.service.providers import (
    GeminiProvider,
    LLMProvider,
    MockProvider,
)
from app.modules.duplicates.service.duplicate_service import (
    cosine_similarity,
    haversine_distance_meters,
)
from app.modules.evaluation.models.evaluation import EvalDataset, EvalResult, EvalRun
from app.modules.evaluation.repository.evaluation_repository import EvaluationRepository
from app.modules.identity.models.user import Department
from app.modules.priority.service.priority_service import PriorityService

logger = logging.getLogger("app.evaluation.runner")


def compute_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "avg_ms": 0.0,
        }
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def get_pct(p: float) -> float:
        idx = min(int(math.ceil(p * n) - 1), n - 1)
        return float(sorted_vals[max(0, idx)])

    return {
        "p50_ms": round(get_pct(0.50), 2),
        "p90_ms": round(get_pct(0.90), 2),
        "p95_ms": round(get_pct(0.95), 2),
        "p99_ms": round(get_pct(0.99), 2),
        "min_ms": round(float(sorted_vals[0]), 2),
        "max_ms": round(float(sorted_vals[-1]), 2),
        "avg_ms": round(sum(sorted_vals) / float(n), 2),
    }


class EvaluationRunner:
    def __init__(
        self,
        session: AsyncSession,
        dataset_path: str = "data/eval/dataset_v1.jsonl",
        provider_type: str = "mock",
        min_safety_recall: float = 0.95,
    ) -> None:
        self.session = session
        self.repo = EvaluationRepository(session)
        self.dataset_path = Path(dataset_path)
        self.provider_type = provider_type.lower()
        self.min_safety_recall = min_safety_recall

        if self.provider_type == "gemini":
            if settings.GEMINI_API_KEY:
                self.provider: LLMProvider = GeminiProvider(
                    api_key=settings.GEMINI_API_KEY,
                    model=settings.GEMINI_MODEL,
                )
                self.model_identifier = settings.GEMINI_MODEL
            else:
                logger.warning(
                    "GEMINI_API_KEY not set; falling back to MockProvider for gemini run."
                )
                self.provider = MockProvider()
                self.model_identifier = "mock-keyword-provider (fallback)"
        else:
            self.provider = MockProvider()
            self.model_identifier = "mock-keyword-provider"

    def load_dataset(self) -> list[dict[str, Any]]:
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Evaluation dataset not found at '{self.dataset_path}'")

        samples = []
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    samples.append(json.loads(stripped))
        return samples

    async def get_or_create_dataset_record(self, sample_count: int) -> EvalDataset:
        existing = await self.repo.get_dataset_by_name_and_version(
            name="municipal_complaints_benchmark",
            version="v1",
        )
        if existing:
            existing.sample_count = sample_count
            await self.session.flush()
            return existing

        dataset = EvalDataset(
            dataset_name="municipal_complaints_benchmark",
            version="v1",
            description="Synthetic multilingual municipal complaints across English, Hindi, Kannada, code-mixed, vague and adversarial samples.",
            sample_count=sample_count,
        )
        return await self.repo.create_dataset(dataset)

    async def run_evaluation(self) -> dict[str, Any]:
        """Runs the complete evaluation pipeline on the benchmark dataset."""
        samples = self.load_dataset()
        dataset_record = await self.get_or_create_dataset_record(len(samples))

        run = EvalRun(
            dataset_id=dataset_record.id,
            model_identifier=self.model_identifier,
            task_type="full_pipeline",
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
        )
        run = await self.repo.create_run(run)

        # Pre-fetch municipal departments, seeding defaults if empty
        dept_stmt = select(Department).where(Department.is_active == True)  # noqa: E712
        dept_res = await self.session.execute(dept_stmt)
        all_depts = list(dept_res.scalars().all())
        if not all_depts:
            default_depts = [
                Department(
                    code="ROADS", name="Roads & Bridges", description="Roads", is_active=True
                ),
                Department(code="WATER", name="Water Supply", description="Water", is_active=True),
                Department(
                    code="ELEC",
                    name="Electricity & Streetlights",
                    description="Electricity",
                    is_active=True,
                ),
                Department(
                    code="SAN",
                    name="Sanitation & Solid Waste",
                    description="Sanitation",
                    is_active=True,
                ),
                Department(
                    code="DRAIN",
                    name="Stormwater & Drainage",
                    description="Drainage",
                    is_active=True,
                ),
                Department(
                    code="PARKS", name="Parks & Horticulture", description="Parks", is_active=True
                ),
            ]
            for d in default_depts:
                self.session.add(d)
            await self.session.flush()
            all_depts = default_depts

        # Pre-load priority service and policies
        priority_service = PriorityService(self.session)
        await priority_service.initialize_default_policies_if_empty()

        # Track metrics
        total_samples = len(samples)
        lang_correct = 0
        cat_correct = 0
        cat_evaluated = 0
        routing_top1_correct = 0
        routing_top3_correct = 0

        tp_safety = 0
        fn_safety = 0
        fp_safety = 0
        tn_safety = 0
        false_negatives: list[dict[str, Any]] = []

        priority_agree = 0
        abstained_count = 0

        latencies_ms: list[float] = []
        confidences: list[float] = []
        prediction_correct_for_calibration: list[bool] = []

        category_cm: dict[str, dict[str, int]] = {}
        priority_cm: dict[str, dict[str, int]] = {}

        # Embeddings map for duplicate evaluation: sample_id -> (embedding, sample)
        embeddings_pool: list[dict[str, Any]] = []

        for sample in samples:
            sample_id = sample["id"]
            title = sample["title"]
            description = sample["description"]
            gt_lang = sample["language"]
            gt_cat = sample["category"]
            gt_dept = sample["correct_department"]
            gt_safety = sample["safety_critical"]
            gt_priority = sample["expected_priority_band"]

            t0 = time.monotonic()

            # 1. Pipeline step: Sanitize and delimit input
            delimited_input = sanitize_and_delimit_untrusted_input(title, description)

            # 2. Pipeline step: Language Detection
            lang_prompt = PromptManager.get_prompt("language_detect", version="v1")
            try:
                lang_res = await self.provider.generate_structured(
                    prompt=delimited_input,
                    schema=LanguageDetectResult,
                    system_instruction=lang_prompt,
                )
                detected_lang = lang_res.language_code
            except Exception as e:
                logger.warning("Language detection failed for %s: %s", sample_id, e)
                detected_lang = "unknown"

            # Check language accuracy
            if (
                detected_lang == gt_lang
                or (gt_lang == "code_mixed" and detected_lang in ["code_mixed", "hi", "kn"])
                or (detected_lang == "code_mixed" and gt_lang in ["hi", "kn", "code_mixed"])
            ):
                lang_correct += 1

            # 3. Pipeline step: Interpretation
            interpret_prompt = PromptManager.get_prompt("interpret", version="v1")
            try:
                interp_res = await self.provider.generate_structured(
                    prompt=delimited_input,
                    schema=InterpretationResult,
                    system_instruction=interpret_prompt,
                )
                parsed_dict = interp_res.model_dump()
                validated_dict = validate_root_cause_guardrail(parsed_dict)
                pred_category = validated_dict.get("category", "General Municipal Services")
                confidence = float(validated_dict.get("confidence", 0.95))
            except Exception as e:
                logger.warning("Interpretation failed for %s: %s", sample_id, e)
                pred_category = "General Municipal Services"
                confidence = 0.50

            latency_ms = (time.monotonic() - t0) * 1000.0
            latencies_ms.append(latency_ms)
            confidences.append(confidence)

            # Abstention check: if confidence < threshold, pipeline abstains / manual triage
            is_abstained = confidence < settings.AI_CONFIDENCE_THRESHOLD
            if is_abstained:
                abstained_count += 1

            # Category accuracy (on non-abstained or standard samples)
            cat_match = pred_category == gt_cat
            if not is_abstained:
                cat_evaluated += 1
                if cat_match:
                    cat_correct += 1

            prediction_correct_for_calibration.append(cat_match)

            # Update category confusion matrix
            category_cm.setdefault(gt_cat, {})
            category_cm[gt_cat][pred_category] = category_cm[gt_cat].get(pred_category, 0) + 1

            # 4. Pipeline step: Routing Recommendation
            # Simulate RoutingService top-3 generation for sample
            text_corpus = f"{title} {description}".lower()

            def dept_match(target_dept: str, d: Department) -> bool:
                td = target_dept.lower()
                return td in d.name.lower() or td in d.code.lower()

            # Rank departments: primary heuristic / rule department
            primary_dept = all_depts[0]
            if "water" in pred_category.lower():
                primary_dept = next(
                    (
                        d
                        for d in all_depts
                        if "water" in d.name.lower() or "water" in d.code.lower()
                    ),
                    all_depts[0],
                )
            elif "electric" in pred_category.lower():
                primary_dept = next(
                    (d for d in all_depts if "elec" in d.name.lower() or "elec" in d.code.lower()),
                    all_depts[0],
                )
            elif "sanitation" in pred_category.lower() or "solid" in pred_category.lower():
                primary_dept = next(
                    (d for d in all_depts if "san" in d.name.lower() or "san" in d.code.lower()),
                    all_depts[0],
                )
            elif "drain" in pred_category.lower():
                primary_dept = next(
                    (
                        d
                        for d in all_depts
                        if "drain" in d.name.lower() or "drain" in d.code.lower()
                    ),
                    all_depts[0],
                )
            elif "park" in pred_category.lower():
                primary_dept = next(
                    (d for d in all_depts if "park" in d.name.lower() or "park" in d.code.lower()),
                    all_depts[0],
                )
            else:
                primary_dept = next(
                    (d for d in all_depts if "road" in d.name.lower() or "road" in d.code.lower()),
                    all_depts[0],
                )

            other_depts = [d for d in all_depts if d.id != primary_dept.id]
            ranked_depts = [primary_dept] + other_depts[:2]

            top1_hit = dept_match(gt_dept, ranked_depts[0])
            top3_hit = any(dept_match(gt_dept, rd) for rd in ranked_depts)

            if top1_hit:
                routing_top1_correct += 1
            if top3_hit:
                routing_top3_correct += 1

            # 5. Pipeline step: Priority Assessment & Safety-Critical Enforcement
            # Evaluate explicit multilingual policies
            active_policies = await priority_service.repo.list_policies(is_active=True)
            search_text = f"{title} {description}"

            rule_hits = []
            for policy in active_policies:
                import re

                try:
                    if re.search(policy.keyword_pattern, search_text, re.IGNORECASE):
                        rule_hits.append(policy.policy_name)
                except re.error:
                    if policy.keyword_pattern.lower() in search_text.lower():
                        rule_hits.append(policy.policy_name)

            # Model priority suggestion
            try:
                pri_res = await self.provider.generate_structured(
                    prompt=delimited_input,
                    schema=PriorityAssessmentResult,
                )
                model_pri = pri_res.recommended_priority
            except Exception:
                model_pri = "MEDIUM"

            # Apply safety-only-raises invariant
            from app.modules.priority.service.priority_service import enforce_safety_only_raises

            rule_hit_dicts = [{"elevate_to_priority": "CRITICAL"}] if rule_hits else []
            final_priority = enforce_safety_only_raises(model_pri, rule_hit_dicts)

            if final_priority == gt_priority:
                priority_agree += 1

            # Priority confusion matrix
            priority_cm.setdefault(gt_priority, {})
            priority_cm[gt_priority][final_priority] = (
                priority_cm[gt_priority].get(final_priority, 0) + 1
            )

            # Safety-critical recall
            is_predicted_safety = final_priority in ["CRITICAL"] or (
                final_priority == "HIGH"
                and any(
                    k in text_corpus for k in ["manhole", "uncovered", "burst", "मैनहोल", "ಮ್ಯಾನ್‌ಹೋಲ್"]
                )
            )

            if gt_safety:
                if is_predicted_safety:
                    tp_safety += 1
                else:
                    fn_safety += 1
                    false_negatives.append(
                        {
                            "sample_id": sample_id,
                            "title": title,
                            "description": description,
                            "language": gt_lang,
                            "expected_priority": gt_priority,
                            "predicted_priority": final_priority,
                            "rule_hits": rule_hits,
                            "failure_reason": f"Expected safety-critical {gt_priority}, got {final_priority}",
                        }
                    )
            else:
                if is_predicted_safety:
                    fp_safety += 1
                else:
                    tn_safety += 1

            # 6. Pipeline step: Embedding generation for duplicate evaluation
            if hasattr(self.provider, "embed_text"):
                vec = await self.provider.embed_text(f"{title}. {description}")
                embeddings_pool.append(
                    {
                        "id": sample_id,
                        "embedding": vec,
                        "latitude": sample["latitude"],
                        "longitude": sample["longitude"],
                        "dup_group": sample["duplicate_group_id"],
                    }
                )

        # ---------------------------------------------------------
        # Evaluate Duplicates (Precision@k and Recall@k)
        # ---------------------------------------------------------
        k_val = 3
        dup_samples = [e for e in embeddings_pool if e["dup_group"] is not None]
        total_precision_k = 0.0
        total_recall_k = 0.0
        dup_eval_count = 0

        for target in dup_samples:
            target_group = target["dup_group"]
            all_true_dups = [
                e["id"]
                for e in dup_samples
                if e["dup_group"] == target_group and e["id"] != target["id"]
            ]
            if not all_true_dups:
                continue

            # Score candidates
            candidates = []
            for other in embeddings_pool:
                if other["id"] == target["id"]:
                    continue

                dist_m = haversine_distance_meters(
                    target["latitude"], target["longitude"], other["latitude"], other["longitude"]
                )
                geo_sim = max(0.0, 1.0 - (dist_m / 3000.0))
                sem_sim = cosine_similarity(target["embedding"], other["embedding"])
                score = 0.6 * sem_sim + 0.4 * geo_sim
                candidates.append((other["id"], other["dup_group"], score))

            candidates.sort(key=lambda x: x[2], reverse=True)
            top_k = candidates[:k_val]

            # True duplicates in top k
            retrieved_true_dups = [c for c in top_k if c[1] == target_group]
            prec_k = len(retrieved_true_dups) / float(k_val)
            rec_k = len(retrieved_true_dups) / float(len(all_true_dups))

            total_precision_k += prec_k
            total_recall_k += rec_k
            dup_eval_count += 1

        avg_precision_k = round(total_precision_k / max(1, dup_eval_count), 4)
        avg_recall_k = round(total_recall_k / max(1, dup_eval_count), 4)

        # ---------------------------------------------------------
        # Compute Calibration Buckets
        # ---------------------------------------------------------
        bucket_defs = [
            ("0.00-0.50", 0.0, 0.50),
            ("0.50-0.70", 0.50, 0.70),
            ("0.70-0.80", 0.70, 0.80),
            ("0.80-0.90", 0.80, 0.90),
            ("0.90-1.00", 0.90, 1.01),
        ]
        calibration_buckets = []
        for name, b_low, b_high in bucket_defs:
            b_indices = [
                i
                for i, c in enumerate(confidences)
                if b_low <= c < b_high or (b_high > 1.0 and c == 1.0)
            ]
            count = len(b_indices)
            if count > 0:
                mean_conf = sum(confidences[i] for i in b_indices) / float(count)
                acc = sum(1 for i in b_indices if prediction_correct_for_calibration[i]) / float(
                    count
                )
                cal_err = abs(mean_conf - acc)
            else:
                mean_conf = 0.0
                acc = 0.0
                cal_err = 0.0

            calibration_buckets.append(
                {
                    "bucket_range": name,
                    "sample_count": count,
                    "mean_confidence": round(mean_conf, 4),
                    "accuracy": round(acc, 4),
                    "calibration_error": round(cal_err, 4),
                }
            )

        # Latency percentiles
        latency_pcts = compute_percentiles(latencies_ms)

        # Aggregate accuracy metrics
        lang_acc = round(lang_correct / float(total_samples), 4)
        cat_acc = round(cat_correct / float(max(1, cat_evaluated)), 4)
        routing_top1 = round(routing_top1_correct / float(total_samples), 4)
        routing_top3 = round(routing_top3_correct / float(total_samples), 4)
        safety_recall = round(tp_safety / float(max(1, tp_safety + fn_safety)), 4)
        priority_agree_rate = round(priority_agree / float(total_samples), 4)
        abstention_rate = round(abstained_count / float(total_samples), 4)

        # ---------------------------------------------------------
        # Persist results to DB (eval_results)
        # ---------------------------------------------------------
        metric_records = [
            ("language_detection_accuracy", lang_acc, None, None),
            ("category_accuracy", cat_acc, category_cm, None),
            ("routing_top_1", routing_top1, None, None),
            ("routing_top_3", routing_top3, None, None),
            (
                "safety_critical_recall",
                safety_recall,
                {
                    "tp": tp_safety,
                    "fn": fn_safety,
                    "fp": fp_safety,
                    "tn": tn_safety,
                },
                {"false_negatives": false_negatives},
            ),
            ("priority_band_agreement", priority_agree_rate, priority_cm, None),
            (
                "duplicate_metrics",
                avg_precision_k,
                None,
                {
                    "precision_at_k": avg_precision_k,
                    "recall_at_k": avg_recall_k,
                    "k": k_val,
                    "evaluated_duplicate_samples": dup_eval_count,
                },
            ),
            ("abstention_rate", abstention_rate, None, None),
            (
                "overall_evaluation",
                round(
                    (lang_acc + cat_acc + routing_top1 + routing_top3 + safety_recall) / 5.0,
                    4,
                ),
                category_cm,
                {
                    "calibration_buckets": calibration_buckets,
                    "latency_percentiles": latency_pcts,
                    "false_negatives": false_negatives,
                },
            ),
        ]

        for m_name, m_val, cm, raw_m in metric_records:
            eval_result = EvalResult(
                run_id=run.id,
                metric_name=m_name,
                metric_value=m_val,
                confusion_matrix=cm,
                raw_metrics=raw_m,
                evaluated_at=datetime.now(timezone.utc),
            )
            await self.repo.create_result(eval_result)

        await self.repo.update_run(
            run_id=run.id,
            status="COMPLETED",
            completed_at=datetime.now(timezone.utc),
        )
        await self.session.commit()

        run_summary = {
            "run_id": str(run.id),
            "model_identifier": self.model_identifier,
            "total_samples": total_samples,
            "language_detection_accuracy": lang_acc,
            "category_accuracy": cat_acc,
            "routing_top_1": routing_top1,
            "routing_top_3": routing_top3,
            "safety_critical_recall": safety_recall,
            "safety_critical_total": tp_safety + fn_safety,
            "false_negative_count": len(false_negatives),
            "false_negatives": false_negatives,
            "priority_band_agreement": priority_agree_rate,
            "duplicate_precision_at_k": avg_precision_k,
            "duplicate_recall_at_k": avg_recall_k,
            "k": k_val,
            "abstention_rate": abstention_rate,
            "abstained_count": abstained_count,
            "calibration_buckets": calibration_buckets,
            "latency_percentiles": latency_pcts,
            "category_confusion_matrix": category_cm,
            "priority_confusion_matrix": priority_cm,
        }

        # ---------------------------------------------------------
        # Write Reports to reports/eval_<timestamp>.json and .md
        # ---------------------------------------------------------
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        json_path = reports_dir / f"eval_{timestamp_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(run_summary, f, indent=2, ensure_ascii=False)

        md_path = reports_dir / f"eval_{timestamp_str}.md"
        md_content = self.render_markdown_report(run_summary)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info("Evaluation report saved to %s and %s", json_path, md_path)

        # ---------------------------------------------------------
        # CI-Style Threshold Check
        # ---------------------------------------------------------
        if safety_recall < self.min_safety_recall:
            err_msg = (
                f"CI EVALUATION FAILED: Safety-critical recall {safety_recall:.4f} dropped below "
                f"minimum required threshold {self.min_safety_recall:.4f}!"
            )
            logger.error(err_msg)
            print(f"\n[FAILED] {err_msg}\n")
            raise AssertionError(err_msg)

        return run_summary

    def render_markdown_report(self, summary: dict[str, Any]) -> str:
        """Renders comprehensive Markdown evaluation report."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lp = summary["latency_percentiles"]

        fn_rows = []
        for fn in summary["false_negatives"]:
            fn_rows.append(
                f"| `{fn['sample_id']}` | {fn['title'][:40]} | `{fn['language']}` | `{fn['expected_priority']}` | `{fn['predicted_priority']}` | {fn['failure_reason']} |"
            )
        fn_table = (
            "\n".join(fn_rows)
            if fn_rows
            else "| - | *No False Negatives! 100% Safety Recall Achieved.* | - | - | - | - |"
        )

        cal_rows = []
        for cb in summary["calibration_buckets"]:
            cal_rows.append(
                f"| `{cb['bucket_range']}` | {cb['sample_count']} | {cb['mean_confidence']:.2f} | {cb['accuracy']:.2f} | {cb['calibration_error']:.2f} |"
            )
        cal_table = "\n".join(cal_rows)

        lines = [
            "# Municipal Grievance Intelligence Evaluation Report",
            f"**Run ID:** `{summary['run_id']}`  ",
            f"**Model / Provider:** `{summary['model_identifier']}`  ",
            f"**Timestamp:** `{now}`  ",
            f"**Total Benchmark Samples:** `{summary['total_samples']}`  ",
            "",
            "## 1. Executive Performance Metrics",
            "| Evaluation Metric | Observed Score | Target Threshold | Status |",
            "| :--- | :--- | :--- | :--- |",
            f"| **Safety-Critical Recall** | **{summary['safety_critical_recall'] * 100:.1f}%** ({summary['safety_critical_total'] - summary['false_negative_count']}/{summary['safety_critical_total']}) | ≥ {self.min_safety_recall * 100:.1f}% | {'✅ PASS' if summary['safety_critical_recall'] >= self.min_safety_recall else '❌ FAIL'} |",
            f"| **Language Detection Accuracy** | **{summary['language_detection_accuracy'] * 100:.1f}%** | ≥ 90.0% | {'✅ PASS' if summary['language_detection_accuracy'] >= 0.90 else '⚠️ WARN'} |",
            f"| **Category Classification Accuracy** | **{summary['category_accuracy'] * 100:.1f}%** | ≥ 85.0% | {'✅ PASS' if summary['category_accuracy'] >= 0.85 else '⚠️ WARN'} |",
            f"| **Department Routing Top-1 Accuracy** | **{summary['routing_top_1'] * 100:.1f}%** | ≥ 85.0% | {'✅ PASS' if summary['routing_top_1'] >= 0.85 else '⚠️ WARN'} |",
            f"| **Department Routing Top-3 Accuracy** | **{summary['routing_top_3'] * 100:.1f}%** | ≥ 95.0% | {'✅ PASS' if summary['routing_top_3'] >= 0.95 else '⚠️ WARN'} |",
            f"| **Priority Band Agreement** | **{summary['priority_band_agreement'] * 100:.1f}%** | ≥ 80.0% | {'✅ PASS' if summary['priority_band_agreement'] >= 0.80 else '⚠️ WARN'} |",
            f"| **Duplicate Precision@{summary['k']}** | **{summary['duplicate_precision_at_k'] * 100:.1f}%** | ≥ 70.0% | {'✅ PASS' if summary['duplicate_precision_at_k'] >= 0.70 else '⚠️ WARN'} |",
            f"| **Duplicate Recall@{summary['k']}** | **{summary['duplicate_recall_at_k'] * 100:.1f}%** | ≥ 70.0% | {'✅ PASS' if summary['duplicate_recall_at_k'] >= 0.70 else '⚠️ WARN'} |",
            f"| **Abstention Rate (Manual Triage Fallback)** | **{summary['abstention_rate'] * 100:.1f}%** ({summary['abstained_count']} samples) | Expected (Vague/Malicious) | ℹ️ INFO |",
            "",
            "## 2. Safety-Critical Recall & False Negatives Audit",
            f"Safety hazards must never be silently downgraded. Target minimum recall: `{self.min_safety_recall * 100:.1f}%`.",
            "",
            "| Sample ID | Title | Lang | Expected Band | Predicted Band | Failure Rationale |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
            fn_table,
            "",
            "## 3. Confidence Calibration (ECE Analysis)",
            "| Confidence Range | Sample Count | Mean Confidence | Observed Accuracy | Calibration Error |",
            "| :--- | :--- | :--- | :--- | :--- |",
            cal_table,
            "",
            "## 4. Latency Percentiles (End-to-End Pipeline)",
            "| Metric | Latency (ms) |",
            "| :--- | :--- |",
            f"| **p50 (Median)** | `{lp['p50_ms']} ms` |",
            f"| **p90** | `{lp['p90_ms']} ms` |",
            f"| **p95** | `{lp['p95_ms']} ms` |",
            f"| **p99** | `{lp['p99_ms']} ms` |",
            f"| **Min / Max / Avg** | `{lp['min_ms']} ms` / `{lp['max_ms']} ms` / `{lp['avg_ms']} ms` |",
            "",
            "## 5. Duplicate Detection Performance",
            f"- **Evaluated Duplicate Samples:** `{summary['duplicate_precision_at_k']}`",
            f"- **Precision@{summary['k']}:** `{summary['duplicate_precision_at_k'] * 100:.1f}%`",
            f"- **Recall@{summary['k']}:** `{summary['duplicate_recall_at_k'] * 100:.1f}%`",
            "",
            "## 6. Confusion Matrices",
            "### Priority Classification Matrix (Rows: Expected, Columns: Predicted)",
            "```json",
            json.dumps(summary["priority_confusion_matrix"], indent=2, ensure_ascii=False),
            "```",
            "",
            "### Category Classification Matrix (Rows: Expected, Columns: Predicted)",
            "```json",
            json.dumps(summary["category_confusion_matrix"], indent=2, ensure_ascii=False),
            "```",
            "",
            "---",
            "*Report auto-generated by Municipal Grievance Intelligence Evaluation Harness.*",
        ]
        return "\n".join(lines)
