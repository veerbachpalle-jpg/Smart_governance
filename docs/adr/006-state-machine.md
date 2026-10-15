# ADR-006: Central Case State Machine

## Status
**Accepted** — Session 5

## Context
The grievance lifecycle spans 15+ distinct states with complex branching: citizen challenges, supervisor reviews, reassignment loops, evidence-gated closure, and auto-close timers. Distributed state transition logic across multiple services would make invariant enforcement fragile and untestable.

## Decision
Implement a **centralized state machine** in `app/modules/cases/service/state_machine.py` as the single authority governing all case status transitions.

### Design:
1. **Declarative Transition Rules**: All valid transitions defined as a list of `TransitionRule` dataclasses:
   ```python
   @dataclass
   class TransitionRule:
       from_state: str
       to_state: str
       allowed_roles: set[str]
       activity_type: str
       visibility: str  # INTERNAL or CITIZEN_VISIBLE
       default_message: str
   ```

2. **29 transition rules** covering the full lifecycle including challenge side-paths, reassignment loops, and closure variants.

3. **Enforcement Layers** (all checked before state mutation):
   - **Transition existence**: Unknown transitions return `ILLEGAL_TRANSITION`.
   - **Role authorization**: Unauthorized roles return `ROLE_NOT_PERMITTED`.
   - **Input validation**: Missing required inputs (reason, evidence, officer, department) return specific error codes.

4. **Universal Side-Effect Contract**: Every successful transition atomically commits (in the SAME PostgreSQL transaction):
   - Case/complaint status mutation
   - Immutable audit hash chain event
   - Immutable case activity log entry (with visibility flag)
   - Transactional outbox event for async processing

### Critical Invariants Enforced:
| Invariant | Enforcement |
|:---|:---|
| Evidence-gated closure | `RESOLUTION_PROPOSED` and `CLOSED` transitions query for verified proposals with >=1 attachment |
| Rejection requires reason | `REJECTED_WITH_REASON` mandates >=5 char justification |
| Reassignment requires reason | `REASSIGN_REQUESTED` mandates >=5 char justification |
| Challenge requires reason | `CHALLENGED` mandates >=5 char justification |
| IN_PROGRESS requires officer | Transition checks `assigned_officer_id` is set |
| ROUTED requires department | Transition checks `lead_department_id` is set |
| Anti-self-review | Checked in ChallengeService before calling state machine |

## Consequences

### Positive
- **Single source of truth**: All transition rules in one file — easy to audit, test, and reason about.
- **Atomic side effects**: No "half-transitioned" states — either everything commits or nothing does.
- **Testable**: Unit tests can exercise every transition path with deterministic assertions.
- **Extensible**: Adding a new state or transition is a single `TransitionRule` addition.

### Negative
- All transition logic centralised in one 600-line file — could become unwieldy with more states.
- Inline imports for `ResolutionProposal` and `Attachment` create loose coupling with challenges module.
- No built-in support for time-based automatic transitions (handled by separate worker jobs).

### Alternatives Considered
- **State pattern (GoF)**: More OOP but scatters transition logic across state classes — harder to audit.
- **External state machine library (transitions, pytransitions)**: Rejected — adds dependency without proportional value for 29 rules.
- **Database-driven transition rules**: Over-engineered — transitions are fixed business logic, not user-configurable.
