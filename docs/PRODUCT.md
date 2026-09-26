# TaskPlanner — principes produit

## Problème à résoudre

Les tâches arrivent de plusieurs sources et restent facilement en tête plutôt que dans un système fiable. Les projets trop gros créent de la friction d'amorçage; un plan trop ambitieux crée ensuite de la procrastination, des retards et une impression de surcharge.

TaskPlanner doit rendre la situation concrète :

- ce qui existe;
- ce qui est réellement faisable;
- ce qui ne doit pas dérailler;
- ce qui peut glisser;
- quels compromis sont disponibles.

## Modèle mental

Le produit part du modèle suivant :

```text
Inbox
  ↓
Project
  ↓
Task
  ↓
TaskSegment
  ↓
PlanningProposal
  ↓
User decision
```

Les catégories ou blocs de temps sont des contraintes/capacités, pas des tâches.

## Politique de décision

TaskPlanner ne doit pas "prendre le contrôle" du calendrier.

Quand une surcharge ou un conflit existe, l'application présente des options et leurs conséquences. L'utilisateur choisit l'action à appliquer.

Les mutations significatives doivent donc distinguer :

1. le fait observé;
2. la proposition;
3. la décision acceptée;
4. l'état appliqué.

## Travail protégé et travail flexible

La première classification cible est :

- **PROTECTED** — ne doit pas dérailler sans décision explicite;
- **REPLANNABLE** — important, mais peut être déplacé avec un compromis;
- **FLEXIBLE** — peut glisser avec un coût limité.

Cette classification n'est pas encore un schéma de base de données; elle doit être stabilisée dans TP-002.

## IA

L'IA peut réduire la friction cognitive en aidant à :

- reformuler une tâche;
- proposer une première action;
- décomposer un projet;
- estimer une fourchette de durée;
- proposer des dépendances;
- présenter des options d'arbitrage.

Les contraintes et la capacité restent déterministes. Une suggestion IA n'est jamais un engagement utilisateur.
