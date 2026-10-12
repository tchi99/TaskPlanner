# ADR-0020 — Disponibilités récurrentes et projection effective (ASTRA-TP022)

**Statut : Accepted**  
**Date : 2026-10-12**  
**WorkItem : ASTRA-TP022 / TP-022 (issue #43)**  
**Décision produit : approuvée par l'utilisateur le 2026-10-12**  
**Références : ADR-0002, 0004, 0005, 0006, 0008, 0009, 0010, 0019; roadmap #1.**

## Contexte

TP-020 et ADR-0006 enregistrent des `AvailabilityBlock` explicites pour une semaine ISO, mutuellement non chevauchants, partitionnés par `WorkType`. Le compartiment `NULL` est distinct; ses minutes ne sont jamais empruntées implicitement. TP-030 utilise cette capacité pour des propositions, TP-040 applique les événements Google en lecture seule et TP-041 confirme des réservations locales après revalidation. Saisir ces blocs chaque semaine est inutilement exigeant.

L'utilisateur souhaite définir une enveloppe générale et des plages hebdomadaires récurrentes (ex. concentration mardi et jeudi 9 h–11 h 30), configurables comme **PROTECTED** ou **PREFERRED**, puis gérer des dérogations. L'architecture doit rester déterministe, préserver le passé et les blocs manuels, et éviter les doubles comptes.

## Décision

### 1. Un seul fournisseur de disponibilité effective

Ajouter des règles et exceptions **en amont** de la capacité existante, et non un deuxième moteur parallèle :

```text
Règles et révisions ─┐
Exceptions           ├─> expansion civile / partition UTC ─> intervalles déclarés disjoints
Blocs manuels        ┘                                         │
Google occupé + réservations confirmées ──────────────────────┴─> temps libre vérifié
                                                                     │
                                                  évaluations / propositions / time blocks
```

La **capacité déclarée** et le **temps libre réellement planifiable** sont deux projections nommées et différentes. Une lecture Google échouée ne devient jamais « calendrier libre »; une projection déclarée reste consultable, mais une nouvelle confirmation qui exige Google demeure interdite sans vérification.

L'autorité métier reste `app/domain` et `app/application` Python. React ne recalcule ni les durées, ni les conflits, ni les priorités de placement.

### 2. Concepts persistants et projetés

- `RecurringAvailabilityRule` (série, UUID stable, état, version de concurrence) et ses **révisions temporelles** : date d'effet civile, validité de fin exclusive, fuseau IANA, ensemble de jours, heures civiles, nature générale ou catégorisée, `WorkType` et `AvailabilityMode` éventuels. Une plage quotidienne correspond à une règle; plusieurs intervalles journaliers sont plusieurs règles.
- `AvailabilityException` : UUID stable, version, action datée ou bornée, rattachement éventuel à une occurrence via `(series_id, original_local_date)`, remplacement/annulation/ajout/retrait de disponibilité et traçabilité.
- `EffectiveAvailabilityBlock` : projection **non persistée** d'intervalles disjoints, munis d'instants UTC, du type, du mode, de la provenance et des diagnostics. Des identifiants de fragments sont déterministes, non des séries UUID générées en base.
- `AvailabilityMode.PROTECTED` / `PREFERRED` : enum distinct du `Task.ProtectionLevel`. `PREFERRED` est le mode par défaut pour une nouvelle plage catégorisée.

Aucune occurrence future infinie n'est matérialisée. Toute projection est bornée par une fenêtre explicite et applique les règles pertinentes même lorsqu'une occurrence est déplacée depuis une autre semaine vers la fenêtre.

### 3. Enveloppe, catégories et temps général

L'enveloppe générale définit les heures admissibles des nouvelles plages catégorisées. Ces plages **subdivisent** l'enveloppe; elles ne lui ajoutent aucune minute. Une plage catégorisée hors de l'enveloppe est refusée/signalée, sauf ajout exceptionnel explicite de capacité.

**Choix produit approuvé :** le temps général non catégorisé demeure dans le compartiment `NULL`. Le moteur n'alloue pas automatiquement ces minutes à un `WorkType`. Une proposition distincte peut préciser **source, destination, durée, raisons et conséquences**, puis demander une confirmation explicite. Une minute transférée est soustraite une fois au donneur et ajoutée une fois au receveur, sans changement permanent de l'horaire.

Une plage **PROTECTED** n'est pas réaffectable par un placement ordinaire; elle exige une dérogation approuvée suivie d'un nouvel aperçu. Une plage **PREFERRED** est privilégiée pour son type; une autre utilisation exige une option chiffrée et une acceptation séparée. Les tâches protégées, événements occupés externes et réservations confirmées ont des sémantiques indépendantes.

Les périodes sans catégorie ne sont ni une réserve infinie, ni une disponibilité supplémentaire; l'ensemble des intervalles consommés par les moteurs demeure **disjoint**.

### 4. Récurrence et portée des modifications

- **Cette occurrence** : exception ciblée à la date civile d'origine.
- **Cette occurrence et les suivantes** : fermeture de la révision précédente et ouverture d'une révision à date d'effet; passé préservé.
- **Toute la série** : **toutes les occurrences futures uniquement**, y compris les versions futures prévues, après aperçu des conséquences; jamais une réécriture des occurrences passées ou commencées. **Choix produit approuvé.**

Une exception suit sa clé d'occurrence d'origine, même si l'occurrence est déplacée. Toute exception future devenue orpheline/incompatible à la suite d'une modification de série nécessite une décision explicite (conserver comme ajout, remapper ou retirer), appliquée atomiquement. Aucune suppression silencieuse.

Une **annulation** d'occurrence retire sa disponibilité; elle ne reconstitue pas automatiquement du temps `NULL`. « Rendre générale » est une opération différente et explicite. Une indisponibilité déclarée retire la capacité de toutes les catégories concernées; un ajout chevauchant ne contourne pas implicitement cette indisponibilité.

### 5. Temps civil, DST, chevauchements et héritage manuel

Les règles stockent heures civiles et fuseau **IANA**; les durées et chevauchements sont calculés par instants **UTC**. Dates de semaines locales ISO et bornes exclusives. Une heure inexistante au passage DST est signalée, sans déplacement tacite; une heure ambiguë demande le choix explicite de l'instant. Les autres occurrences valides restent projetables.

Fusionner/partitionner les intervalles aux frontières d'enveloppes, catégories, exceptions, blocs hérités, occupations et semaines. Deux catégories incompatibles superposées produisent un conflit, jamais un choix arbitraire par UUID/date d'insertion; la partie litigieuse est non planifiable tant que non résolue. Deux règles équivalentes peuvent être unifiées en préservant les provenances.

Conserver identités, instants et sémantique des `AvailabilityBlock` historiques : ils restent des déclarations explicites strictes au même type, **non** rétroactivement `PREFERRED`. Ils ne doublent jamais la capacité de l'enveloppe et les recouvrements incompatibles sont signalés. Les anciennes API manuelles gardent leurs contrats et leurs libellés; les projections enrichies doivent être explicitement identifiables.

### 6. Intégration et audit

Utiliser le fournisseur de projection commune pour la capacité, propositions, calendrier, time blocks, revue du matin et revue hebdomadaire. Conserver une évaluation déterministe sans emprunt automatique, les estimations inconnues non transformées en zéro, et la charge sur les unités ouvertes (ADR-0004). Une réservation planifiée n'est **pas** une preuve de travail accompli.

Le calcul du temps libre vérifié applique un découpage conservateur à la minute **commun** à TP-040/041; distinguer les statistiques historiques « occupation arrondie » des minutes planifiables afin de ne pas afficher deux chiffres contradictoires sous le même nom.

Étendre l'historique append-only d'ADR-0005 avec faits typés de règles, révisions, exceptions et décisions (p. ex. `AVAILABILITY_RULE_CHANGED`, `AVAILABILITY_EXCEPTION_APPLIED`) et `task_id` nul lorsqu'aucune tâche n'est concernée. Ces événements ne doivent pas simuler une interaction sur les tâches.

Les migrations Alembic sont additives et non destructives, compatibles SQLite local/PostgreSQL privé Supabase (ADR-0019); aucune conversion automatique de semaines manuelles, aucune exposition d'une table métier par le navigateur.

## Conséquences

- TP-022A établit séries/révisions, identité, persistance, résolution temporelle et API; TP-022B ajoute exceptions, projections et conflits. Les moteurs consommateurs sont modifiés seulement après ces contrats.
- L'évolution est explicitement additive à ADR-0006 (compartiments et exclusion du double comptage) et ADR-0009 (lecture seule), sans les remplacer globalement.
- Tests requis : mardi/jeudi = 300 minutes déclarées, annulation isolée, modification future sans réécrire le passé, exception intersemaine, collision, bloc manuel superposé, DST Toronto, et cohérence SQLite/PostgreSQL.
- Toute annulation/déplacement de réservation existante suit l'ADR-0021; aucun changement de disponibilité ne déclenche seul une écriture Google ou la mutation d'une tâche.
