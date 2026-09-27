# ADR-0005 — Historique comportemental et faits métier

**Statut : Accepted**  
**Date : 2026-09-27**

## Contexte

TaskPlanner doit pouvoir apprendre ultérieurement des habitudes de planification : travail régulièrement repoussé, estimations révisées, bénéfice de la segmentation, difficultés d'amorçage ou motifs de report.

Ces analyses ne peuvent pas être reconstruites fidèlement à partir du seul état courant. Une estimation finale ne révèle pas ses révisions antérieures; une tâche aujourd'hui complétée ne révèle pas les reports, réouvertures ou changements de contexte qui ont précédé sa clôture.

L'objectif est donc de commencer à conserver des faits métier structurés dès l'introduction des mutations TP-011, sans transformer TaskPlanner en système event-sourced.

## Décision

### État courant autoritaire

Les tables métier courantes restent la source de vérité pour charger et exécuter TaskPlanner.

L'historique est complémentaire :

- aucun rejeu d'événements n'est requis pour reconstruire une `Task`;
- aucun composant métier ne dépend d'un bus d'événements;
- aucune projection analytique ni IA n'est requise pour exécuter le cœur du produit.

La chaîne cible est :

```text
faits métier
→ historique append-only
→ projections/statistiques déterministes
→ analyse ou hypothèse IA
→ proposition
→ décision utilisateur
```

Les projections analytiques et l'IA sont hors périmètre de TP-011.

### Événements sémantiques

L'historique conserve des événements métier explicites, pas des changements SQL déduits.

Exemples TP-011 :

- `TASK_CAPTURED`;
- `TASK_CLARIFIED`;
- `TASK_STARTED`;
- `TASK_COMPLETED`;
- `TASK_CANCELLED`;
- `TASK_REOPENED` lorsqu'une telle commande existe;
- `TASK_ESTIMATE_CHANGED`;
- `TASK_WORK_TYPE_CHANGED`;
- `SEGMENT_ADDED`;
- `SEGMENT_STARTED`;
- `SEGMENT_COMPLETED`;
- `SEGMENT_CANCELLED`;
- `SEGMENT_REMOVED`;
- `SEGMENT_ESTIMATE_CHANGED`;
- `SEGMENT_WORK_TYPE_CHANGED`.

Un événement n'est émis que lorsqu'un fait métier a réellement changé. Réenregistrer une valeur identique ne crée pas un faux événement.

Les événements projet, protection, échéance et réorganisation peuvent être ajoutés avec leurs commandes lorsqu'ils deviennent utiles, mais ne conditionnent pas le noyau initial.

### Contrat HistoryEvent

Le contrat minimal comprend :

- `id` : UUID stable;
- `occurred_at` : instant UTC du fait;
- `recorded_at` : instant UTC d'enregistrement;
- `entity_type` : type contrôlé;
- `entity_id` : UUID de l'objet directement concerné;
- `task_id` : UUID de la tâche racine pour les événements Task/Segment;
- `event_type` : type sémantique explicite;
- `schema_version` : version du contrat de payload;
- `source` : origine immédiate du fait;
- `reason_code` : motif structuré facultatif;
- `correlation_id` : identifie une commande métier;
- `causation_id` : événement causal connu, facultatif;
- `payload` : delta et contexte autorisés pour ce type d'événement.

Une `note` libre n'est pas collectée par défaut dans TP-011.

Une identité d'acteur pourra être ajoutée lorsqu'un modèle d'identité applicative existe réellement.

### Payload typé et versionné

Le payload ne contient ni snapshot complet de l'entité, ni requête HTTP brute, ni objet ORM sérialisé.

Chaque `event_type` définit un contrat de payload avec liste positive de champs.

Exemple conceptuel :

```json
{
  "estimated_minutes": {
    "before": null,
    "after": 45
  },
  "context": {
    "effective_work_type_id": "uuid",
    "has_segments": false
  }
}
```

Les valeurs inconnues restent `null`; elles ne sont jamais converties en zéro.

Le contexte capturé doit être le minimum nécessaire à l'interprétation future du fait. Une transition peut notamment conserver le WorkType effectif et l'estimation pertinente au moment du changement sans copier le contenu textuel de la tâche.

### Source, corrélation et causalité

`source` décrit l'origine immédiate du fait. Le noyau prévoit :

- `USER`;
- `SYSTEM_RULE`;
- `IMPORT`;
- `AI`.

La source est déterminée côté backend et n'est pas une valeur libre imposable par React.

La relation avec une proposition ou décision future n'est pas encodée comme une source hybride. Lorsqu'elles existeront, les références telles que `proposal_id`, `option_id` ou `decision_id` seront conservées dans le contrat approprié.

Ainsi, une suggestion provenant de l'IA puis acceptée par l'utilisateur reste distinguable entre :

- origine de la suggestion;
- décision utilisateur;
- application déterministe;
- résultat observé.

Tous les événements d'une même commande partagent un `correlation_id`.

Lorsqu'une action produit une conséquence automatique, celle-ci est un événement distinct avec `source=SYSTEM_RULE` et peut référencer l'événement causal.

Exemple : commencer un segment peut produire :

- `SEGMENT_STARTED`, source `USER`;
- `TASK_STARTED`, source `SYSTEM_RULE`.

Ces faits ne représentent pas deux démarrages indépendants.

### Raisons structurées

`reason_code` est facultatif.

L'absence de motif reste `NULL`; elle ne signifie pas `USER_CHOICE`.

Les codes sont définis dans le code applicatif avec une sémantique stable et sont stockés comme texte, afin de pouvoir faire évoluer le catalogue sans migration SQL pour chaque ajout.

Les motifs admissibles dépendent du type d'événement.

Exemples futurs ou actuels selon les commandes :

- `HIGHER_PRIORITY`;
- `INTERRUPTION`;
- `BLOCKED`;
- `MISSING_INFORMATION`;
- `LOW_ENERGY`;
- `UNDER_ESTIMATED`;
- `OVER_ESTIMATED`;
- `DEPENDENCY`;
- `TIME_UNAVAILABLE`;
- `USER_CHOICE`;
- `OTHER`.

Un motif est une donnée déclarée, pas une causalité démontrée. TaskPlanner ne doit pas inférer automatiquement `UNDER_ESTIMATED` d'une simple hausse d'estimation.

### Émission et atomicité

Les faits de mutation sont produits par le domaine ou le cas d'usage applicatif, jamais déduits depuis SQLAlchemy, FastAPI ou React.

Le flux d'une commande est :

1. ouvrir l'unité de travail;
2. charger l'état;
3. exécuter la mutation métier;
4. obtenir les faits sémantiques;
5. construire les `HistoryEvent` avec horloge, source et corrélation;
6. enregistrer état courant et historique;
7. effectuer un seul commit.

Les repositories partagent la transaction et ne font pas de commit autonome.

L'insertion de l'historique est obligatoire pour les mutations couvertes. Si l'historique échoue, la mutation opérationnelle échoue aussi. Si la mutation échoue, aucun événement correspondant ne subsiste.

Aucun bus, outbox, middleware HTTP, hook ORM ou tâche asynchrone n'est requis pour ce journal local.

### Persistance

Une table unique `history_events` suffit pour le socle initial.

Schéma conceptuel :

```text
history_events
  sequence        INTEGER PRIMARY KEY AUTOINCREMENT
  id              UUID/TEXT UNIQUE NOT NULL
  occurred_at     UTC NOT NULL
  recorded_at     UTC NOT NULL
  entity_type     TEXT NOT NULL
  entity_id       UUID/TEXT NOT NULL
  task_id         UUID/TEXT NULL
  event_type      TEXT NOT NULL
  schema_version  INTEGER NOT NULL
  source          TEXT NOT NULL
  reason_code     TEXT NULL
  correlation_id  UUID/TEXT NOT NULL
  causation_id    UUID/TEXT NULL
  payload         JSON/TEXT NOT NULL
```

Index initiaux :

- `(task_id, sequence)`;
- `(entity_type, entity_id, sequence)`;
- `(correlation_id, sequence)`.

L'UUID est l'identité publique. `sequence` fournit seulement un ordre local stable d'enregistrement.

Les références historiques vers des objets ayant existé ne sont pas des FK destructives vers les tables courantes. Un segment supprimé opérationnellement reste identifiable dans l'historique.

La migration qui introduit l'historique ne fabrique aucun événement rétroactif pour les captures antérieures. Une période sans instrumentation signifie « non observée », pas « absence d'activité ».

### Immutabilité et correction

Les événements sont append-only dans le fonctionnement métier normal.

Le repository d'historique expose des opérations d'ajout, pas une mise à jour générique.

Les corrections sémantiques futures peuvent être représentées par un événement de correction ou d'invalidation.

Cette immutabilité ne doit jamais empêcher un effacement réel nécessaire pour la vie privée. Une purge contrôlée reste une opération exceptionnelle distincte des commandes métier ordinaires.

### Minimisation et vie privée

L'historique utilise une liste positive de données autorisées.

Il ne copie pas automatiquement :

- titres ou descriptions;
- notes de tâches;
- contenu de calendrier;
- participants ou lieux;
- courriels;
- prompts ou réponses IA complets;
- contexte personnel inféré;
- secrets, jetons ou détails HTTP.

Une future intégration IA ne reçoit pas l'historique brut par défaut. Elle consomme uniquement des projections ou données explicitement nécessaires au cas d'usage.

La politique de rétention configurable et l'interface de purge peuvent être ajoutées ultérieurement.

### Limites d'interprétation

Les faits doivent rester descriptifs.

En particulier :

- `completed_at - started_at` est un délai écoulé, pas une mesure de temps travaillé;
- une hausse d'estimation n'est pas nécessairement une sous-estimation;
- un report ne prouve pas sa cause;
- une corrélation statistique n'établit pas une causalité;
- l'acceptation d'une proposition ne prouve pas son efficacité;
- la génération d'une suggestion ne constitue ni une décision ni un résultat.

La future IA formule des hypothèses et des propositions, elle ne transforme pas ces observations en conclusions certaines.

## Impact sur TP-011

### TP-011A

Ajoute :

- contrats de faits métier;
- types/version des événements;
- deltas structurés;
- distinction action directe / propagation système;
- absence d'événement sur mutation sans changement réel.

### TP-011B

Ajoute :

- table `history_events`;
- repository append-only;
- unité de travail commune aux repositories;
- retrait du commit interne de `SqlTaskRepository`;
- écriture atomique état + historique;
- instrumentation de la capture actuelle avec `TASK_CAPTURED`;
- tests de rollback dans les deux directions.

### TP-011C

Ajoute les événements associés aux commandes réellement livrées, notamment :

- `TASK_CLARIFIED`;
- changements d'estimation;
- changements de WorkType.

Une clarification enrichie peut produire plusieurs événements partageant la même corrélation.

### TP-011D

Ajoute les événements de segments et de progression réellement livrés :

- ajout;
- démarrage;
- complétion;
- annulation;
- suppression autorisée;
- révision d'estimation;
- changement de WorkType;
- propagation éventuelle du statut parent.

Aucun écran d'historique n'est requis pour terminer TP-011.

## Hors périmètre de TP-011

- consultation/export de l'historique;
- projections statistiques;
- analyse IA;
- mesure du temps réellement consommé;
- événements de planification avant l'existence du moteur correspondant;
- corrections/invalidation exposées dans l'UI;
- rétention configurable;
- identité détaillée des acteurs;
- idempotence générale des imports;
- bus d'événements;
- outbox sans consommateur;
- CQRS complet;
- event sourcing;
- entrepôt analytique;
- base vectorielle;
- pipeline ML.

## Conséquences

- les changements comportementaux commencent à être observables dès TP-011;
- les futures analyses peuvent distinguer faits, règles système, suggestions, décisions et résultats;
- l'état courant reste simple et autoritaire;
- l'historique ne devient pas une copie du contenu personnel;
- l'atomicité impose une vraie unité de travail applicative dans TP-011B;
- les données historiques pourront alimenter des projections déterministes avant toute analyse IA.
