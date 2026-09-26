# ADR-0002 — Noyau de domaine et frontière proposition/décision

**Statut : Accepted**  
**Date : 2026-09-26**

## Contexte

TaskPlanner doit pouvoir raisonner sur des projets, tâches, segments, contraintes et options de planification sans dépendre du stockage, de FastAPI, de React ou d'une intégration externe.

Le produit doit également préserver une distinction durable entre ce que le système propose et ce que l'utilisateur décide.

## Décision

Le noyau initial est composé de valeurs/entités Python pures sous `app/domain/` :

- `Project`;
- `Task`;
- `TaskSegment`;
- `WorkType`;
- `Constraint`;
- `PlanningOption`;
- `PlanningProposal`;
- `PlanningDecision`.

Les identités sont des UUID stables.

Le niveau de protection est explicite :

- `PROTECTED`;
- `REPLANNABLE`;
- `FLEXIBLE`.

`WorkType` est une donnée de domaine identifiable et non un enum fermé afin de permettre des types de travail configurables sans modifier le code.

Une `PlanningProposal` contient une ou plusieurs options mais n'enregistre aucune acceptation. Une `PlanningDecision` est un objet séparé qui référence la proposition et, en cas d'acceptation, une option valide.

Les dates métier représentées par `datetime` doivent être timezone-aware.

## Conséquences

- le moteur futur peut être testé sans base de données ni calendrier externe;
- les types de travail peuvent évoluer sans migration de code enum;
- une proposition ne peut pas devenir implicitement une décision;
- la persistance SQLAlchemy pourra mapper ce modèle plus tard sans devenir l'autorité métier;
- les futurs use cases devront appliquer explicitement une décision plutôt que muter un plan à la création d'une proposition.
