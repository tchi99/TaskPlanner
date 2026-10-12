# TP-022R — Résolution explicite des réservations locales

## Autorité et portée

Une dérogation TP-022B continue d'enregistrer une indisponibilité véridique
sans annuler/déplacer une réservation. Les réservations actives restent
`CONFIRMED` même lorsqu'un diagnostic `OPEN` est projeté. Le seul chemin
pour annuler/déplacer une réservation est la commande explicite TP-022R.

Aucune écriture Google Calendar, aucun changement de statut/estimation de
tâche et aucun transfert PROTECTED implicite. La résolution est locale, sous le
même verrou transactionnel que la confirmation TP-022C.

## API

Point de départ : `/api/capacity/weeks/{week_start}/time-blocks/{booking_id}/resolution`.

1. `POST /preview` : `decision=CANCEL|MOVE|KEEP`, `expected_revision`,
   `timezone_name`, `reason`. Un MOVE ajoute `starts_at` et `ends_at`
   avec décalage UTC explicite. Retourne empreinte, conflits ouverts et
   conséquences. Aucune mutation.
2. `POST /confirm` : mêmes champs, `fingerprint`, `decision_id` UUID
   pour idempotence, `confirmed=true`. L'état local est relu après
   acquisition du verrou puis la proposition recalculée; une empreinte ou
   révision périmée produit HTTP 409.
3. `GET /history` : événements append-only du booking (décision, raison,
   auteur de la commande, origine/destination, référence et horodatage).

CANCEL passe `CONFIRMED → CANCELLED` et garde le fait initial.
MOVE passe `CONFIRMED → SUPERSEDED`, crée une nouvelle réservation active
de même durée et même travail, et conserve l'ancienne ligne. En cas d'échec,
la transaction complète est annulée. KEEP laisse le bloc actif et le
diagnostic de conflit ouvert, en augmentant sa révision et en inscrivant
la décision. Les replays du même `decision_id` n'appliquent pas une deuxième
fois la mutation; un réemploi contradictoire est refusé.

Un déplacement exige une couverture complète de disponibilité effective
compatible, absence de nouvelle occupation locale/Google, tâche et segment
ouverts, heure future et date limite respectée. Un déplacement dans une
plage PREFERRED réaffectée conserve la provenance et n'autorise jamais
un nouveau transfert. Une annulation est disponible même sans Google
Calendar : aucun créneau n'est créé par cette opération.

Les conflits OPEN demeurent dans les projections TP-022B/C et la capacité
vérifiée tant qu'une réservation active incompatible existe. Après
CANCEL/MOVE, ils disparaissent de la projection courante; le journal conserve
la preuve de la résolution. L'UI de ces commandes relève de TP-022D.

## Migration et validation

Alembic 0014 ajoute `status` et `revision` aux réservations existantes
(valeurs initiales `CONFIRMED`, `1`) et autorise des faits `TIME_BLOCK`
dans l'historique. Aucun effacement des réservations historiques; downgrade
refusé après une décision confirmée. La contrainte d'unicité historique
`(task_id, segment_id, starts_at)` est conservée.

Validations visées :

```bash
python -m compileall -q app tests
pytest -q tests/test_tp022r_api.py tests/test_tp022r_migration.py
pytest -q
cd frontend && npm run build
```
