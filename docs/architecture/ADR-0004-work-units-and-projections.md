# ADR-0004 — Unités de travail, estimation et projections déterministes

**Statut : Accepted**  
**Date : 2026-09-27**

## Contexte

TaskPlanner doit pouvoir décomposer une tâche tout en préparant TP-020 — capacité hebdomadaire.

Sans règle explicite, conserver une estimation sur `Task` et des estimations sur ses `TaskSegment` créerait un risque de double comptage. La prochaine action, le type de travail effectif et l'état de préparation à la clôture pourraient aussi devenir plusieurs champs synchronisés manuellement.

## Décision

### Une seule source de charge effective

La charge est calculée sur les feuilles du travail :

- tâche ouverte sans segment actif → la tâche est l'unité de travail;
- tâche ouverte avec segments actifs → les segments sont les unités de travail;
- le parent et les enfants ne sont jamais comptés simultanément.

Les captures `INBOX`, les tâches terminales et les segments terminaux ne constituent pas de la charge ouverte.

TP-011 ne décide pas encore quelle partie du backlog appartient à une semaine donnée.

### Estimation

`estimated_minutes` reste une estimation d'effort.

`NULL` signifie « estimation inconnue » et ne doit jamais être converti en zéro.

Lorsqu'une tâche n'est pas décomposée, `Task.estimated_minutes` est son estimation effective.

Lorsqu'une tâche possède des segments actifs :

- les estimations des segments deviennent la source de charge;
- `Task.estimated_minutes` peut rester stocké comme estimation globale de référence;
- l'estimation parent n'est pas additionnée aux segments;
- elle n'est pas écrasée automatiquement par leur somme.

Une projection doit distinguer :

- la source de l'estimation : tâche ou segments;
- le sous-total connu;
- le nombre d'unités non estimées;
- le total effectif, nullable lorsqu'il reste une estimation inconnue;
- la présence de charge ouverte non estimée.

Exemple : estimation globale 120 min, segment A 20 min, segment B inconnu. Le total effectif reste inconnu; il n'est ni 20 ni 140.

### Prochaine action

La prochaine action est dérivée dans le backend et n'est pas persistée.

Ordre déterministe :

1. `Task.INBOX` → clarifier la tâche;
2. tâche terminale → aucune prochaine action;
3. tâche ouverte sans segment actif → la tâche elle-même;
4. tâche décomposée → premier segment `IN_PROGRESS` selon l'ordre;
5. sinon → premier segment `TODO`;
6. aucun segment ouvert → revue/clôture explicite de la tâche.

Aucun champ `next_action_text`, `next_segment_id` ou `is_next` ne devient une seconde source de vérité.

### Progression

Le démarrage d'un segment fait progresser une tâche `TODO` vers `IN_PROGRESS`.

Tous les segments terminaux rendent la tâche « prête à clôturer », mais `Task.DONE` reste une décision explicite.

Une tâche ne revient pas automatiquement à `TODO` lorsque sa structure change.

### WorkType

`WorkType` est persisté comme référentiel configurable.

Pour une tâche sans segments, le type de travail effectif est celui de la tâche.

Pour un segment :

- un `work_type_id` explicite surcharge la tâche;
- `NULL` signifie hériter du type de la tâche;
- si les deux sont absents, l'unité est non classée.

TP-020 devra regrouper les unités de travail selon ce type effectif sans recompter le parent.

### Protection effective

Dans TP-011, la protection effective d'un segment est celle de sa tâche.

Aucune règle de combinaison parent/enfant n'est introduite avant TP-021.

### Frontend

React consomme des projections backend et ne recalcule pas les règles ci-dessus.

Les projections destinées à l'interface exposent au minimum, selon le contexte :

- prochaine action;
- progression;
- estimation effective et son caractère incomplet;
- type de travail explicite/effectif;
- protection effective;
- actions métier actuellement autorisées.

Les états chargement, vide et erreur restent distincts.

## Hors périmètre

- temps réellement consommé;
- reste à faire détaillé;
- sélection hebdomadaire de charge;
- règles de glissement;
- dépendances entre segments;
- blocs calendrier;
- persistance des propositions de plan;
- IA.

## Conséquences

- TP-020 dispose d'une définition déterministe des unités de travail;
- aucune estimation parent/enfant n'est comptée deux fois;
- une estimation inconnue reste visible comme incertitude;
- la prochaine action ne peut pas devenir périmée par désynchronisation;
- React reste une couche de présentation;
- les futurs time blocks pourront référencer une tâche ou un segment stable sans faire du segment un créneau de calendrier.
