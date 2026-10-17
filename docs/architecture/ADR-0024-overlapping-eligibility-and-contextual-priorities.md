# ADR-0024 — Admissibilités superposables, priorité contextuelle et grille hebdomadaire (ASTRA-TP025)

**Statut : Accepted — cinq décisions ASTRA-TP025 approuvées explicitement par l'utilisateur le 2026-10-16**  
**Date : 2026-10-16**  
**Parent : [TP-025 / issue #64](https://github.com/tchi99/TaskPlanner/issues/64)**  
**Roadmap maître : [issue #1](https://github.com/tchi99/TaskPlanner/issues/1)**  
**Base de l'analyse : `main@24020c6a98b62b00a341e7f7406b0e5d2e6cb1a2`** (TP-024C fusionnée).  
**ADR applicables :** ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0009, ADR-0010, ADR-0020, ADR-0021, ADR-0022 et ADR-0023.

**Autorité :** décision **documentaire** de stabilisation de la gate `ASTRA-TP025`, initialement `DECISION_REQUIRED`. L'acceptation de cet ADR **n'autorise aucun développement**. `TP-025A/B/C/D` demeurent `BLOCKED` et `TP-080D` `BLOCKED` en standby jusqu'à autorisation humaine distincte. Pas de migration, publication, écriture Google Calendar ou création de réservation lors de cette formalisation.

## 1. Contexte et constats vérifiés

Un utilisateur veut :
- **Focus work admissible** les mardi, mercredi et jeudi, **09:00–12:00 et 13:00–15:00**;
- **Réunions admissibles** du lundi au vendredi, **10:00–12:00 et 13:00–16:00**;
- **Focus work prioritaire mardi et jeudi matin**, tout en autorisant **automatiquement une réunion sur toute minute réellement libre**, sans réaffectation manuelle d'une plage `PREFERRED`;
- une **grille hebdomadaire visuelle** avec deux barres pour deux admissibilités simultanées, priorité reconnaissable, occupation séparée, détails et accessibilité.

Ce besoin n'est ni une double disponibilité, ni une réservation anticipée de Focus, ni une nouvelle sémantique des modes historiques `PROTECTED/PREFERRED`.

Constats ASTRA sur le vrai `main@24020c6a` (rapport `DECISION_REQUIRED`) :
1. `app/domain/effective_availability.py::project_effective()` produit un `EffectiveBlock` à **un seul WorkType** : des WorkTypes différents simultanés déclenchent `INCOMPATIBLE_WORK_TYPES`.
2. `app/application/planning_availability.py::effective_week()` matérialise des `AvailabilityBlock` exclusifs; additionner des compartiments par WorkType peut fausser capacité et faisabilité si ces blocs sont dupliqués.
3. `app/domain/time_blocks.py::suggest_time_blocks()` est un placement glouton en **ordre de candidats**, suivi d'un passage de transferts `PREFERRED`; il ne connaît pas une priorité qui change selon l'heure.
4. `app/application/time_blocks.py` et les flux de conflit/`MOVE` vérifient encore la couverture par type exclusif ou donneur `PREFERRED`. La confirmation de nouveaux time blocks ne dispose pas du reçu `command_id` et de l'audit de commande de certains éditeurs; leur idempotence n'est donc pas acquise.
5. Une projection « après » des réservations futures dans `app/application/weekly_schedule.py::_plan()` omet `compatibility_id` et `affiliations` à un appel, contrairement au chemin « avant »; l'évolution doit harmoniser et tester ce chemin.
6. La grille `frontend/src/WeeklyScheduleEditor.tsx` configure les déclarations `GENERAL/CATEGORIZED`, avec un choix exclusif `PROTECTED/PREFERRED`; une nouvelle édition distincte est nécessaire pour éviter de modifier les données historiques.

Les mécanismes existants de verrous SQLite/PostgreSQL, révisions datées, audit et `draft → preview → confirm` constituent la base à **étendre**, non des garanties automatiquement transposables à tous les endpoints.

## 2. Principe fondateur : chronologie physique unique, choix multiples

Conserver un **unique moteur Python d'autorité** qui projette une chronologie d'**instants physiques UTC disjoints**. Chaque fragment physique comporte :
- le `scope_id` **unique** et l'enveloppe `GENERAL` qui le couvre;
- sa capacité physique (une minute ne vaut qu'une minute), restrictions et provenance;
- **zéro, une ou plusieurs admissibilités** `work_type_id`, rang contextuel et sources/révisions;
- les occupations externes/locales et les réservations déjà confirmées, **distinctes** des permissions;
- les allocations **proposées**, avec raison et consommation unique, avant confirmation.

**Invariants absolus :**
- La superposition de permissions n'ajoute **aucune** minute à l'enveloppe. Sur 10:00–12:00, `Focus 120 min potentiels + Réunions 120 min potentiels` = **120 minutes physiques au total**, non 240.
- Une minute peut rester admissible à deux WorkTypes, mais **n'être allouée qu'une fois** dans un aperçu ou une réservation confirmée.
- Aucun chevauchement d'enveloppes **entre parents** : la frontière d'ADR-0023 reste en vigueur.
- Une minute d'un parent ne peut servir à un autre, `NULL` résiduel n'est pas une réserve commune; les WorkTypes continuent d'être des feuilles rattachées temporellement à un parent.
- Il est **interdit de créer deux `AvailabilityBlock` physiques** de WorkTypes différents sur le même intervalle et de les additionner ou de les soumettre aveuglément au moteur exclusif.
- Les `PROTECTED` historiques, indisponibilités, blocs manuels stricts, exceptions et réservations ne peuvent être contournés par une nouvelle « permission ».
- Une panne ou une absence de vérification Google ne prouve jamais qu'un créneau est libre; aucune écriture automatique sur Google.

## 3. Cinq décisions humaines approuvées

### D1 — Neutralité mercredi/après-midi et ordre d'arbitrage déterministe

**Décision :** les mercredi matin et après-midis, **aucune priorité de catégorie implicite** n'est définie. La seule préférence de WorkType préconfigurée dans le scénario de référence est **Focus > Réunions mardi et jeudi matin sur la partie réellement commune 10:00–12:00**. Le mardi/jeudi 09:00–10:00, Réunions n'est pas admissible.

Lorsqu'un intervalle physique est libre et que plusieurs candidats présents dans **le même aperçu** sont admissibles, l'algorithme examine **dans cet ordre** :

1. **Contraintes obligatoires** : occupation/indisponibilité, enveloppe, admissibilité, interdictions strictes, durée demandée, échéance comme borne temporelle, protection ou engagement déjà confirmé.
2. **Protection effective de l'unité de travail** : protégée, replanifiable, flexible (réutiliser les règles de protection existantes, sans inventer une nouvelle protection des WorkTypes).
3. **Priorité contextuelle de l'activité sur cet intervalle** (rang porté par la fenêtre).
4. **Échéance la plus proche** pour les candidats encore éligibles à cet intervalle.
5. **Ordre explicite utilisateur**, puis ordre stable des segments/identifiants uniquement comme dernier déterminisme.

**Conséquence explicitement acceptée :** une réunion protégée peut passer avant un Focus flexible malgré la préférence Focus; à protection identique, Focus passe devant une réunion **sur le créneau mar/jeu matin**. Une réunion déjà confirmée n'est pas un candidat mobile; elle reste occupante.

La priorité est **locale à un fragment horaire**, jamais un tri global « toutes les tâches Focus avant toutes les réunions ». Une proposition montre le motif, les éventuels replis et les unités non placées. Un échec heuristique se dit **« aucun placement trouvé par cette stratégie »**, pas **« aucune solution mathématiquement possible »**.

Sans Focus parmi les candidats de l'aperçu, Réunions peut utiliser mardi/jeudi 10:00–12:00 directement si les minutes sont libres, **sans transfert manuel `PREFERRED`**. Le repli n'accorde **aucune confirmation automatique** de réservation : l'acceptation effective du plan demeure explicite.

### D2 — Exceptions propres à l'admissibilité, sans altération des anciennes exceptions

**Décision :** une occurrence d'admissibilité peut être retirée ou déplacée **pour son WorkType seulement**; les autres permissions sur les mêmes minutes demeurent intactes :
- Retirer l'admissibilité **Focus** mardi 10:00–12:00 ne retire **pas** Réunions.
- Déplacer une admissibilité déplace **la permission**, pas l'enveloppe physique et sans créer de capacité.
- Si la **dernière admissibilité nouvelle** disparaît, les minutes encore couvertes par l'enveloppe du **même parent** redeviennent **`NULL` résiduel** seulement en l'absence d'une ancienne affectation exclusive ou autre restriction applicable; aucune affectation automatique à une feuille.
- Déclarer une **indisponibilité physique** retire la capacité de son parent ou globalement selon la portée, y compris pour toutes les admissions concernées.
- Le `CANCEL/REPLACE` **historique** conserve sa signification (notamment `CANCEL` n'ajoute jamais implicitement `NULL`), sans conversion automatique vers une exception d'admissibilité.
- Une réservation devenue incompatible reste `CONFIRMED`, visible avec un conflit ouvert, jusqu'à résolution explicite ADR-0021.

L'API, l'audit, les noms de commande, révisions et provenance doivent empêcher de confondre **désactivation d'une permission** et **annulation de capacité**.

### D3 — Réunions locales à heure fixe dans TP-025B

**Décision :** TP-025B comprend un contrat **étroit** pour placer une unité/tâche existante avec **début et fin imposés**, à durée **indivisible**, par **aperçu et confirmation locale**. Cela ne crée pas de rendez-vous Google automatiquement, ne répond pas à une invitation et ne déplace pas une réservation existante.

Les tâches ordinaires conservent la **fragmentation à la minute** du moteur actuel en V1; aucun minimum universel ou algorithme d'optimisation globale n'est introduit par défaut. Les heures fixes doivent passer les mêmes contrôles d'admissibilité/occupation/versions/protection, avec conflits explicites et revalidation sous verrou.

Le `command_id` et le reçu idempotent de **création de réservation** restent à implémenter/étendre dans TP-025B; ne pas supposer que le contrat d'édition hebdomadaire les fournit déjà.

### D4 — Transition opt-in, datée et atomique des plages historiques

**Décision :** les anciennes plages exclusives `GENERAL/CATEGORIZED` et modes `PROTECTED/PREFERRED` ne deviennent **jamais** automatiquement des fenêtres admissibles superposables.

Concevoir un modèle **dédié** de séries d'admissibilité, révisions datées et exceptions dédiées : UUID stable, propriétaire, version, `scope_id`, `work_type_id`, date d'effet/validité, jours, heures civiles, fuseau IANA, choix DST ambigus, **rang contextuel facultatif porté par la fenêtre**, provenance et supersession. **Un modèle générique de politique séparé n'est pas nécessaire en V1.**

Transformer une plage exclusive existante en permission partagée exige une **opération volontaire** : retrait ciblé de l'ancienne déclaration sur les occurrences futures visées, création des nouvelles fenêtres/rangs, traitement explicite des exceptions et des réservations impactées, **aperçu puis confirmation dans une seule transaction**. Rien n'est modifié rétroactivement ni purgé. Ne jamais convertir en silence les anciennes protections, le `NULL`, des événements Google ou les identités `WorkType`.

Deux déclarations équivalentes peuvent fusionner dans la **projection** en conservant toutes les sources. Des rangs contradictoires pour **une même activité aux mêmes minutes** constituent un **diagnostic**, jamais une résolution arbitraire par UUID, ordre d'insertion ou fuseau.

### D5 — Édition depuis les barres, sans glisser-redimensionner V1

**Décision :** la grille hebdomadaire visuelle doit être **fonctionnelle et accessible** et permettre d'ouvrir un **formulaire contextualisé** lorsqu'une barre est activée (clic, clavier ou toucher). L'édition suit `brouillon → aperçu → confirmation` et conserve le brouillon en cas de `409`. **Pas de glisser-redimensionner** en V1.

Afficher :
- semaine/parent/fuseau et axes locaux heure/jour; barres en **sous-couloirs** pour les admissions simultanées sans masquer une autre catégorie;
- **couleur par WorkType** et **contour/motif/texte** pour la priorité (une « catégorie Focus prioritaire » supplémentaire n'existe pas);
- légende et aide indiquant que les barres sont des **choix, non de la capacité doublée**;
- **trois vues/layers** : *Configuration* (permissions/priorités et restrictions), *Occupation réelle* (bookings locaux, occupation Google **seulement vérifiée**, libre/indisponible/conflits), *Plan proposé* (placements, replis, alternatives et motifs);
- détails : WorkType/parent, source/révision, date d'effet, période, priorité, restrictions, autres admissibilités et diagnostics;
- filtres visuels sans changement de l'autorité du moteur; alternative **tabulaire**, contrastes, lecteurs d'écran, clavier, rendu mobile et trois superpositions ou plus;
- instants UTC, fuseau/décalage et transitions DST (premier/second instant ou heure inexistante) sans fausse durée.

**API de lecture dédiée** ou projection commune enrichie, sans deuxième source métier : exposer séparément fragments physiques, permissions, occupations, diagnostics et compteurs vérifiés; calcul et classement restent dans Python. React calcule **seulement la mise en page** (couleurs, pixels, `layer`), pas la capacité ni la priorité.

## 4. Contrat transversal d'implémentation

### 4.1 Projections, capacité et décisions

Une seule autorité Python de projection :

```text
GENERAL par parent + règles historiques + blocs manuels + exceptions physiques
   → découpage des minutes physiques UTC, sans chevauchement interparent
   + séries/révisions/exception d'admissibilité (choix multiples intra-parent)
   → fragments physiques uniques + choix/priorités/restrictions/provenances
   → retrait global des bookings locaux CONFIRMED et événements Google occupés
   → allocateur déterministe sur demandes conjointes et priorités par intervalle
   → capacité physique / potentiels non additifs / placements / explications
   → aperçu / revalidation sous verrou / confirmation locale explicite
```

- `EffectiveAvailability` ne peut plus être consommée aveuglément comme une liste de compartiments mutuellement exclusifs **par activité** lorsque des admissions sont superposées.
- `effective_week()`, `evaluate_week()`, propositions, time blocks, revues du matin/hebdomadaires, résolutions de conflit/`MOVE` et vérification du placement doivent recevoir une **projection commune versionnée**.
- L'évaluation **conjointe des candidats** doit tester les compétitions entre sous-ensembles de WorkTypes. Ex. demande Focus 120 min + Réunions 60 min sur une seule plage commune 120 min : ces 180 min ne sont pas faisables **sur cette seule plage**, même si chaque potentiel est de 120 min.
- Totaux globaux = **union des fragments physiques**, potentiels par type = **alternatives non-additives** clairement libellées, résultat d'allocation = placement trouvé / non trouvé selon stratégie / estimation inconnue. Le code `OVER_CAPACITY` reste réservé à une insuffisance **démontrée**, pas un seul échec de glouton.
- Une confirmation consomme physiquement les minutes pour **toutes** les permissions du fragment. Les réservations conservent leur vraie provenance (`scope_id`, admissibilité/révision retenue ou transfert historique), avec **aucune utilisation de `transferred_from` pour coder un repli partagé**.

### 4.2 Transactions, révisions et sécurité

- Maintenir une migration **additive SQLite + PostgreSQL**, autorisation par propriétaire et historique `append-only`, sans conversion/purge automatique.
- Pour édition, transition et création/déplacement de réservation : versions pertinentes et `fingerprint` de contenu incluant plages, rangs, exceptions, affiliations temporelles, ordre des candidats, demandes fixes, état Google vérifié et **version d'algorithme**; `command_id` idempotent lié au contenu et à l'utilisateur, audit atomique.
- À la confirmation, **verrou commun avant relecture** de l'état local, recalcul et comparaison d'empreinte, vérification des nouvelles allocations **entre elles** et contre les occupations, rollback total sur conflit/stale (`409`), pas de double réservation possible lors de courses SQLite/PostgreSQL.
- Google reste **en lecture seule** et non verrouillable; le résultat de sa lecture n'atteste pas qu'il ne changera pas ultérieurement. Un échec de lecture ne peut pas être remplacé par une absence présumée d'occupation.
- Les affiliations datées et les conflits futurs doivent être examinés sur une fenêtre annoncée. **93 jours** est la borne actuelle de projection numérique, pas une garantie pour une récurrence infinie; inventorier les réservations futures persistées au-delà de l'horizon.
- Réconcilier le chemin « après » de `weekly_schedule._plan()` avec `compatibility_id` et `affiliations` et ajouter un test de réservation future parentée; compléter la confirmation idempotente et l'audit des nouveaux time blocks.

### 4.3 Compatibilité ADR et limites

Cette décision **complète et modifie de façon ciblée** :
- **ADR-0023 D2/D3** : « une minute planifiable, un compartiment » reste vrai de **la capacité physique/consommation**, mais les **nouvelles admissions non exclusives** d'un même parent autorisent plusieurs WorkTypes sur ce fragment. Les enveloppes de parents distincts restent mutuellement exclusives. Les anciennes feuilles `CATEGORIZED` exclusives restent incompatibles entre elles tant qu'aucune conversion explicitement confirmée n'a eu lieu.
- **ADR-0020** : `PROTECTED/PREFERRED` et les `CANCEL/REPLACE` historiques sont inchangés; la nouvelle permission de repli **n'est pas** un transfert préférentiel ni une dérogation.
- **ADR-0021/0022** : aucune mutation silencieuse d'une réservation, `draft → preview → confirm`, versions, transaction et audit; l'idempotence doit être étendue aux confirmations de nouveaux blocs et aux éditions d'éligibilité.
- **ADR-0004/0006/0010** : protection de l'unité de travail, charge/estimations et ordre explicite demeurent des données pertinentes; l'ordre utilisateur devient un **départage après** contraintes, protection, priorité contextuelle et échéance dans le **nouvel allocateur de mode partagé**, pas une requalification rétroactive des anciens plans.
- **ADR-0009** : aucune création/modification d'événement Google.

**Exclusions V1 :** partage alternatif Travail/Personnel, choix implicite de priorité mercredi/après-midi, mutation de réservations confirmées, garantie d'optimisation exhaustive, définition automatique d'une durée minimum Focus, réponses Google aux invitations, glisser-redimensionner, déploiement/sauvegarde/Go-Live TP-080D.

## 5. Alternatives rejetées

1. **Supprimer simplement `INCOMPATIBLE_WORK_TYPES`** : crée des compteurs doublés et permet des doubles réservations.
2. **Dupliquer les `AvailabilityBlock` par WorkType** : fausse capacité, évaluations et placeurs historiques.
3. **Classer globalement tous les Focus avant toutes les réunions** : ignore la priorité limitée à mardi/jeudi matin.
4. **Réinterpréter automatiquement toutes les règles `PREFERRED` comme souples** : change les décisions/consentements passés.
5. **Réutiliser `transferred_from` pour le repli** : perd la provenance réelle et la distinction d'un transfert historique.
6. **Stocker une représentation de grille ou les couleurs comme métier** : invente une deuxième autorité de calcul.
7. **Réservation automatique dès qu'une minute est admissible** : viole la séparation proposition/confirmation et la protection des engagements.

## 6. Tranches et critères bloquants

**Gate `ASTRA-TP025` :** verdict `DECISION_REQUIRED` résolu par les **cinq décisions humaines explicites** ci-dessus; après CI de cette PR documentaire verte et fusion vérifiée, clore la gate `DONE` dans #1/#64. Aucun code, modèle, schéma/API ou UI métier modifié par la gate.

**TP-025A — `BLOCKED`** : séries/révisions/exceptions d'admissibilité, rang par fenêtre, migrations et projections physiques uniques; contrôle des conflits legacy, IANA/DST, héritage du parent, tests SQLite/PostgreSQL. **Ne pas activer le mode partagé auprès des utilisateurs avant B**.

**TP-025B — `BLOCKED`** : allocateur déterministe par intervalle, évaluation conjointe et revues, priorité/protection/échéance/ordre, réunions fixes locales indivisibles, provenance sans transfert fictif, confirmation idempotente/audit, adaptation conflit/`MOVE`, correction `weekly_schedule._plan()`, courses SQLite/PostgreSQL.

**TP-025C — `BLOCKED`** : API de lecture et grille visuelle hebdomadaire Configuration / Occupation / Plan proposé, sous-couloirs de superposition, légende et priorité par texte/contour, totaux non trompeurs, Google « non vérifié » distinct, mobile/clavier/alternative tabulaire.

**TP-025D — `BLOCKED`** : formulaire contextuel ouvert depuis barre, transitions opt-in d'anciens créneaux, aperçu/confirmation et conservation du brouillon, recette complète et non-régressions backend/frontend/E2E; **pas de drag-resize V1**.

**Tests requis, au minimum :**
- 120 minutes physiques partagées par 2 ou 3 activités = 120 minutes, sans double réservation; concurrence d'unités aux permissions identiques mais totaux insuffisants;
- mardi/jeudi Focus avant Réunions **à protection égale**, mercredi/après-midi neutres; contraintes > protection > priorité horaire > échéance > ordre utilisateur; explication et déterminisme;
- Réunions seules autorisées sur temps libre mar/jeu sans transfert, créneau fixe indivisible et réellement admissible, réservation Focus/réunion existante jamais déplacée;
- exclusion des occupations Google, lecture échouée, conflits historiques et `PROTECTED` strict; aucune capacité interparent supplémentaire ou `NULL` automatiquement cédée;
- nouvelle exception de permission ne retire pas l'admissibilité voisine, dernière permission → `NULL` résiduel sous enveloppe, ancien `CANCEL/REPLACE` inchangé;
- transition future opt-in atomique, inventaire des exceptions/confirmations, audit et identité préservée, date d'effet et DST Toronto;
- changement **seul** de priorité invalidant la prévisualisation (`409`), course réservation/réservation et réservation/configuration PostgreSQL/SQLite, rejeu de `command_id` et rollback audit;
- réservation future parentée `weekly_schedule._plan()` après/avant identiques en termes de scopes, dépassement des 93 jours, affiliation en milieu de semaine;
- trois barres simultanées, contraste et motif, clavier/mobile/lecteur d'écran, semaine DST (heures répétées ou inexistantes), vues différenciées, filtres sans masquage de l'autorité, brouillon conservé sur erreur.

**Gouvernance :** tests/CI applicatifs appartiennent aux futures tranches; la PR actuelle ne contient **que de la documentation**. La formalisation de la gate n'exécute aucun test métier local, ne crée aucun endpoint ni migration et ne promeut **aucune tranche DEV**. `TP-025A/B/C/D BLOCKED`, `TP-080D BLOCKED standby` jusqu'à ordre humain explicite.
