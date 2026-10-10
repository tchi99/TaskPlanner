# Architecture

Ce dossier contient les Architecture Decision Records (ADR) de TaskPlanner.

## ADR acceptés

- [ADR-0001](./ADR-0001-foundational-architecture.md) — architecture fondatrice;
- [ADR-0002](./ADR-0002-domain-model.md) — noyau de domaine et frontière proposition/décision;
- [ADR-0003](./ADR-0003-task-aggregate-and-lifecycle.md) — agrégat Task, segments et cycle de vie;
- [ADR-0004](./ADR-0004-work-units-and-projections.md) — unités de travail, estimation et projections déterministes;
- [ADR-0005](./ADR-0005-behavioral-history.md) — historique comportemental et faits métier;
- [ADR-0006](./ADR-0006-weekly-capacity.md) — disponibilité hebdomadaire manuelle et faisabilité;
- [ADR-0009](./ADR-0009-google-calendar-read.md) — calendrier externe en surcouche de lecture seule.

- [ADR-0015](./ADR-0015-start-assistance.md) — amorçage non autoritaire et point de reprise;

- [ADR-0018](./ADR-0018-supabase-auth-and-api-boundary.md) — identité Supabase, JWT/JWKS et frontière API;

## Convention

Chaque ADR doit contenir au minimum :

- contexte;
- décision;
- conséquences;
- statut.

Format recommandé :

```text
ADR-0001-titre-court.md
ADR-0002-autre-decision.md
```

Statuts usuels :

- Proposed
- Accepted
- Superseded
- Rejected

Les ADR documentent les décisions durables. Le roadmap courant reste dans l'issue GitHub #1.
