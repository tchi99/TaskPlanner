# TP-022C — Intégration moteur des disponibilités effectives

## Sources de vérité

Les consommateurs capacité (POST /api/capacity/weeks/{monday}/evaluate),
propositions, matin, revue hebdomadaire et TP-041 utilisent la projection
disjointe TP-022B. Les blocs manuels historiques restent accessibles via
les routes d'origine et sont des déclarations strictes, jamais PREFERRED.
Les plages NULL ne sont pas empruntées à un WorkType.

Les capacités des réponses d'évaluation et de propositions sont **déclarées**,
non garanties libres : projection = DECLARED_NOT_CALENDAR_VERIFIED.
Le GET /api/availability/verified?week_start=YYYY-MM-DD&timezone_name=IANA
retourne les minutes réellement libres après retrait conservateur des
événements Google et des réservations locales; calendar_checked=true.
Une erreur de calendrier bloque la vérification, pas de repli à un agenda vide.
La lecture n'est pas une réservation et n'offre aucun verrou Google.

## Prévisualisation et confirmation TP-041

- Par défaut, le placement reste strict au WorkType.
- offer_transfers=true autorise l'**aperçu seulement** de minutes PREFERRED
  *restantes après les placements stricts* vers un autre WorkType.
- Chaque suggestion réaffectée expose transferred_from et des conséquences
  chiffrées. Une plage PROTECTED, MANUAL ou NULL n'est jamais donneuse.
- La confirmation réitère les mêmes arguments, exige le fingerprint exact
  et accept_transfers=true si une réaffectation est présente. Aucun transfert
  n'est accepté silencieusement.
- Les réservations acceptées restent de type du travail destinataire et
  conservent transferred_from en base. Le moteur de conflits reconnaît
  cette autorisation uniquement si la plage donneuse est toujours PREFERRED.
- Avant une confirmation, le calendrier est relu; l'état local est relu sous
  un verrou transactionnel global (BEGIN IMMEDIATE sur SQLite, verrou
  transactionnel consultatif sur PostgreSQL), et les nouveaux blocs
  n'empiètent sur aucune réservation locale ni engagement occupé.
- Le fingerprint inclut séries, révisions, exceptions, blocs manuels,
  réservations, projection, travaux et événements externes pertinents.
  Une confirmation désuète répond 409. Une offre gloutonne incomplète
  ne peut pas être confirmée.

L'adaptation d'une réservation déjà confirmée (annulation, déplacement,
résolution de conflits) reste **hors TP-022C** et relève de TP-022R.
Une déclaration d'indisponibilité ne change pas une réservation.
Aucune écriture Google Calendar n'est créée.

## Mise à jour technique

La migration Alembic 0013_tp022c ajoute le champ nullable
confirmed_time_blocks.transferred_from_work_type_id en conservant toutes les
réservations historiques. Une migration de retour refuse de supprimer des
provenances de transfert déjà acceptées.

Exécuter :
```bash
python -m compileall -q app tests
pytest -q tests/test_tp022c_integration.py tests/test_tp022c_migration.py
pytest -q
cd frontend && npm run build
```

Limites : l'API Google peut évoluer immédiatement après la relecture;
la projection de capacité déclarée n'est pas une promesse de temps libre;
un algorithme de placement glouton ne prouve pas l'impossibilité d'un autre
agencement. Les vues UX des exceptions et les commandes de résolution restent
dans TP-022D/TP-022R.
