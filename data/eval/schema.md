# Municipal Complaint Evaluation Dataset Schema (v1)

## Overview
This document specifies the format and semantic fields of the benchmark evaluation dataset `dataset_v1.jsonl` used for validating grievance intelligence pipelines (language detection, classification, routing, priority assessment, duplicate detection, and guardrails).

## Format
JSON Lines (`.jsonl`), where each line is a self-contained JSON object representing a municipal grievance complaint.

## Field Specifications

| Field Name | Type | Nullable | Allowed Values / Constraints | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | No | Alphanumeric (e.g. `eval_001`) | Unique sample identifier |
| `title` | `string` | No | 1 - 200 characters | Original citizen complaint headline |
| `description` | `string` | No | 1 - 2000 characters | Detailed complaint text |
| `language` | `string` | No | `en`, `hi`, `kn`, `code_mixed` | Ground-truth primary language |
| `category` | `string` | No | `Roads & Footpaths`, `Water Supply & Sewerage`, `Electricity & Lighting`, `Solid Waste Management`, `Stormwater & Drainage`, `Parks & Recreation`, `General Municipal Services` | Target municipal grievance category |
| `correct_department` | `string` | No | `Roads & Bridges`, `Water Supply`, `Electricity & Streetlights`, `Sanitation & Solid Waste`, `Stormwater & Drainage`, `Parks & Horticulture` | Ground-truth accountable municipal department |
| `safety_critical` | `boolean` | No | `true`, `false` | Immediate hazard to human life, safety, or public health |
| `expected_priority_band` | `string` | No | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` | Expected SLA priority classification |
| `duplicate_group_id` | `string` | Yes | String identifier or `null` | Group identifier for duplicate complaints reporting the exact same real-world incident |
| `sample_type` | `string` | No | `standard`, `safety_critical`, `code_mixed`, `vague`, `adversarial`, `duplicate` | Category of synthetic evaluation benchmark sample |
| `latitude` | `float` | No | 12.80 to 13.15 | Geographic latitude coordinate (Bengaluru municipal zone) |
| `longitude` | `float` | No | 77.45 to 77.75 | Geographic longitude coordinate (Bengaluru municipal zone) |
| `ward_id` | `string` | Yes | e.g. `ward_1`, `ward_2`, etc. | Associated administrative ward |

## Key Evaluation Criteria
1. **Safety-Critical Recall**: Evaluates whether samples labeled with `safety_critical: true` are correctly escalated to `CRITICAL` (or `HIGH` immediate safety hazard) priority. Every missed detection is recorded as a False Negative.
2. **Duplicate Detection**: Evaluates whether complaints sharing the same `duplicate_group_id` are ranked in the top-k candidate recommendations.
3. **Guardrail Robustness**: Vague samples must degrade gracefully to `MANUAL_TRIAGE` via low confidence, and adversarial/prompt-injection samples must not compromise system invariants.
