# AGENTS.md

This file defines the durable working rules for coding agents operating in the TaskPlanner repository.

Its purpose is to let an agent complete approved work autonomously while preserving product intent, architecture, tests, CI reliability and the GitHub roadmap.

---

## 1. Source of truth

For implementation work, use the following sources in this order:

1. current code and tests on `main`;
2. the GitHub Issue defining the requested work;
3. roadmap maître GitHub issue #1 and its canonical pipeline;
4. architecture/product documentation under `docs/`;
5. relevant PR discussions.

Do not treat previous chat conversations as more authoritative than the repository.

Do not redo an analysis already documented unless code or requirements materially changed.

Always synchronize with the current `main` before starting implementation.

---

## 2. Product authority

TaskPlanner is designed to reduce cognitive load without taking important decisions away from the user.

Durable product rules:

- capture must be low-friction;
- projects may be decomposed into tasks and small actionable segments;
- capacity must be considered before proposing a plan;
- protected work ("must not derail") must be distinct from work that may safely slip;
- the system proposes options and consequences rather than silently deciding;
- significant reprioritization or calendar mutation requires explicit user confirmation;
- deterministic rules own capacity, constraints, conflicts and feasibility;
- AI may assist decomposition, estimation and option generation, but it is not the source of truth for business rules.

Do not implement automation that contradicts these rules without an explicit roadmap/architecture decision.

---

## 3. Main architecture

The target application is:

```text
React + TypeScript + Vite
          ↓
       FastAPI
          ↓
 Application / Domain
          ↓
 Infrastructure
          ↓
 SQLAlchemy / external integrations
```

Expected source areas:

```text
frontend/                 React / TypeScript / Vite
app/main.py               FastAPI composition
app/application/          use cases and application services
app/domain/               business rules and domain model
app/infrastructure/       persistence and integration adapters
tests/                    Python tests
docs/                     product, development and architecture docs
```

Preserve these boundaries unless an approved architectural change explicitly requires otherwise.

### Authority rules

- FastAPI is the mutation boundary for the web application.
- Python domain/application code remains authoritative for planning and capacity rules.
- React must not duplicate authoritative calculations.
- External APIs are accessed through backend adapters, never directly from the browser when secrets or authoritative behavior are involved.
- Integrations must not be required for deterministic unit tests.

---

## 4. Normal development lifecycle

When asked to implement an approved issue or roadmap tranche, continue autonomously through:

```text
understand scope
→ inspect relevant code/docs
→ implement
→ targeted tests
→ broader relevant validation
→ create/update PR
→ CI
→ diagnose/fix normal failures
→ CI green
→ merge when permitted
→ update issue/roadmap #1
→ promote the real next READY item
```

Do not stop simply because implementation is complete, a PR exists or CI has started, unless the user explicitly requested that stop point.

If repository rules prevent merge, report the blocker rather than bypassing it.

---

## 5. Scope discipline

Implement the smallest coherent change that satisfies the issue.

Prefer incremental changes over broad refactors.

Do not:

- redesign unrelated components;
- add speculative abstractions;
- expand an issue into adjacent roadmap work;
- change product semantics merely to simplify implementation;
- hide unresolved product decisions inside frontend behavior.

Useful neighboring cleanup that is not necessary belongs in a separate issue.

---

## 6. Backend rules

For backend changes:

- keep business rules in application/domain layers;
- keep HTTP routes thin;
- use stable IDs instead of display labels for relationships;
- preserve API contracts unless the issue changes them;
- keep planning proposals separate from accepted decisions;
- make meaningful state transitions explicit and testable;
- treat user confirmation as a real domain/application boundary where required.

Planning rules must expose enough information to explain why a proposal is feasible or conflicting.

---

## 7. Frontend rules

For frontend changes:

- consume backend projections instead of recreating business rules;
- preserve loading, empty and error states;
- optimize capture and daily review for low friction;
- make protected vs flexible work visually understandable;
- show proposed consequences before applying meaningful plan changes;
- do not silently mutate priorities or calendar commitments.

Production validation requires:

```bash
cd frontend
npm run build
```

---

## 8. Persistence and migrations

SQLite is the initial local persistence target. SQLAlchemy is the persistence abstraction.

Once persistent domain tables exist:

- use explicit migrations rather than ad-hoc schema mutation;
- preserve data unless destructive change is explicitly approved;
- keep domain concepts distinct even when fields overlap;
- do not use names or UI labels as durable identifiers.

Do not introduce PostgreSQL or another production database merely by assumption; that is a roadmap/architecture decision.

---

## 9. External integrations

Google Calendar / Reclaim and OpenAI are optional integrations around the core domain.

Rules:

- core development and tests must run without live external credentials;
- use adapters/ports around external APIs;
- keep secrets server-side;
- prefer read/propose/confirm flows before write automation;
- calendar writes require an explicit product rule and user confirmation;
- a failed external integration must not corrupt local planning state.

---

## 10. AI boundary

AI may suggest:

- decomposition;
- clearer next actions;
- duration ranges;
- dependencies;
- clarification questions;
- prioritization options;
- possible postpone/delegate/reduce-scope choices.

AI must not be the sole authority for:

- hard deadlines;
- capacity arithmetic;
- protected constraints;
- conflict detection;
- committed calendar mutations;
- irreversible state transitions.

Persist deterministic facts separately from AI-generated suggestions.

---

## 11. Validation

Backend baseline:

```bash
python -m compileall -q app tests
pytest -q
```

Frontend baseline:

```bash
cd frontend
npm install --no-audit --no-fund
npm run build
```

Run the smallest relevant tests first, then the broader validation required by the change.

Do not weaken a meaningful test only to make CI green.

---

## 12. Privacy and secrets

Never commit:

- passwords;
- API keys;
- OAuth client secrets;
- access/refresh tokens;
- production database credentials;
- private calendar data;
- local `.env` files.

Use `.env.example` for non-secret configuration examples.

Diagnostics must not print secret values.

---

## 13. Pull requests

A PR should represent one coherent issue or sub-tranche.

The description should summarize:

- requested change;
- implementation;
- important decisions;
- validation performed;
- migration/compatibility implications;
- known limitations.

When the work is complete and repository rules allow it, merge only after required CI is green.

---

## 14. GitHub roadmap updates

The canonical roadmap is GitHub issue #1. There is no canonical `ROADMAP.md`.

After a merged issue/sub-tranche:

- update issue #1 when its state/order changed;
- mark only work actually complete;
- keep human roadmap prose aligned with the canonical block;
- promote only the true next MAIN item to `READY`;
- keep later MAIN items `BLOCKED` unless explicitly parallelized.

### COCKPIT_PIPELINE_V1 contract

When issue #1 contains `COCKPIT_PIPELINE_V1`, it is the machine-readable work-order contract.

Any change to work order or completion state must:

- update the canonical block in the same roadmap edit;
- preserve stable keys;
- mark merged/completed work `DONE`;
- promote the actual next MAIN step to `READY`;
- keep later MAIN steps `BLOCKED`;
- never substitute PR numbers, CI runs or commit SHAs for step identity.

Do not store the active/next roadmap item in this file. `AGENTS.md` contains durable rules; issue #1 contains current product state.

---

## 15. Architecture decisions

Use ADRs under `docs/architecture/` for decisions that are structural, durable or costly to reverse.

Create/update an ADR when work changes, for example:

- domain boundaries;
- persistence strategy;
- integration authority;
- calendar mutation semantics;
- AI authority;
- concurrency/versioning model;
- authentication/authorization model.

Do not create an ADR for every small implementation detail.

---

## 16. Stop / escalation conditions

Stop and surface the decision instead of guessing when implementation requires:

- destructive data migration;
- a new external system or structural dependency not approved by the roadmap;
- a breaking public API contract with unclear migration semantics;
- ambiguous rules about protected commitments or user confirmation;
- security/authentication decisions not established by an issue/ADR;
- conflicting architecture decisions.

Normal coding defects and CI failures are not escalation conditions; diagnose and correct them autonomously.
