# TP-022A — Règles hebdomadaires de disponibilité (backend)

Cette tranche établit les **déclarations** récurrentes, pas encore une projection de
capacité effective ni une autorisation de planifier. Les anciens blocs manuels
`/api/capacity/weeks` restent inchangés et sont toujours seuls consommés par les
moteurs de capacité/Google/time blocks, jusqu'à TP-022B/C.

## Modèle

- `recurring_availability_rules` : UUID stable, propriétaire vérifié par le
  serveur et `version` de concurrence.
- `recurring_availability_revisions` : historique immuable numéroté; les
  modifications ne réécrivent aucune occurrence passée. La date
  `effective_from` est incluse, `valid_until` est exclusive; plusieurs plages
  d'une même journée nécessitent plusieurs règles. La dernière révision ayant
  commencé gouverne la date : après son expiration, une ancienne révision ne
  redevient jamais active.
- `history_events` : événements `AVAILABILITY_RULE_CREATED`,
  `AVAILABILITY_RULE_CHANGED`, `AVAILABILITY_RULE_DISABLED` à `task_id=NULL`
  et `entity_type=AVAILABILITY_RULE`. L'état de série, sa nouvelle révision et
  le fait d'historique sont enregistrés dans **une seule transaction**.
- Jours de semaine : lundi=0, mardi=1, ..., dimanche=6. Horaires civils
  `HH:MM` dans un fuseau IANA, `24:00` admissible seulement comme heure de fin.
  Pour une plage catégorisée, `work_type_id` existant obligatoire et
  `mode=PROTECTED|PREFERRED` (`PREFERRED` par défaut). Les plages générales
  exigent `work_type_id=NULL, mode=NULL`; les minutes générales ne sont pas
  implicitement données à tous les types.

## API authentifiée

- `POST /api/availability/rules` : création avec réglages complets.
- `GET /api/availability/rules` et `GET /api/availability/rules/{id}` :
  lecture et toutes les révisions, filtrées par identité autorisée.
- `PATCH /api/availability/rules/{id}` : remplacement complet de la
  configuration, avec `expected_version` et date d'effet **strictement
  postérieure à la dernière révision**. Une révision passée est interdite.
- `DELETE /api/availability/rules/{id}?expected_version=...&effective_from=...` :
  ajout d'une révision désactivée (pas de suppression physique).
- `GET /api/availability/rules/occurrences?from=YYYY-MM-DD&to=YYYY-MM-DD` :
  expansion en dates civiles sur **[from, to)** bornée à 93 jours, avec instants
  UTC, provenance de règle/révision et diagnostics DST. L'étiquette
  `RAW_DECLARATIONS_NOT_FREE_CAPACITY` est intentionnelle.

Pour une heure inexistante au printemps, l'occurrence est exclue et rapportée
comme `NONEXISTENT_LOCAL_TIME`. Pour une heure ambiguë à l'automne,
`AMBIGUOUS_LOCAL_TIME` est retourné jusqu'au choix explicite de
`start_fold`/`end_fold` (0 ou 1). Aucune heure n'est déplacée silencieusement.
Les bornes de dates et les chevauchements éventuels ne sont **pas** encore
fusionnés ou vérifiés comme capacité libre.

## Limites délibérées

L'API ne crée pas de dérogation, ne fusionne pas l'enveloppe/catégories, ne
construit pas les plages effectives, ne modifie aucune réservation et n'écrit
aucun événement Google. Les révisions futures insérées entre des révisions
existantes et les portées « cette occurrence »/« toute la série future » avec
réconciliation d'exceptions appartiennent à TP-022B. Les moteurs et empreintes
de confirmation évoluent en TP-022C; les résolutions de réservations en TP-022R.

Migrations : `0011_tp022a` additive pour SQLite et PostgreSQL privé;
l'historique existant et les blocs manuels sont conservés. Le downgrade refuse
de supprimer une série ou un audit nouveau. Le script de recette de sauvegardes
attend désormais la révision `0011_tp022a`; cela ne vaut pas autorisation de
production (TP-080D demeure bloquée).
