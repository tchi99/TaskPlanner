# ADR-0013 — Revue quotidienne locale à décisions explicites (TP-060)

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-060**

## Contexte

TP-031 livre une lecture du matin, pas un plan quotidien enregistré. TP-060 doit permettre un choix du matin, une réévaluation légère lorsque l'utilisateur constate un événement significatif, une fermeture en fin de journée et la remise en évidence des éléments restés ouverts.

## Décision

- Un enregistrement local par date civile et fuseau IANA conserve uniquement une **sélection ordonnée d'identifiants de tâches**, son état OPEN/CLOSED, une révision et les futures dates de revue choisies à la clôture. Cette sélection est une intention explicite, **pas** un créneau, un statut de tâche ni une garantie de faisabilité.
- L'interface du matin TP-031 reste une projection en lecture seule. Un POST confirmé choisit les tâches ouvertes clarifiées. L'utilisateur déclenche une réévaluation sur événement significatif par une nouvelle lecture des faits et, s'il le souhaite, confirme une nouvelle sélection. Les changements ne sont jamais appliqués par une simple lecture.
- À la fermeture, les tâches sélectionnées encore ouvertes exigent **chacune** une date de prochaine revue strictement ultérieure. Les tâches déjà terminées/annulées n'exigent pas de date; aucune tâche n'est complétée automatiquement. Un jour fermé ne peut pas être réécrit dans cette première tranche.
- Les jours antérieurs laissés ouverts et les prochaines revues arrivées à échéance font réapparaître les tâches encore ouvertes, sans auto-sélection. Un événement plus récent pour une tâche remplace son ancien rappel. Une tâche fermée n'apparaît plus; aucune absence de clic n'est qualifiée de faute, de procrastination ou de causalité.
- Les commandes exigent une confirmation explicite et une révision attendue pour éviter d'écraser silencieusement une décision entre deux vues. L'état est local SQLite (migration 0006). Les contenus de calendrier, titres et notes ne sont pas copiés dans ce stockage.
- Aucun déplacement, modification de protection, date d'échéance, mutation de progression ou appel d'écriture Google Calendar/Reclaim n'est réalisé par le cycle quotidien. Les statuts restent sous les commandes dédiées de tâches et de segments.

## Limites

- Le plan quotidien n'est ni une réservation de temps, ni une allocation validée par un moteur horaire journalier. TP-031 affiche la capacité manuelle et le scénario hebdomadaire hypothétique; l'utilisateur conserve le jugement sur la sélection.
- La comparaison se base sur les statuts courants au moment de la lecture/fermeture; elle ne déduit pas du temps de travail à partir d'une absence d'événement. Aucun système de notification, projection comportementale, semaine revue (TP-061) ou édition d'un jour déjà clos n'est introduit.
- La vérification de révision suffit au premier usage SQLite local; une future concurrence multi-utilisateur demanderait un verrouillage transactionnel plus strict.
