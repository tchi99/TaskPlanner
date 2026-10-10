# ADR-0017 — Projections descriptives et interventions facultatives

**Statut : Accepted**  
**Date : 2026-10-10**  
**Portée : TP-072 (#13)**

## Décision

Le noyau TP-072 ajoute uniquement une projection déterministe en lecture. La source opérationnelle reste la Task et la WorkSession; les faits métier demeurent append-only selon ADR-0005. Les propositions d'intervention ne sont ni des HistoryEvent, ni des PlanningDecision, ni des mutations implicites. Il n'y a pas de migration et aucune copie persistée du profil comportemental.

L'API GET /api/behavior agrège les faits sans exporter les payloads bruts, notes ou informations de calendrier. Les vues quotidienne et hebdomadaire peuvent afficher ce panneau indépendant, lequel décrit explicitement la situation **actuelle** plutôt qu'une reconstruction historique de la date de revue. Les suites possibles passent par les commandes déjà soumises à choix/confirmation; le GET ne change rien. Aucun appel à un modèle externe.

Les tendances de portée générale exigent au moins trois tâches distinctes observées pour une même catégorie d'événements ou de sessions, ou au moins trois unités terminales avec estimation pour la calibration TP-071. Les séries insuffisantes restent masquées. Les suggestions pour une tâche individuelle sont distinguées de ces tendances de population et peuvent s'appuyer sur un fait isolé explicitement signalé. Les nombres sont des données instrumentées avec couverture **UNVERIFIED**, jamais un taux de comportement réel garanti.

La fréquence d'interruption utilise uniquement les sessions FINISHED et les interruptions explicitement enregistrées; les sessions encore actives et le délai écoulé ne comptent pas comme du temps de travail. La calibration réutilise la logique TP-071 et ne remplace pas les estimations autoritaires. Les motifs sont **déclarés** et non inférés. Les changements d'estimation ou créations de segments prouvent seulement que ces événements ont été enregistrés, pas qu'ils ont causé un démarrage plus rapide ou une meilleure productivité.

## Boucle anti-oubli

Une tâche ouverte/Inbox dont la dernière interaction instrumentée remonte à 14 jours peut refaire surface comme **option** de revue. Lorsque l'instrumentation est absente sur une tâche ancienne, la projection l'indique comme **UNKNOWN**, jamais « inactive ». Le fait de revoir, reporter, préciser une date, abandonner, décomposer ou reprendre demeure un choix explicite de l'utilisateur; ne pas culpabiliser pour une absence de signal.

## Limites assumées

- Les éventuelles décisions de revue ou effets observés restent distincts des suggestions; aucune efficacité ne peut être attribuée automatiquement à une intervention.
- Pas de suivi passif, profil clinique, inférence de cause, scoring psychologique, prédiction ML, stockage analytique ou transfert d'historique brut à l'IA.
- Aucune modification automatique de priorités, protections, Task, segments ou calendrier.
- Les travaux réalisés hors de sessions enregistrées restent inconnus.
- Les projections ne modifient pas l'algorithme de resurgissement de TP-060/TP-061; elles offrent une aide de lecture complémentaire.

Cette décision complète ADR-0005 et ADR-0016 sans élargir leurs contrats persistés.
