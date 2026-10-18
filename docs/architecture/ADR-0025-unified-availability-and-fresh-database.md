# ADR-0025 — Modèle unique de disponibilités et installations vierges (ASTRA-TP026)

**Statut : Accepted — trois décisions D1–D3 approuvées explicitement par l'utilisateur le 2026-10-18**  
**Date : 2026-10-18**  
**WorkItem : ASTRA-TP026 — analyse architecture suppression legacy et base vierge**  
**Parent : [TP-026 / issue #70](https://github.com/tchi99/TaskPlanner/issues/70)**  
**Roadmap canonique : [issue #1](https://github.com/tchi99/TaskPlanner/issues/1)**  
**Base analysée : `main@d03215e7e2db786fb76b616f6e8d779fc34f1787`** (TP-025A/B/C/D intégralement livrées).  
**Références :** AGENTS.md; ADR-0002/0004/0005/0009/0019/0020/0021/0022/0023/0024.

**Portée de l'autorité :** cette décision stabilise la nouvelle architecture pour une **installation vierge de développement**. Elle n'est ni une PR de code, ni une autorisation de déploiement, ni une suppression de données. La livraison documentaire clôt la gate seulement après vérification et fusion de la PR; les WorkItems `TP-026A/B/C` demeurent `BLOCKED` tant que leur démarrage n'a pas été autorisé. `TP-080D` reste `BLOCKED` en standby.

## 1. Contexte et constats de la gate

L'utilisateur est en développement initial et déclare ne vouloir **conserver aucune donnée** dans sa base locale/test (y compris tâches, projets, catégories, historiques de test et réservations locales). Il demande de supprimer le **parcours legacy**, pas les garanties fondamentales de TaskPlanner, et de pouvoir créer une plage depuis une **grille initialement vide** via `+ Nouvelle plage`.

Le rapport ASTRA-TP026 (`DECISION_REQUIRED`, analyse en lecture seule sur `main@d03215e7`) constate :
- `SqlScheduleScopeRepository.list_owner()` **injecte** un parent de compatibilité synthétique; `create_scope()` exécute `ensure_compatibility()`. Un reset de base ne fait donc pas disparaître la compatibilité.
- `WorkType` n'a pas de parent direct; `ScopeAffiliation` et `compatibility_scope_id` portent le rattachement, avec saisie en deux opérations UI.
- `project_effective()` produit des compartiments exclusifs; `project_eligibility()` y ajoute des choix multiples en cas de minutes générales résiduelles; des consommateurs bifurquent toujours entre moteurs **exclusif** et **partagé** selon la semaine.
- Capacité, propositions, time blocks, revue hebdomadaire, brief du matin, calendrier et résolution `MOVE` utilisent aujourd'hui des chemins partiellement distincts. Un retrait partiel peut faire diverger la faisabilité et la planification.
- `WeeklyEligibilityChart.showFragment()` crée l'action d'édition **uniquement après sélection d'une barre** : impossible de créer une première permission lorsque la grille est vide. `WeeklyCapacity.tsx` offre aussi une configuration manuelle legacy séparée.
- `evaluate_eligibility_week()` peut qualifier `OVER_CAPACITY` un simple échec du placeur glouton; ce diagnostic va au-delà de la preuve obtenue.
- Les exceptions d'admissibilité ont déjà un modèle domaine/persistance, mais l'édition série ne fournit pas un traitement de bout en bout des exceptions futures et renvoie `UNRESOLVED_ELIGIBILITY_EXCEPTIONS`.
- La chaîne Alembic active va jusqu'à **`0019_tp025d`**; tests, recette de restauration jetable et documentation référencent des révisions historiques.

**Décisions déjà prises par l'utilisateur avant la gate :** départ d'une base locale de développement vierge; aucun besoin de conserver/transférer les données legacy; suppression du parent de compatibilité et des écrans/branches exclusifs; formulaire accessible par un CTA `+ Nouvelle plage` même sans aucune barre. **Ces choix ne sont pas rouvertes.**

## 2. Trois décisions explicitement approuvées

### D1 — `WorkType.scope_id` obligatoire et non modifiable en TP-026

Chaque `WorkType` **appartient à exactement un `ScheduleScope` réel**, via un `scope_id` non nul portant une clé étrangère restrictive vers un parent appartenant au même propriétaire. L'API `POST /api/work-types` exige un parent actif valide lors de la création. Les lectures renvoient le parent réel; la modification de nom et métadonnées autorisées est possible avec version/concurrence; **changer de parent n'est pas possible en TP-026**. Aucune inférence par nom, aucun parent implicite ni passage par une affiliation datée.

Ceci supprime du **modèle cible neuf** : `compatibility_scope_id()`, `ScheduleScope.is_compatibility`, `ScopeAffiliation`, ses versions, la création automatique du parent synthétique, les tables `work_type_scope_assignments` et `work_type_scope_versions`, les endpoints `/api/schedule-scopes/affiliations/*` et la conversion d'affectations historiques. Les relations et validations des services/projections doivent utiliser `WorkType.scope_id` **directement**, sans créer un nouveau fallback de compatibilité déguisé.

**Le reclassement d'une sous-catégorie existante est hors TP-026.** Il demanderait ultérieurement une commande explicite, un examen des tâches/réservations et un nouveau choix architectural; ne jamais accepter silencieusement un `PATCH scope_id`.

Les enveloppes `GENERAL` sont **propres à leur parent**; deux parents ne possèdent pas la même minute physique planifiable. Les sous-catégories d'un même parent peuvent, elles, être admissibles sur les mêmes minutes selon ADR-0024. La frontière de propriété des données est validée côté backend par l'identité propriétaire du parent : une FK seule ne suffit pas.

### D2 — Nouvelle racine Alembic pour une **base vierge**, sans réexécution historique

La cible de déploiement **vierge** possède **une nouvelle baseline Alembic** déclarant le schéma final complet (tables, clés étrangères, index, contraintes, timestamps UTC), fonctionnant sous **SQLite de test/développement** et **PostgreSQL dans un schéma privé `taskplanner`**, selon les garanties d'ADR-0019. Ne pas rejouer `0001 → 0019_tp025d` pour recréer puis détruire les anciennes structures. Aucun parent, WorkType, règle, réservation ni exemple ne doit être précréé.

Les 19 scripts historiques restent **dans l'historique Git, hors chemin Alembic actif** de l'installation neuve : l'organisation des dossiers/commandes doit garantir une **seule tête effective**, sans double racine importée par erreur. Ne pas réécrire l'histoire de Git en prétendant qu'il n'y a jamais eu d'anciennes migrations. Les tests ou restaurations qui mentionnent `0019_tp025d` doivent être adaptés à la **nouvelle baseline réelle**; la restauration jetable doit restaurer une nouvelle installation, pas transformer une base historique.

**Les bases anciennes existantes ne sont pas migrées vers le schéma nouveau.** Le bootstrap/migrateur détecte et **refuse explicitement** toute base non vide dotée de l'ancien schéma/version : ne pas appliquer une migration destructive automatique, ne pas faire `alembic stamp head` pour contourner un schéma incompatible et ne pas supprimer de tables lors du démarrage FastAPI.

**Autorisations de suppression séparées des migrations :** l'utilisateur a permis de **repartir de zéro pour les données de développement local/test**, et n'a aucune donnée à conserver. Avant la moindre suppression réelle, vérifier concrètement le projet Compose, les noms et ID réels des conteneurs/volumes, l'hôte et la base backend/migrateur, la cible `taskplanner-local` / `taskplanner_dev` / schéma privé `taskplanner`. Arrêter et réinitialiser **uniquement** le volume PostgreSQL **local isolé identifié**. Ne jamais présumer son nom à partir d'un préfixe Compose ni lancer `down -v` à l'aveugle. Le dépôt GitHub ne donne pas accès à l'environnement Docker de l'utilisateur. Un hôte Supabase/Render distant, partagé ou de production requiert identification et autorisation spécifiques; `TP-080D` reste `BLOCKED`. Ne supprimer ni base, ni volume, ni schéma dans cette gate documentaire.

**La source d'autorité de migration reste Alembic/SQLAlchemy côté serveur**, pas des scripts React ni un second moteur. Le schéma PostgreSQL privé, permissions restreintes, TLS et UTC d'ADR-0019 restent intacts.

### D3 — Capture libre des tâches, classification obligatoire avant réservation

L'**Inbox** et la capture de projet/tâche demeurent possibles **sans `work_type_id`** : aucune friction de saisie anticipée n'est imposée.

**Avant toute création ou déplacement de réservation `CONFIRMED`,** le travail à réserver possède obligatoirement un `work_type_id` actif relié à un vrai parent de l'utilisateur, dont une permission le rend admissible sur toutes les minutes envisagées. Une tâche non classée reçoit un diagnostic/action de classification; elle n'est pas discrètement affectée à un type, un parent ou à du temps `NULL`.

Le temps `GENERAL` encore sans permission demeure **`NULL` résiduel** dans une enveloppe; il **n'est jamais alloué implicitement** à une tâche sans type même si un seul parent est actuellement configuré. C'est une clarification concordante avec ADR-0023 : elle **retire le cas spécial** de l'allocateur partagé qui utilise aujourd'hui ce résiduel pour des demandes non typées.

Appliquer ce contrat **uniformément** aux aperçus, propositions, réservations locales à heure fixe, révisions, résolution `MOVE`, évaluation de capacité et vues matin/hebdomadaire, avec raison explicite de non-placement. Aucun algorithme ne doit attribuer un type par inférence, ni traiter « non classé » comme « aucune charge de travail ».

## 3. Modèle métier et fournisseur commun retenus

```text
ScheduleScope(owner, id, nom, état, version)
  ├── Enveloppes physiques récurrentes + exceptions physiques
  └── WorkType(owner par parent, id, scope_id NON NULL, nom, version)
        └── EligibilitySeries(révisions futures, jours, heures, priorité locale)
              └── EligibilityException(occurrence / permission ciblée)
             ↓
Projection Python unique : fragments physiques disjoints UTC
    + zéro, une ou plusieurs permissions par fragment
    – occupations Google vérifiées et réservations locales
             ↓
Capacité • propositions • revue matin/semaine • calendrier • bookings/KEEP/CANCEL/MOVE
             ↓
Aperçu/version/empreinte → confirmation sous verrou + audit
```

Les deux calculs **physique** puis **permissions** peuvent rester deux étapes *complémentaires* internes d'un fournisseur unique, mais **jamais deux moteurs concurrents sélectionnés d'après le contenu de la semaine**. L'absence de permissions n'autorise pas le fallback vers `suggest_time_blocks()`, un bloc manuel historique ou une capacité `NULL` implicite.

**Invariants maintenus :**
- Chaque minute appartient à zéro ou un parent; les permissions intra-parent sont multiples, mais les minutes physiques non additives.
- Deux permissions concurrentes de 120 min chacune sur une plage de 120 min n'offrent que 120 min de capacité totale; une seule réservation peut y être confirmée.
- L'arbitrage d'ADR-0024 reste : contraintes → protection effective d'une tâche → priorité locale à la fenêtre → échéance → ordre utilisateur (départage stable). Focus prioritaire mardi/jeudi matin, mercredi et après-midi neutres dans le scénario de référence.
- Indisponibilité physique vs retrait d'une permission : l'une retire la capacité, l'autre ne change pas la capacité ni les autres permissions. Dernière permission retirée → `NULL` sous enveloppe, jamais une affectation automatique.
- Un événement Google vérifié occupé bloque toutes les permissions du fragment; une lecture Google échouée n'est jamais interprétée comme liberté. Aucun droit d'écriture Google nouveau.
- Les nouvelles réservations confirmées restent des engagements, même lorsqu'un changement de règle crée un conflit; `KEEP/CANCEL/MOVE` avec confirmation, versions, idempotence, verrouillage et audit. L'histoire comportementale des **nouvelles** commandes est conservée et atomique malgré le reset autorisé de la base de développement historique.
- Temporalité IANA / DST, révisions futures, date d'effet régulière **au plus tôt demain** dans le fuseau visé; pour les besoins **d'aujourd'hui**, utiliser une exception datée (ne pas changer cette règle sans nouvel arbitrage).
- Les estimations inconnues ne sont pas des zéros. `OVER_CAPACITY` est réservé à une impossibilité **démontrée**; une heuristique gloutonne qui échoue doit retourner un résultat de type **placement non trouvé**, sans prouver l'infaisabilité.

## 4. Surfaces à retirer, adapter et conserver

| Surface | Contrat cible |
|---|---|
| `domain/schedule_scopes.py`, repositories, `work_types` | Retirer parent synthétique, affiliations temporelles/fallback; `WorkType.scope_id` obligatoire, FK restrictive et propriétaire vérifié |
| `recurring_availability` / `effective_availability` | Conserver l'enveloppe et les primitives UTC/civiles utiles; supprimer l'affectation exclusive `CATEGORIZED`, les modes de plage `PROTECTED/PREFERRED` et les routes de création exclusives |
| `eligibility_projection`, `planning_availability` | Projection physique + permissions multiple unique; pas de double capacité ni d'aiguillage par présence d'une permission |
| `eligibility_edits` | Conserver prévisualisation/confirmation, séries et exceptions; retirer `legacy_rule_id`, `expected_legacy_version`, `CUTOVER`, traitement de conversion |
| `time_blocks`, allocateurs, résolution `MOVE` | Un seul placeur éligible, tâches typées avant réservation, retirer `PREFERRED_TRANSFER` et leur faux coût; garder réunions locales fixes, confirmations, conflits, idempotence et audit |
| Capacité, propositions, `weekly.py`, brief matin, calendrier | Rebaser tous les consommateurs sur la projection commune; plus d'appel exclusif ou de lecture directe de blocs manuels obsolètes |
| `weekly_schedule` | Reprendre les transactions atomiques et révisions ciblées pour **les enveloppes**; supprimer les commandes de compartiments catégorisés |
| `availability_blocks` / `WeeklyCapacity.tsx` | Retirer la saisie manuelle exclusive; offrir les cas légitimes d'ajout/indisponibilité datée via des **exceptions physiques** explicites |
| `ScheduleCategories`, `AvailabilityPlanner`, `WeeklyEligibilityChart`, `EligibilityContextEditor` | Parcours unique, état vide et `+ Nouvelle plage`, création de WorkType directement sous un parent, configuration + occupation + plan; retirer la conversion legacy et les grilles exclusives |
| Routes HTTP publiques | Conserver `/api/schedule-scopes` et `/api/work-types` (création parentée); retirer `/api/schedule-scopes/affiliations/*` et `/api/capacity/weeks/{week}/blocks`; garder lecture hebdomadaire/admissibilité, time blocks et résolution |
| Reçus de commandes et historique | Conserver idempotence, empreintes, audit append-only et commandes explicites; renommer si nécessaire sans perte des garanties |
| Tests et CI | Remplacer tests du legacy par tests du nouveau contrat; adapter `verify_disposable_restore.py`, migrations et job PostgreSQL |

**Ne pas supprimer `Task.ProtectionLevel.PROTECTED`** : l'ancien mode de **plage** nommé `PROTECTED` est retiré, mais la protection effective des **tâches** demeure. Éviter toute suppression globale au simple nom `PROTECTED`.

Les anciens champs de DTO et anciens endpoints supprimés doivent **échouer explicitement** s'ils sont utilisés par erreur, au lieu de simuler une commande réussie en ignorant des champs. Le retrait d'un API historique est ici intentionnel pour **les nouvelles installations vierges uniquement**, sans promesse de mise à niveau d'anciens clients/bases.

**Gestion d'exception d'admissibilité requise de bout en bout :** exposer une commande utilisateur pour annuler/remplacer une occurrence de permission sans altérer ses voisines; lever de manière explicable les `UNRESOLVED_ELIGIBILITY_EXCEPTIONS` avant d'éditer une série. L'UI ne doit pas laisser une exception irréconciliable bloquer à jamais toute modification.

## 5. Nouvelle UX initiale obligatoire

À la première ouverture, afficher une configuration réellement vide (ni catégorie ni parent précréés) :
1. **Créer un parent** (ex. Travail ou Personnel) et définir **une enveloppe** de capacité physique récurrente sur ce parent.
2. **Créer une sous-catégorie directement rattachée** au parent choisi (ex. Focus work, Réunions), sans affiliation ultérieure.
3. **Créer la toute première permission depuis la grille vide** via un CTA `+ Nouvelle plage` indépendant de `showFragment()`. Le formulaire comporte parent, WorkType, jours récurrents, heures civiles, rang contextuel facultatif, fuseau IANA et date d'effet; il valide l'enveloppe sans inventer de capacité.
4. Prévisualiser les conséquences et confirmer; permettre ensuite d'ajouter d'autres permissions simultanées et d'éditer une barre par formulaire contextuel.
5. Offrir les vues Configuration / Occupation réelle vérifiée / Plan proposé, les exceptions datées et les éventuelles indisponibilités dans le **même parcours**; alternatives tabulaires, navigation clavier et mobile. Glisser-redimensionner **hors V1** (ADR-0024).

**Pas de précréation** des parents Travail/Personnel ou des sous-catégories par migration : ce sont des exemples de saisie, pas des données d'installation. Aucun écran « Compatibilité (héritage) », « Convertir la règle historique », « Rattacher la feuille créée en compatibilité », « Catégorisé protégé/préférentiel » ou bloc manuel exclusif dans l'UX cible.

## 6. Impact ciblé sur les ADR déjà acceptés

**Le présent ADR prévaut uniquement sur les clauses de compatibilité des ADR antérieurs spécifiées ici.** Les garanties qui ne sont pas mentionnées restent applicables. Aucun ADR antérieur n'est réputé intégralement abrogé.

| ADR antérieur | Clauses ciblées remplacées pour le **nouveau modèle vierge** | Contrats conservés |
|---|---|---|
| **ADR-0019** | L'exigence d'appliquer à une nouvelle installation la **chaîne historique complète** est remplacée par une nouvelle baseline unique et les révisions archivées hors chaîne active | SQLAlchemy/Alembic, PostgreSQL privé, SQLite offline, TLS, UTC, droits et séparation backend |
| **ADR-0020** | Blocs manuels historiques, compartiments `CATEGORIZED`, modes de plage `PROTECTED/PREFERRED`, transferts préférentiels et conservation automatique de leurs identités | Enveloppe physique, exceptions, temps civil IANA/DST, Google busy, projection déterministe et capacité réelle |
| **ADR-0021** | Les références aux transferts et à la protection de **plages** ne se transposent plus au nouveau modèle | Conflit ouvert, réservations confirmées non déplacées, `KEEP/CANCEL/MOVE`, verrous, audit et confirmation |
| **ADR-0022** | Édition de sections `CATEGORIZED` et sauvegarde ciblée des anciens compartiments | Brouillon → aperçu → confirmation, révisions futures, supersession ciblée, atomicité, 409, idempotence |
| **ADR-0023** | Parent de compatibilité, affiliations datées, rétro-migration et reclassement temporel D1/D4/D5 pour les **données inexistantes d'installation neuve** : remplacés par `WorkType.scope_id` obligatoire immuable en TP-026 | Hiérarchie de deux niveaux, exclusivité physique interparent, `NULL` sans allocation implicite, pas d'inférence |
| **ADR-0024** | D4 (conversion `opt-in` d'anciennes plages), branches runtime legacy et empreintes d'affiliations temporaires devenues sans objet | Permissions multiples, priorités par fenêtre, choix uniques sur minutes physiques, repli, exceptions de permission, grille |
| **ADR-0002/0004/0005/0009** | Aucun remplacement | Séparation propositions/décisions; charge, protection de tâches et estimations; historique des faits nouveaux; Google lecture seule |

**Clarification sur ADR-0019 :** celui-ci ne mandate pas à lui seul la migration de toute ancienne base vers une nouvelle installation; la décision ici est de **ne plus offrir cette mise à niveau**, de conserver les scripts historiques comme artefacts Git, et de construire une nouvelle baseline unique. Les contraintes de persistance sécurisée d'ADR-0019 demeurent intactes.

## 7. Découpage de livraison et limites de gate

L'analyse ASTRA-TP026 avait le verdict **`DECISION_REQUIRED`** sur D1–D3. L'approbation explicite de ces trois décisions et le présent ADR stabilisent le cadrage vers **`ARCHITECTURE_READY`** à condition de valider, fusionner et vérifier le dossier documentaire.

| Tranche | Exigences clés | Statut à l'issue de cette gate |
|---|---|---|
| **ASTRA-TP026** | Analyse lecture seule, décisions D1–D3 approuvées, ADR-0025 publié et roadmap réconcilié | `DONE` seulement après PR documentaire verte et fusionnée |
| **TP-026A** | Nouveau domaine/schema, parent `WorkType.scope_id`, nouvelle baseline active, **adaptation immédiate des consommateurs indispensables** (capacité, propositions, calendrier, matin, hebdo, réservations, MOVE); tests backend et transactions | `BLOCKED` |
| **TP-026B** | UI de première utilisation, création parentée, grille/éditions `+ Nouvelle plage`, gestion exceptions et enveloppes, retrait des surfaces UI exclusives; tests frontend/E2E | `BLOCKED` |
| **TP-026C** | Retrait du code/routes morts, tests croisés, audit backend, **fresh bootstrap via Alembic réel** sur SQLite + PostgreSQL, Docker vérifié, docs et recette | `BLOCKED` |
| **TP-080D** | Go-Live et stockage hébergé | `BLOCKED`, standby jusqu'à décision explicite |

**TP-026A et B rompent ensemble certains contrats**; les états intermédiaires ne sont pas des livrables production. L'adaptation de tous les consommateurs indispensables est **dès A**, pas différée à C. **Cette gate ne lance aucune tranche DEV, aucune migration ou reset de base.** L'autorisation préalablement donnée pour TP-025A–D ne s'étend pas automatiquement à TP-026; l'ordre et les conditions de promotion restent ceux du roadmap.

## 8. Recette obligatoire des futures tranches

- Base neuve réelle **sans tables** → Alembic **nouvelle racine** → catalogue vide; aucune création de compatibilité au premier `GET` ni au premier `POST`.
- API et UI publiques : créer parent, deux sous-catégories directement rattachées, enveloppe, **première** permission sans barre préalable, seconde superposée, sauvegarde versionnée. Aucun appel obligatoire à une API de conversion.
- Focus mar/mer/jeu 09–12 et 13–15; Réunions lun–ven 10–12 et 13–16; priorité Focus mar/jeu matin et repli réunion si libre. **120 minutes en chevauchement restent 120 minutes physiques**, pas 240.
- Cohérence des résultats capacité, propositions, réunions fixes, calendrier, brief du matin et revue hebdomadaire. **Échec heuristique ≠ surcharge démontrée.**
- Task non typée capturable et modifiable, mais impossible à proposer/réserver, y compris si un unique parent et temps `NULL` existent. Une tâche classée redevient planifiable seulement sur permissions réelles.
- Réservation `CONFIRMED` conservée lors d'une révision de règles; conflits explicites même au-delà de 93 jours, résolution `KEEP/CANCEL/MOVE` auditée, pas d'écriture Google.
- Exceptions de permission indépendantes et éditables, dernière permission → `NULL` résiduel, indisponibilité physique globale/parent; exceptions datées pour aujourd'hui.
- Versions, `command_id`, fingerprints, `409`, concurrence SQLite/PostgreSQL, rollback et audit; IANA `America/Toronto`, DST instants inexistants/ambiguës.
- Visualisation accessible trois couches, chevauchement de plusieurs sous-catégories, clavier, lecteur d'écran, mobile et brouillon conservé sur conflit.
- **Recette réelle** contre backend branché à une base créée par **Alembic** (pas uniquement `Base.metadata.create_all()`) et vrai PostgreSQL, en complément des mocks Playwright; CI PostgreSQL doit réellement exécuter ces nouveaux scénarios et `verify_disposable_restore.py` doit utiliser la nouvelle baseline.
- Procédure documentée de reset **ciblé et local**, refus clair sur ancienne base non réinitialisée, zéro suppression intempestive au démarrage, aucune donnée exemple ou structure historique.

**Conséquences et exclusions :** la rupture de compatibilité legacy est **volontaire et limitée au nouvel environnement vierge**, en conformité avec l'absence de données à conserver. Le schéma et le code cible peuvent devenir plus simples, au prix d'une coordination stricte backend/API/frontend/tests et d'une ligne de base Alembic contrôlée. Aucun déploiement Render/Supabase, reset hébergé, modification Google ou activation TP-080D n'est inclus.
