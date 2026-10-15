# ADR-0022 — Édition hebdomadaire atomique et révisions temporelles (ASTRA-TP023)

**Statut : Accepted (décisions produit approuvées le 2026-10-15)**  
**Date : 2026-10-15**  
**WorkItem : ASTRA-TP023 / TP-023 (issue #52)**  
**Roadmap maître : issue #1**  
**Références : ADR-0002, ADR-0005, ADR-0006, ADR-0020, ADR-0021; issues #43, #50, #52.**  
**Autorisation : documentation du gate seulement. TP-023A/B/C restent BLOCKED; TP-080D reste en standby jusqu'à nouvel ordre.**

## Contexte et problème

L'interface actuelle représente l'horaire récurrent comme une liste de règles à réviser individuellement; « Semaine réelle » crée des exceptions pour une occurrence datée. L'utilisateur demande un **éditeur hebdomadaire direct**, par jour et type de disponibilité, inspiré de la facilité d'usage de Reclaim, avec activation des jours, plusieurs intervalles, édition, retrait et copie entre jours.

L'analyse ASTRA-TP023 a vérifié sur `main@3e2ea9895d58799d28ac931f6251c03fc3fdbfea` les lacunes suivantes :

- `create_rule` / `revise_rule` ouvrent chacune leur unité de travail et effectuent leur propre commit : plusieurs PATCH/POST ne forment pas une sauvegarde atomique.
- Une `RecurringAvailabilityRule` peut être partagée par plusieurs `days_of_week` : éditer le mardi ne doit pas altérer les autres jours.
- Les révisions supposent un ordre des `effective_from` strictement croissant, avec unicité SQL `(rule_id, effective_from)` : deux sauvegardes au même jour ou l'édition avant un changement futur déjà programmé sont actuellement impossibles.
- Les exceptions sont liées à `(rule_id, original_local_date)`; une division de série peut nécessiter leur remappage.
- Le fournisseur de projection effective, la sérialisation des écritures SQLite/PostgreSQL, l'audit append-only et le protocole de résolution des réservations existent déjà et doivent être réutilisés.

**Décision structurante : TP-023A est nécessaire** pour le contrat temporel et la sauvegarde groupée; une refonte frontend seule ne peut pas garantir les invariants.

## Décisions produit expressément approuvées le 2026-10-15

### 1. Retrait d'une plage catégorisée dans l'enveloppe générale

Lorsqu'une plage récurrente affectée à un `WorkType` est retirée alors que l'enveloppe générale couvre toujours la période, cette période **redevient du temps général `NULL`**, et non du temps du type précédent. Le moteur **n'emprunte jamais automatiquement `NULL`** pour un autre WorkType : toute affectation suit les propositions et consentements d'ADR-0020.

Pour retirer **toute** disponibilité pendant la période, il faut modifier l'enveloppe générale ou déclarer une indisponibilité pertinente, avec ses conséquences et conflits.

Cette opération est **distincte** de « annuler cette occurrence » par une exception `CANCEL`, qui retire la disponibilité de cette occurrence **sans reconstituer `NULL`** conformément à ADR-0020. Les libellés UX et l'aperçu doivent rendre la distinction explicite.

### 2. Remplacement de changements futurs déjà programmés

Pour les **jours et sections explicitement sélectionnés**, un nouvel horaire enregistré à sa date d'effet remplace la configuration future correspondante **à compter de cette date**, y compris les changements ultérieurs déjà programmés. L'aperçu doit identifier les révisions futures rendues inapplicables et leurs conséquences.

Les jours/sections **non sélectionnés** conservent intégralement leur chronologie future, même lorsqu'ils étaient historiquement dans la même série multi-jours. Le passé et toutes les révisions historiques restent auditables : remplacer une configuration future n'est pas effacer un enregistrement historique.

### 3. Première application au plus tôt demain

En V1, la sauvegarde de l'horaire habituel ne peut prendre effet **avant le lendemain civil** de la date courante dans le fuseau **IANA de la règle**. L'éditeur indique clairement la date d'effet et interdit tout changement rétroactif ou d'une occurrence déjà commencée. Les besoins portant sur **aujourd'hui** sont traités par les dérogations de « Semaine réelle », sans modifier le passé.

La date est une **date civile locale** (pas un instant UTC par défaut). Les conversions, transitions DST, heures ambiguës/inexistantes et intervalles sont traités par le domaine déterministe comme dans ADR-0020.

## Décision d'architecture

### A. Une vue de grille calculée, pas un deuxième modèle autoritaire

La grille est une **projection à la date d'effet choisie** des règles/révisions et exceptions existantes. Le backend reste l'autorité sur les séries, changements futurs, conflits et minutes; React ne déduit ni les minutes libres ni les versions effectives.

Chaque intervalle conserve une identité/source stable (règle et révision, ou identifiant temporaire de brouillon). Ne pas recréer ou normaliser toutes les séries simplement parce que l'utilisateur ouvre l'éditeur.

Le brouillon distingue explicitement :
- **jour/section absent(e)** : aucune modification;
- **jour/section explicitement présent(e) avec plages vides** : jour désactivé pour cette section à la date d'effet;
- **jour/section présent(e) avec intervalles** : remplacer uniquement son horaire futur par les intervalles décrits.

Copier un jour vers plusieurs destinataires est une transformation de brouillon, non une série d'écritures serveur immédiates. L'aperçu nomme les jours cibles et les plages remplacées.

### B. Commande applicative de lot : brouillon → aperçu → confirmation

Proposer une surface dédiée (noms indicatifs, contrat à fixer dans TP-023A) :

- `GET /api/availability/weekly-schedule` : lire l'état à une date d'effet, les identifiants et versions sources, et les changements futurs pertinents;
- `POST /api/availability/weekly-schedule/preview` : normaliser le brouillon, calculer la transformation de séries et les conséquences **sans mutation**;
- `POST /api/availability/weekly-schedule/confirm` : confirmer avec empreinte, versions et consentement explicite, puis sauvegarder **en une transaction atomique**.

La commande décrit le fuseau et la date d'effet, les sections/jours visés, les intervalles avec identité stable, les versions attendues des ressources pertinentes et les décisions explicites sur exceptions. L'aperçu rapporte **avant/après**, divisions de séries, révisions futures supplantées, exceptions, réservations affectées, conflits et évolution de capacité.

La confirmation inclut une empreinte calculée sur le contenu normalisé, le périmètre temporel, la version d'algorithme, les versions d'état pertinentes et les conséquences, ainsi qu'un identifiant de commande stable et l'acceptation explicite. L'empreinte n'est pas une garantie durable; le serveur revalide sous verrou. Une réponse `409 Conflict` exige un nouvel aperçu, **sans mutation partielle**.

### C. Divisions ciblées de séries multi-jours

**Préserver les séries existantes** tant que le comportement demandé n'exige pas de division. Pour le mardi d'une règle couvrant lundi–vendredi :
1. conserver la série originale et ses occurrences passées;
2. à partir de la date d'effet, détacher le mardi dans une série dérivée ou une révision ciblée dont l'identité est traçable;
3. conserver lundi/mercredi/jeudi/vendredi avec **toutes leurs révisions futures**, pas seulement la configuration visible aujourd'hui;
4. remplacer les futures configurations du mardi qui seraient incompatibles avec la nouvelle demande;
5. inventorier les exceptions du mardi à remapper ou à arbitrer avant toute confirmation.

La correspondance entre ancienne et nouvelle identité doit être explicite et historisée. Une exception future compatible reste conservée; un remappage certain peut être proposé; si le lien ou la portée est ambiguë, l'aperçu exige une décision explicite parmi les options applicables d'ADR-0020. Une exception `CANCEL` **ne devient jamais un ajout**. Détecter les collisions de clés uniques des exceptions lors d'un remappage. Ne jamais effacer silencieusement une exception.

### D. Séparer la date d'effet de l'ordre d'enregistrement des révisions

Le numéro de révision est l'ordre d'enregistrement/audit, **pas** la clé unique de l'ordre temporel métier. Les révisions restent **immuables**; plusieurs révisions peuvent avoir une date d'effet identique. Le choix effectif est déterministe : **plus récente date d'effet applicable, puis plus récent numéro de révision à cette date**, en écartant explicitement les révisions futures remplacées par la nouvelle commande pour les jours/sections touchés.

L'implémentation de TP-023A doit rendre explicites les périodes de validité effectives et la supersession des révisions, pour éviter qu'une ancienne configuration ne réapparaisse après expiration/désactivation. Elle doit modifier conjointement :
- la contrainte SQL unique `(rule_id, effective_from)` et les migrations SQLite/PostgreSQL;
- la validation de domaine qui exige l'ordre strict des dates;
- `expand_rules` / la projection temporelle et les chemins de lecture;
- les contrôles de concurrence et l'unicité `(rule_id, number)`, à conserver.

Modifier seulement la contrainte SQL **ne satisfait pas** ce contrat. Conserver le passé, l'historique d'audit et les anciennes identités de réservations et de blocs manuels.

### E. Une seule transaction, idempotence et audit commun

La confirmation suit un seul use case applicatif et une unité de travail **non committée par des sous-commandes** :
1. authentifier/autoriser et confirmer le consentement;
2. acquérir le verrou d'écriture existant (`BEGIN IMMEDIATE` SQLite, verrou transactionnel PostgreSQL) **avant les lectures de revalidation**;
3. vérifier une éventuelle commande déjà appliquée;
4. relire versions, règles, exceptions, réservations et contraintes pertinentes;
5. recalculer la transformation et comparer l'empreinte;
6. écrire divisions, révisions, exceptions et faits d'historique;
7. effectuer **un seul commit** ou rollback complet.

L'idempotence lie `command_id`, identité utilisateur **et hash du contenu normalisé complet** : même commande répétée retourne le résultat initial; `command_id` réutilisé avec contenu différent est rejeté. Les faits typés partagent un `correlation_id` commun et identifient les scissions et arbitrages. Une sauvegarde sans changement n'ajoute pas de faux événements. Les changements significatifs de plan sont explicitement consentis (ADR-0002/0005/0021).

### F. Conflits et bornes d'évaluation

Une suppression de plage, copie ou désactivation peut créer une incompatibilité avec une réservation locale `CONFIRMED`. L'enregistrement de l'indisponibilité déclarée peut être permis **avec reconnaissance explicite** des conflits, mais la réservation demeure intacte, visible comme conflit ouvert; **aucune annulation/déplacement automatique**. Les résolutions `CANCEL/MOVE/KEEP` de TP-022R/TP-022E restent des commandes séparées.

La validation structurelle de l'horaire doit être distinguée de :
- l'**inventaire de toutes les exceptions et réservations locales futures effectivement affectées**, y compris hors semaine affichée;
- la **projection chiffrée bornée** et la vérification Google sur la fenêtre annoncée.

La projection existante est bornée à **93 jours**; une fenêtre d'aperçu ne peut donc pas être présentée comme une preuve de l'absence de tout conflit pour une série infinie. Les événements Google sont en lecture seule et non verrouillables. Une panne Google ne signifie jamais « temps libre confirmé ».

Une catégorie hors enveloppe ou des catégories incompatibles produisent diagnostics/refus selon ADR-0020; ni capacité inventée ni correction automatique. Préserver `PROTECTED/PREFERRED` et le compartiment `NULL`, sans double comptage.

## Portée et validation de la réalisation

**ASTRA-TP023 (gate documentaire)** : le présent ADR matérialise les trois décisions humaines et les invariants architecturaux; aucun code ni schéma métier modifié.

**TP-023A (BLOCKED, non autorisé à démarrer)** : API de lecture/aperçu/confirmation en lot, mapping et division des séries, supersession temporelle, migrations si nécessaires, atomicité/idempotence, audit et tests Python SQLite/PostgreSQL. Tests obligatoires : rollback en milieu de lot/audit, concurrence réelle entre deux transactions, réponse perdue/idempotence, seconde sauvegarde à la même date, nouvelle modification antérieure à une révision future, exceptions remappées, conflit au-delà de la semaine, DST Toronto, absence de réécriture du passé et de réservation automatique.

**TP-023B (BLOCKED)** : éditeur React par jour/section/WorkType, brouillon non destructif, ajout/retrait, jours OFF, copie ciblée, date d'effet, aperçu/confirmation, gestion `409`, accessibilité desktop/mobile et conservation du brouillon sur erreur.

**TP-023C (BLOCKED)** : recette E2E mobile/clavier et non-régression (en particulier TP-022E), rechargement, plusieurs plages, règles multi-jours, DST, conflits et absence d'écritures Google. Les tests de sûreté transactionnelle relèvent déjà de TP-023A.

## Conséquences et autorité

- Cet ADR **complète** ADR-0020/0021. Il distingue explicitement le retrait **récurrent** d'une plage catégorisée (retour à `NULL` sous enveloppe restante) et l'annulation **datée** d'une occurrence par exception (aucune restitution de `NULL`).
- Il **ne change pas encore** l'implémentation; l'ancien modèle et ses API restent l'état livré jusqu'à une tranche DEV distincte et approuvée.
- Toute réalisation doit préserver l'architecture React → FastAPI → domaine/application Python → SQLAlchemy; aucune logique métier parallèle dans React.
- **TP-080D reste `BLOCKED`, standby jusqu'à nouvel ordre humain**, sans recette, Go-Live, dépense ou écriture Google Calendar.
- **TP-023A/B/C restent `BLOCKED`** : l'acceptation de ce gate ne constitue ni une autorisation d'exécution ni une promotion automatique `READY`.
