# ADR-005: AI Provider Abstraction & Fail-Safe Degradation

## Status
**Accepted** — Session 4

## Context
The system uses AI for complaint categorization, routing suggestions, priority assessment, and duplicate detection. However, AI is advisory — never authoritative. The system must function correctly when AI is unavailable, slow, or producing garbage output.

## Decision
Implement a **provider abstraction layer** with deterministic fallback and multi-layered guardrails:

### Provider Interface:
```python
class LLMProvider(ABC):
    async def generate(self, prompt: str, system_prompt: str) -> str: ...


class EmbeddingProvider(ABC):
    async def embed(self, text: str) -> list[float]: ...
```

### Implementations:
1. **GeminiProvider**: Production REST client for Gemini 1.5 Flash + text-embedding-004.
2. **MockProvider**: Deterministic keyword-matching provider for offline development, unit testing, and evaluation benchmarking.

### Guardrail Chain (executed in order):
1. **PII Redaction**: Regex-based scrubbing of phone numbers, emails, Aadhaar numbers before any AI egress.
2. **Prompt Injection Defense**: Citizen text wrapped in `<untrusted_citizen_submission>` XML boundaries with escaped control tags.
3. **Circuit Breaker**: Trips to `OPEN` after N consecutive provider failures (configurable, default 3). Auto-resets after cooldown period.
4. **Pydantic Validation**: AI output parsed against strict schema with one automatic retry on format errors.
5. **Confidence Threshold**: Outputs below configurable threshold (default 0.7) trigger degradation.

### Fail-Safe Degradation Triggers:
| Trigger | Effect |
|:---|:---|
| `AI_ENABLED=false` | Immediate `MANUAL_TRIAGE` |
| Circuit breaker OPEN | Immediate `MANUAL_TRIAGE` |
| Provider timeout | Immediate `MANUAL_TRIAGE` |
| Confidence < threshold | Immediate `MANUAL_TRIAGE` |
| Invalid JSON after retry | Immediate `MANUAL_TRIAGE` |

### Manual Triage Queue:
When AI degrades, complaints enter `MANUAL_TRIAGE` status. Officers use `POST /triage/manual/{id}` to manually assign category, routing, and priority — producing identical downstream records as the AI pipeline.

## Consequences

### Positive
- **Zero AI lock-in**: Switch providers by implementing the abstract interface.
- **Graceful degradation**: System never blocks on AI failures; human triage is always available.
- **Testability**: MockProvider enables deterministic testing without API keys or network.
- **Versioned prompts**: Prompt files in `prompts/v1/` enable A/B testing and rollback.

### Negative
- MockProvider accuracy doesn't represent real AI performance.
- Prompt versioning requires manual synchronization with evaluation datasets.
- Circuit breaker state is in-memory — resets on process restart.

### Alternatives Considered
- **LangChain/LlamaIndex**: Rejected — unnecessary abstraction layer for two provider implementations.
- **Queue-based async processing only**: Rejected — doesn't address fail-safe degradation logic.
- **Synchronous AI calls in request path**: Rejected — unacceptable latency for user-facing endpoints.
