# TP-024C — Recette de non-régression : catégories et capacité

**WorkItem :** TP-024C · parent [#57](https://github.com/tchi99/TaskPlanner/issues/57) · roadmap [#1](https://github.com/tchi99/TaskPlanner/issues/1)  
**Référence :** [ADR-0023](architecture/ADR-0023-schedule-scopes-and-temporal-category-migration.md), ADR-0020 à ADR-0022.  
**Portée :** tests déterministes backend SQLite, tests Playwright simulés desktop/mobile et matrice de recette; **aucune migration réelle, aucun Google Calendar write, aucune mise en ligne Render/Supabase**.

## Scénarios automatisés ajoutés

| Risque | Preuve | Oracle |
| --- | --- | --- |
| Passage heure d'hiver (America/Toronto) | `test_tp024c_fall_back_two_scopes_on_distinct_folds_are_disjoint` | Deux occurrences à 01 h avec folds différents donnent deux périodes physiques différentes, 60 minutes au total |
| Collision interparent autour du fold | `test_tp024c_fall_back_parent_overlap_never_double_counts_minutes` | Intersection UTC de 30 min en `INCOMPATIBLE_SCOPES`; 90 minutes restantes, pas 150 |
| Heure inexistante au printemps | `test_tp024c_spring_forward_gap_does_not_create_phantom_parent_capacity` | Diagnostic `NONEXISTENT_LOCAL_TIME`; zéro capacité fictive |
| Compatibilité des anciennes API | `test_tp024c_legacy_weekly_endpoint_cannot_aggregate_parent_envelopes` | Sans `scope_id`, l'horaire legacy ne retourne aucune enveloppe des nouveaux parents; capacité globale disjointe |
| Identité et héritage après renommage | `test_tp024c_parent_rename_preserves_leaf_membership_and_physical_capacity` | UUID des parents et feuilles, rattachement et capacité inchangés |
| Réservations futures `CONFIRMED` | `TP-024C : réservations futures conservées avec consentement explicite` | Provenance inconnue visible, acquittement obligatoire, requête `acknowledge_bookings: true`, aucune écriture Google |
| Aperçu périmé | `TP-024C : aperçu d'affiliation périmé 409 est invalidé sans confirmation` | Diagnostic 409 visible, aperçu invalidé, brouillon sélectionné conservé |
| Conflit hérité | `TP-024C : conflit interparent hérité est visible sans fausse nouvelle erreur` | `PREEXISTING` rendu distinct de `NEW`, confirmation UI non artificiellement bloquée |
| Création d'une nouvelle feuille | `TP-024C : créer une feuille ne l'affecte pas automatiquement à son parent` | Feuille créée dans compatibilité, demande d'aperçu daté, aucune affectation implicite |

## Couverture existante préservée

- `tests/test_tp024a_domain.py` : deux `NULL` isolés, collisions interparents, appartenance temporelle, `CANCEL` sans restitution, indisponibilités globales/par parent, refus des transferts `PREFERRED` entre parents, DST.
- `tests/test_tp024a_api.py` : contrôle de version `409`, projection effective, affiliation atomique et concurrence SQLite; `tests/test_tp024a_migration.py` : migration additive, UUID, archives et garde de downgrade.
- `tests/test_tp080b_postgres.py` : validation PostgreSQL isolée, y compris scope/affiliation/version; `tests/test_tp023a_api.py` : sauvegarde groupée, `NEW/PREEXISTING`, conflits et réservations au-delà de l'horizon numérique.
- `frontend/e2e/availability.spec.ts` : grille des horaires, disponibilité réelle, annulation locale sur confirmation, conflits, mode protégé/préférentiel et édition par parent.

## Commandes de validation

Exécuter à la racine d'une copie synchronisée avec le `main` puis la branche TP-024C :

```bash
python -m compileall -q app tests migrations
pytest -q tests/test_tp024a_domain.py tests/test_tp024a_api.py tests/test_tp024a_migration.py tests/test_tp023a_api.py
pytest -q tests/test_tp080b_postgres.py  # nécessite TASKPLANNER_PG_TEST_URL sur une DB jetable
pytest -q
cd frontend
npm install --no-audit --no-fund
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

La CI GitHub exécute les jobs `backend`, `frontend`, `frontend-e2e`, `postgres` et `render-config` sur une PR. **La soumission d'une PR ne certifie pas ces jobs verts.** DevCockpit doit suivre la CI et ne réconcilier le roadmap qu'après fusion et preuves requises.

## Recette manuelle de contrôle, en environnement local jetable seulement

1. Migrer une base de test comportant des WorkTypes plats et une règle historique; vérifier qu'aucun parent n'est inféré de « Travail »/« Personnel » et que les UUID, règles, exceptions et engagements sont conservés.
2. Créer Travail et Personnel, puis les feuilles Focus, Gestion et Famille; confirmer explicitement leurs rattachements datés et contrôler l'historique avant/après.
3. Configurer des enveloppes **sans recouvrement physique**. Ajouter Focus dans Travail et Famille dans Personnel; vérifier que chaque sous-catégorie subdivise son parent, jamais ne s'y additionne, et que les deux compartiments `NULL` restent distincts.
4. Provoquer un chevauchement interparent : le diagnostic `NEW` interdit la confirmation; en cas d'héritage `PREEXISTING`, le conflit demeure visible sans retirer des archives. Refaire la vérification aux transitions DST Toronto.
5. Tester une exception `CANCEL` sur une occurrence : aucune restitution au `NULL` parent. À l'inverse, retirer une plage **récurrente** sous une enveloppe conservée restitue au `NULL` de ce parent seulement.
6. Avec un booking `CONFIRMED` futur et un changement de parent, afficher l'inventaire au-delà de 93 jours et demander un acquittement explicite; s'assurer qu'aucune réservation ni événement Google n'a été déplacé. Modifier une version après preview : la confirmation doit échouer en `409` sans écriture partielle.
7. Refaire le parcours au clavier, sur desktop et mobile; vérifier les états chargement/erreur, l'absence de débordement horizontal et la lecture seule des anciennes sources.

**Limites :** les Playwright utilisent des réponses simulées, pas un environnement de production; la projection chiffrée d'affiliation couvre 93 jours civils tandis que l'inventaire des réservations futures persistées n'est pas tronqué. Aucune attestation de recette réelle Render/Supabase/TP-080D ni aucun Go-Live n'en découle.
