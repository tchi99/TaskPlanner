# ADR-0008 — Propositions hebdomadaires non engageantes (TP-030)

**Statut : Accepted**  
**Date : 2026-10-10**  
**WorkItem : TP-030**

## Contexte

ADR-0002 sépare PlanningProposal et PlanningDecision; ADR-0004 évite le double comptage; ADR-0006 évalue la capacité manuelle; ADR-0007 protège les engagements. TP-030 doit présenter des compromis sans supposer de calendrier accepté.

## Décision

- Une proposition est générée à la demande à partir d'une sélection **explicite** de tâches ouvertes clarifiées, d'une semaine ISO et des blocs de capacité existants. L'instantané est éphémère; aucune proposition, décision ou sélection n'est persistée.
- KEEP présente le verdict initial. Chaque DEFER retire exactement une **tâche entière** non protégée de la sélection hypothétique, recalculée via le moteur TP-020. Une tâche comportant un segment ouvert effectivement protégé n'est jamais candidate à un report de tâche entière.
- Le report est un retrait **hypothétique de la semaine**, et non le déplacement d'un créneau réel; aucune date de reprise n'est inventée. Échéance existante et inconnues de charge sont visibles. Une capacité simulée favorable ne prouve pas la faisabilité calendaire ou le respect d'une échéance.
- Si la charge connue dépasse la capacité, réduction de portée et délégation sont des pistes **qualitatives**, sans gain présumé ni verdict chiffré amélioré. Les estimations manquantes appellent une clarification, jamais une conversion en zéro.
- Les propositions offrent plusieurs options lorsqu'elles sont réellement disponibles; le système n'invente pas de déplacement protégé pour atteindre un nombre arbitraire de solutions.
- POST /api/capacity/weeks/{week_start}/proposals est strictement en lecture seule. Ses identifiants identifient uniquement la réponse courante; aucun endpoint accept/apply n'est introduit. Toute mutation future nécessitera une commande explicite, une revalidation des faits et une décision utilisateur distincte.

## Conséquences et limites

Le backend détient les règles; React présente options, conséquences et confirmations requises sans les appliquer. Aucune tâche, segment, protection, estimation, échéance ou disponibilité n'est modifié. Ni plan durable, ni affectation future, ni Google Calendar/Reclaim, ni revue du matin (TP-031) ne sont introduits.
