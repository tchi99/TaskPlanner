# ADR-0016 — WorkSession, temps actif observé et calibration

**Statut : Accepted**  
**Date : 2026-10-10**  
**Portée : TP-071 (#12)**

## Décision

Une `WorkSession` est une observation explicite et durable, distincte de `Task.status`, de l'historique ADR-0005 et des réservations de capacité. Elle appartient à une Task stable et, facultativement, à un TaskSegment identifié par UUID. L'identité du segment est conservée comme référence historique sans FK destructive (un segment peut être retiré opérationnellement). La FK de la tâche reste restrictive.

Les états sont `ACTIVE`, `PAUSED`, `FINISHED`. `start` ouvre un intervalle, `pause` clôt l'intervalle actif et ajoute sa durée, `resume` ouvre un nouvel intervalle, et `finish` clôt le dernier intervalle s'il existe. Une session terminée est immuable. Les transitions sont explicites, révisionnées et horodatées UTC par le serveur; le client n'envoie jamais une durée travaillée. Le temps actif est la somme des intervalles explicitement ouverts, **pas** la différence entre le début initial et la fin. Une session laissée `ACTIVE` après fermeture du navigateur reste provisoire et doit être arrêtée explicitement : il n'y a aucune surveillance passive ou arrêt inféré. Une unique session ACTIVE est permise dans l'instance locale, vérifiée par le domaine applicatif et par index unique partiel SQLite.

Le cumul fermé est stocké en secondes entières. `active_since` reste présent seulement à l'état actif; sa durée en cours est **provisoire** et n'est pas retenue dans les agrégats de calibration. Toute observation reste potentiellement incomplète puisque du travail sans session n'est pas observable. Un `planned_minutes` optionnel, choisi explicitement, sert uniquement à suggérer une pause/réévaluation lorsque la durée active l'atteint. Aucun arrêt obligatoire ni mutation du calendrier.

Le WorkType effectif et l'estimation applicable sont **figés au début** comme contexte minimal de comparaison; l'estimation actuelle reste la source autoritaire pour la planification. Ne collecter ni titres, ni notes, ni activité clavier/souris, ni détails privés de calendrier.

Les commandes écrivent l'état de session et un événement sémantique `WORK_SESSION_STARTED/PAUSED/RESUMED/FINISHED` dans une **seule transaction**, selon ADR-0005. L'événement cible la Task ou le Segment (types déjà admis) avec uniquement l'identifiant de session, l'état et le cumul de secondes. Un motif structuré facultatif est purement déclaré, jamais interprété comme preuve causale. Les transitions en conflit retournent 409.

La calibration est descriptive : durée typique et fréquence des interruptions par WorkType, puis, lorsque trois unités terminées avec estimation connue existent, médianes estimation/observé et distribution des écarts sur ces seules unités. Ne pas additionner des estimations Task et Segment; chaque unité mesurée conserve son identité. Une cible supprimée ou non terminale n'est pas une observation complète. **Même une unité terminale peut avoir du temps non capturé** : l'API publie explicitement cette réserve et ne corrige pas l'estimation automatiquement. Aucune interprétation clinique ou causalité n'est produite.

Hors scope : timesheets, facturation, capteurs de présence, saisie rétroactive de temps, calendrier écriture, apprentissage prédictif TP-072, infrastructure d'analytique externe.

## Conséquences

- Migration additive sans réinterprétation des tâches ni backfill d'événements.
- API de contrôle et projections côté FastAPI; React ne calcule pas l'autorité des durées.
- Résultats déterministes sans connexion à Google Calendar ni OpenAI.
- L'absence d'instrumentation doit toujours rester « inconnue », jamais « zéro travail ».
