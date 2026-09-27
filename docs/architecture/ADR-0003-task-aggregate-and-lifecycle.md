# ADR-0003 — Agrégat Task, segments et cycle de vie

**Statut : Accepted**  
**Date : 2026-09-27**

## Contexte

TP-011 introduit la structure persistante `Project → Task → TaskSegment`.

Le noyau livré par TP-002 possède déjà des UUID stables et les concepts `Project`, `Task` et `TaskSegment`. TP-010 a ajouté la capture persistante en statut `INBOX`.

La prochaine évolution doit permettre la clarification, la décomposition et la progression sans créer plusieurs sources de vérité ni détruire l'identité d'une capture.

## Décision

### Task comme frontière de cohérence

`Task` gouverne les mutations de ses segments.

Un `TaskSegment` :

- possède un UUID stable;
- appartient à exactement une tâche;
- ne peut pas être transféré vers une autre tâche dans TP-011;
- est persisté séparément pour pouvoir être référencé durablement;
- ne possède pas un cycle de vie métier autonome de sa tâche.

Les commandes qui modifient une tâche et ses segments sont atomiques : l'application orchestre une transaction unique et les repositories ne valident pas individuellement leurs écritures.

### Project

`Project` est une entité persistante indépendante.

Une tâche peut rester sans projet.

Le rattachement d'une tâche exige un projet existant et actif.

`Project.COMPLETED` signifie que le travail ouvert du projet est terminé : la transition est refusée tant qu'une tâche du projet est `INBOX`, `TODO` ou `IN_PROGRESS`.

La sémantique exacte de `ARCHIVED` n'est pas figée par TP-011. Elle ne doit pas être automatiquement assimilée à `COMPLETED`.

Fermer un projet ne modifie jamais implicitement les statuts de ses tâches.

### Cycle de vie de Task

Les statuts restent :

- `INBOX` : capture conservée mais non clarifiée;
- `TODO` : travail clarifié, non commencé;
- `IN_PROGRESS` : travail commencé;
- `DONE` : résultat explicitement atteint;
- `CANCELLED` : travail explicitement abandonné.

Clarifier une capture :

1. charge la tâche existante;
2. applique les précisions et relations valides;
3. fait passer `INBOX → TODO`;
4. conserve l'UUID et `created_at`;
5. persiste le tout dans une transaction unique.

Une édition ordinaire de titre ou de notes ne clarifie pas implicitement une tâche Inbox.

Une tâche terminée reste éditable pour ses métadonnées. Modifier sa structure de travail exige une réouverture explicite.

### Cycle de vie de TaskSegment

Les segments ont un enum distinct `SegmentStatus` :

- `TODO`;
- `IN_PROGRESS`;
- `DONE`;
- `CANCELLED`.

`INBOX` n'est jamais valide pour un segment.

Commencer ou terminer un segment d'une tâche `TODO` fait progresser la tâche vers `IN_PROGRESS`.

La fin de tous les segments ne passe pas automatiquement la tâche à `DONE`. Elle rend la tâche prête à une clôture explicite.

Une tâche décomposée ne peut être complétée tant qu'un segment actif reste ouvert.

L'annulation de tous les segments ne signifie pas que le résultat de la tâche a été atteint.

### Ordre et identité

L'ordre des segments est explicite et indépendant de l'UUID ou de la date de création.

Réordonner un segment conserve son UUID.

Les dépendances entre segments et les segments imbriqués sont hors périmètre de TP-011.

### Suppression

Aucune cascade destructive implicite n'est utilisée pour exprimer une décision métier.

Un segment `TODO` qui n'a jamais progressé peut être supprimé explicitement.

Un segment ayant progressé ne doit pas disparaître silencieusement : sa sortie du travail actif passe par une transition métier explicite, notamment `CANCELLED`.

TP-011 n'introduit pas de soft-delete généralisé obligatoire.

### Protection

`ProtectionLevel` reste porté par `Task`.

Les segments héritent de la protection de leur tâche. Les surcharges de protection par segment sont réservées à TP-021.

## Persistance

TP-011 introduit au minimum :

- `projects`;
- `work_types`;
- `task_segments`;
- les clés étrangères nécessaires depuis `tasks`.

Les relations utilisent des UUID stables.

Aucune relation métier n'utilise un nom ou libellé comme identifiant.

Sous SQLite, les connexions runtime et de test activent réellement les clés étrangères.

Les migrations Alembic préservent les captures existantes et ne réécrivent pas la migration TP-010.

## Concurrence

La concurrence optimiste via un champ `Task.version` est reportée.

Elle pourra être introduite lorsqu'un besoin concret de mutations concurrentes le justifiera. TP-011 ne doit pas inventer un mécanisme de versionnement de plan avant son besoin.

## Conséquences

- une capture peut évoluer sans perte d'identité;
- les segments sont référencables durablement sans devenir des agrégats autonomes;
- les transitions restent explicites et testables;
- une transaction échouée ne laisse pas une tâche partiellement clarifiée ou réordonnée;
- aucune clôture ou suppression ne masque implicitement du travail actif;
- TP-020 et les futures intégrations peuvent s'appuyer sur des identités stables.
