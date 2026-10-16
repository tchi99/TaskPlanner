# ADR-0023 — Catégories parentes, enveloppes contextualisées et migration temporelle (ASTRA-TP024)

**Statut : Accepted — cinq décisions produit approuvées par l'utilisateur le 2026-10-15**  
**Date : 2026-10-15**  
**WorkItem : ASTRA-TP024 / TP-024 (issue #57)**  
**Roadmap maître : issue #1**  
**Références : ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0009, ADR-0010, ADR-0020, ADR-0021, ADR-0022; issues #43, #52, #57, #58; TP-023D livré en PR #59.**  
**Autorité : décision documentaire seulement. Le gate peut être clôturé après validation documentaire; TP-024A/B/C demeurent BLOCKED sans autorisation de développement. TP-080D reste BLOCKED en standby jusqu'à nouvel ordre explicite.**

## Contexte et vérifications sur le main actuel

TaskPlanner doit proposer les catégories parentes **Travail** et **Personnel**, chacune dotée d'une enveloppe horaire indépendante et de sous-catégories planifiables (p. ex. Focus work, Gestion et planification, Famille), sans double comptage des minutes physiques.

L'analyse ASTRA-TP024 initiale (lecture seule, verdict `DECISION_REQUIRED`) a porté sur `main@d231cb1120195e5c719d034a1bc90c6ebaafd074`; elle constate un modèle `WorkType` plat, une enveloppe `GENERAL` globale, un compartiment `NULL` unique, des transferts `PREFERRED` non contextualisés par parent et une grille indexée seulement par jour/nature/type/fuseau. Elle préconise un `ScheduleScope` parent distinct des WorkTypes feuilles et un moteur de projection unique.

La réconciliation documentaire a examiné **`main@1c76c788f1f40548e92a26239d7c4f68c51176a0`**, après livraison de **TP-023D / PR #59** :
- `app/application/weekly_schedule.py`, algorithme **`TP-023D/v2`** : le calcul `_invalid_details` classe désormais **les minutes structurellement incompatibles** par code et identité(s) de WorkType, au lieu de traiter un simple changement de bornes comme un nouveau conflit. Le résultat expose `NEW`/`PREEXISTING`, dates/heures locales, fuseau de lecture, identifiants de règles, fuseaux et dates d'origine, causes et remédiations; `invalid_conflicts` ne retient que les nouvelles incompatibilités bloquantes.
- La lecture `read_weekly()` reste filtrée au fuseau sélectionné; la validation `_plan()` projette toutes les règles. Les diagnostics TP-023D rendent les sources d'un autre fuseau visibles, mais n'établissent **aucun** parent d'horaire et ne transforment pas les données anciennes.
- `frontend/src/WeeklyScheduleEditor.tsx` restitue ces diagnostics et les raccourcis vers les sections; `frontend/src/AvailabilityPlanner.tsx` n'expose plus l'ancien formulaire de modification règle par règle, mais conserve un inventaire des séries historiques **en lecture seule**.
- `app/domain/effective_availability.py::project_effective()` vérifie toujours toutes les plages `CATEGORIZED` contre une enveloppe `GENERAL` **unique** et produit des blocs sans `scope_id`. TP-023D ne règle donc pas la séparation Travail/Personnel.

**Conclusion de réconciliation :** l'option `ScheduleScope` et les cinq décisions ASTRA demeurent valides, mais la future sémantique doit **étendre la classification par minutes de TP-023D** à la provenance et à la capacité par parent. Il ne faut ni réintroduire l'ancien test exact `(code, début, fin)`, ni supposer qu'un conflit `PREEXISTING` est nouveau, ni créer deux moteurs concurrents.

## Décisions de produit approuvées

### D1 — Hiérarchie fixe à deux niveaux

- Introduire une entité **`ScheduleScope`** persistée, identifiée par UUID stable, propriétaire, nom, état et **version**; Travail et Personnel en sont les premiers cas d'usage, sans valeur sémantique calculée à partir du libellé.
- Conserver **`WorkType` comme feuille planifiable** : son UUID reste la référence des tâches et segments (ADR-0004), des règles et des réservations. Un parent ne devient pas une nouvelle unité de travail. Pas de WorkType enfant d'un autre WorkType, ni d'arbre récursif en V1.
- À une date civile donnée, un WorkType appartient à **un seul scope**, via un **rattachement temporel versionné**; l'ancienne appartenance ne doit pas être réécrite en déplaçant un pointeur mutable. Les renommages ne changent pas les UUID.
- Un WorkType existant appelé « Travail » ou « Personnelle » reste une **feuille** tant qu'il n'est pas explicitement rattaché; aucun renommage/convertissage automatique en parent homonyme.

### D2 — Parents mutuellement exclusifs pour la capacité planifiable V1

- Les enveloppes de deux scopes distincts ne peuvent pas créer **simultanément** deux disponibilités planifiables sur la **même minute physique**. La projection découpe les intervalles en UTC et **signale/refuse tout nouveau chevauchement structurel interparent**; elle n'arbitre jamais Travail contre Personnel selon l'ordre de création, la priorité de libellé ou l'identifiant.
- Les chevauchements hérités restent visibles, avec sources/fuseaux/jours datés; leur intersection est **non planifiable jusqu'à résolution explicite**. Les anciennes déclarations ne sont pas supprimées automatiquement.
- Une même minute peut appartenir à l'enveloppe et à une sous-catégorie du **même parent** (subdivision normale, pas addition). Deux feuilles incompatibles du même parent sont toujours un conflit.
- La capacité **partagée alternativement** (« Travail **ou** Personnel » sur les mêmes minutes) et toute priorité automatique ou transfert entre parents sont **hors V1**; ils exigeraient un autre contrat produit et une décision humaine.

### D3 — Temps général et unités de travail par parent

- Le compartiment métier effectif est **`(scope_id, work_type_id)`**, avec `work_type_id = NULL` désignant **le temps général résiduel de ce parent**, jamais une réserve globale entre parents.
- Les intervalles `CATEGORIZED` sont couverts par leur **propre enveloppe `GENERAL`**, jamais par celle d'un autre parent; ils divisent la capacité de leur scope et ne l'augmentent pas.
- **Aucune allocation implicite** du `NULL` d'un parent à une feuille, à une tâche sans type ou à un autre parent. Les tâches/segments sélectionnent des **WorkTypes feuilles**; le type effectif continue d'obéir à ADR-0004. Une tâche sans WorkType reste non classée; une feuille explicitement appelée « Général » est une feuille ordinaire et ne capture pas le résiduel `NULL` par son nom.
- La somme d'un parent est une **agrégation** de compartiments disjoints, non une deuxième couche de capacité. La somme de tous les parents porte sur des minutes physiques uniques.
- Les transferts `PREFERRED` ordinaires, avec consentement déjà requis, restent **intra-parent**; `PROTECTED` exige toujours sa dérogation approuvée. Le transfert interparent n'est **pas** offert en V1.

### D4 — Migration additive et affectation confirmée, sans inférence

- **Phase technique additive** (migrations SQLite/PostgreSQL versionnées) : nouvelles tables/colonnes pour scopes, rattachements datés, portées de règles et exceptions, versions et provenance de confirmations; **aucune suppression d'identité/donnée historique** et aucune création de deux enveloppes à partir d'une ancienne enveloppe globale.
- Les données antérieures restent temporairement dans un **scope de compatibilité explicite** représentant fidèlement le comportement actuel : une enveloppe `GENERAL`, un compartiment `NULL`, les WorkTypes plats, blocs manuels, règles/révisions et exceptions historiques. Ce scope n'est pas une nouvelle disponibilité à additionner aux scopes Travail/Personnel.
- **Phase métier distincte** : inventaire lisible des WorkTypes, tâches/segments, blocs manuels, règles et révisions futures, exceptions, occupations et réservations; choix explicites d'affectation aux nouveaux parents, avec date d'effet, fuseau IANA, aperçu des conflits et de la capacité, puis confirmation atomique.
- Une affectation non déduisible reste dans le scope de compatibilité, **jamais** auto-classée par le nom « Travail », « Personnel » ou « Personnelle ». Le nettoyage manuel d'un environnement local ne prouve pas que toutes les instances de TaskPlanner sont vierges de séries historiques : la migration de produit doit rester sûre pour les autres bases.
- Une requête legacy sans identifiant de parent reste limitée au **scope de compatibilité**; elle n'est **jamais** interprétée « tous les parents ». Si l'intention d'un changement est ambiguë, demander explicitement le nouveau contrat plutôt que changer silencieusement la signification d'une API.
- Aucun nettoyage physique des archives, migration réelle de Supabase, écriture Google ou Go-Live n'est autorisé par cet ADR.

### D5 — Reclassement daté, aperçu/confirmation atomique et engagements préservés

- Déplacer une feuille vers un autre `ScheduleScope` est une **révision de rattachement à date d'effet**, pas une mutation rétroactive du passé. Conserver UUID, historique des anciennes appartenances et rattachements non affectés.
- La **confirmation d'un changement d'horaire ou d'appartenance ne déplace, n'annule et ne requalifie jamais silencieusement** un `ConfirmedTimeBlock`. Les réservations nouvelles devront enregistrer la provenance `scope_id` et le compartiment utilisé; pour les anciennes réservations, l'absence de provenance reste **inconnue**, pas un scope inventé.
- Si une modification crée des incohérences avec les engagements conservés, retourner un inventaire et des conflits explicites; conserver les décisions de résolution `KEEP/CANCEL/MOVE` dans les commandes distinctes prévues par ADR-0021. La reconnaissance d'un conflit de réservation ne valide pas une incohérence structurelle interparent.
- Tout reclassement qui peut toucher des réservations, des exceptions ou la capacité doit être **prévisualisé puis confirmé**, avec verrou et audit, sans modification partielle.

## Projection unique, exceptions et consommation

Maintenir **un seul chemin d'autorité** :

```text
Règles/révisions + scope + rattachement daté + exceptions + blocs manuels
   → expansion civile IANA/DST
   → partition en instants UTC (jamais deux copies de la même minute)
   → contrôle GENERAL/CATEGORIZED par scope et des chevauchements interparent
   → fragments disjoints (scope_id, work_type_id ou NULL, mode, provenances)
   → retrait global des occupations Google et bookings locaux confirmés
   → capacité déclarée / temps libre vérifié / propositions / time blocks / revues
```

Invariants obligatoires :
- Une minute planifiable appartient au plus à **un** compartiment et à **un** scope; aucun parent ne se rajoute aux enfants comme capacité supplémentaire.
- Le `NULL` d'un parent n'alimente pas les autres; retirer une **plage récurrente catégorisée** rend sa période au `NULL` du **même parent** si son enveloppe demeure (ADR-0022).
- Une exception `CANCEL` d'**occurrence** ne rend **pas** ce temps au `NULL` (ADR-0020/0022); `CANCEL/REPLACE` héritent de la portée de l'occurrence ciblée et les remappages sont explicites.
- `UNAVAILABLE` reçoit une portée **globale** ou **un parent spécifique**. Les indisponibilités historiques globales conservent leur effet; une indisponibilité globale retire les minutes physiques de tous les parents concernés.
- Google occupé et les bookings actifs bloquent les **instants physiques**, indépendamment de l'affichage en parents; panne Google ne vaut pas calendrier libre (ADR-0009/0020).
- La classification structurée TP-023D `NEW/PREEXISTING` continue par **ensemble réel de minutes incompatibles**, étendue aux identités de parent et de feuille pertinentes; les diagnostics indiquent parent(s), règles/révisions, intervalle/date locale et fuseaux sources, sans requalifier un conflit réduit comme « nouveau ».

Étendre les **consommateurs existants** et leur sérialisation : `effective_week()`, évaluations/capacité, propositions et donneurs `PREFERRED`, temps libre vérifié, time blocks, résolutions de réservations et revues. Un total global de minutes préférentielles **sans parent** ne suffit plus pour justifier un transfert; React consomme les projections Python au lieu de sommer lui-même.

## Contrat de migration, édition et reclassement

Réutiliser le protocole `draft → preview → confirm` d'ADR-0022 avec une **commande applicative dédiée** pour migration/reclassement, plutôt qu'une suite de PATCH indépendants.

Le brouillon cible explicitement : identités/versions de scopes, appartenances temporelles des WorkTypes et versions attendues, `scope_id` des sections/jours, date d'effet future et fuseau IANA, règles/révisions/sections à réviser, exceptions et décisions de remappage. **Absent** signifie inchangé; une section explicitement vide signifie suppression future ciblée, sans effacer l'histoire.

L'aperçu :
- montre les capacités **avant/après par parent et globalement**, sans double comptage;
- expose toutes les **nouvelles** incompatibilités structurelles, les anciennes et celles atténuées, datées et localisées par parent, les sources/fuseaux et les corrections proposées;
- conserve un inventaire de toutes les réservations persistées **futures**, y compris au-delà de l'horizon chiffré, ainsi que les exceptions à arbitrer; ne prétend pas vérifier l'ensemble d'une récurrence infinie;
- annonce clairement que la **projection numérique est bornée à 93 jours civils** et que Google reste une lecture externe non verrouillable.

La confirmation :
1. requiert l'autorisation/propriété et le consentement explicite;
2. acquiert le **verrou commun avant relecture** (`BEGIN IMMEDIATE` SQLite ou verrou transactionnel PostgreSQL);
3. relit les versions de scopes, affiliations, règles, exceptions, réservations et toute autre source pertinente;
4. recalculera l'empreinte incluant **scope, rattachements/version du référentiel, projet de migration et décisions** — changer la parenté entre aperçu et confirmation entraîne `409 Conflict` **sans écriture partielle**;
5. applique révisions, remappages/exception decisions, audit append-only corrélé et reçu idempotent `command_id` dans **une seule transaction** (sinon rollback complet).

La date d'effet de l'horaire habituel respecte ADR-0022 : **au plus tôt le lendemain civil IANA**, et les exceptions de « Semaine réelle » règlent aujourd'hui. Ne pas refaire le passé ni convertir silencieusement les instants DST ambigus/inexistants.

## Alternatives rejetées et conséquences

- **Simple `WorkType.parent_id`** : n'identifie pas correctement les enveloppes générales, `NULL` et sources historiques, ni la portée des exceptions/réservations.
- **Arbre WorkType arbitraire** : niveaux, cycles et héritage inutilement complexes pour le besoin V1, risque de types parents déjà référencés par des tâches.
- **Deux projections calculées puis additionnées** : violeraient ADR-0006/0020 et doubleraient la capacité de certains instants physiques.
- **Reclassement immédiat mutable / inférence par libellé** : réécrirait implicitement l'interprétation du passé et pourrait déplacer les engagements.
- **Priorité Travail sur Personnel ou partage interparent implicite** : choix produit non autorisé.

Conséquences : nouveaux IDs parent, versions/affiliations temporelles, colonnes/contrats/additions compatibles et changement transversal des consommateurs de capacité. Plus de diagnostics et un parcours de migration utilisateur, mais maintien de l'autorité métier unique et des engagements historiques. Le présent ADR **complète** ADR-0004/0006/0020/0021/0022, sans les annuler.

## Découpage et validation avant toute réalisation

- **ASTRA-TP024 (gate documentaire)** : après validation de cet ADR et du `main` post-TP-023D, le gate peut être déclaré `DONE`; aucune implémentation de modèle/API/UI.
- **TP-024A (BLOCKED)** : modèle `ScheduleScope`, rattachement temporel, migrations SQLite/PostgreSQL, compatibilité, APIs, projection unique, changements de consommateurs, verrou/idempotence, tests unitaires/intégration. Tests bloquants : séparation des deux `NULL`, conflit interparent, absence de transfert interparent, portée `UNAVAILABLE`, `CANCEL` non reconstituant, préservation des UUID/passé/bookings, `409` après changement d'affiliation et concurrence réelle SQLite/PostgreSQL.
- **TP-024B (BLOCKED)** : UI Travail/Personnel → feuilles, grille par parent, aperçu de migration/reclassement, diagnostics TP-023D enrichis et affichage sans confusion des anciennes séries/du scope de compatibilité; mobile/clavier et état de brouillon conservés.
- **TP-024C (BLOCKED)** : recette de migration réaliste, anciennes APIs, DST America/Toronto, mois/semaine, historique, conflits, occupations, réservations, absence de double comptage, validations CI/backend/frontend/E2E.

**Limites et gouvernance :** aucun test exécuté par la seule analyse documentaire; la CI de la PR documentaire sert de validation de dépôt. Aucune migration utilisateur réelle ni changement de code métier, schéma, API ou UI. La finalisation d'ASTRA **ne donne pas** le droit de promouvoir TP-024A/B/C à `READY` sans ordre humain distinct. **TP-080D demeure `BLOCKED`, standby jusqu'à nouvel ordre explicite**, sans recette Render/Supabase, déploiement ni écriture Google Calendar.
