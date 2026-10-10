# ADR-0007 — Protection hiérarchique et aperçu de glissement (TP-021)

**Statut : Accepted**  
**Date : 2026-10-10**

## Contexte

ADR-0003 reporte les dérogations de protection de segment à TP-021. TP-020
évalue une sélection hypothétique de travail, sans créer d'agenda accepté.
TaskPlanner doit distinguer le travail intangible du travail replanifiable,
exposer les conséquences d'un report et laisser l'utilisateur décider.

## Décisions

- La tâche conserve sa protection `PROTECTED`, `REPLANNABLE` ou `FLEXIBLE`.
  Une commande explicite peut la modifier, avec fait métier append-only.
  Abaisser sa protection requiert un indicateur explicite de confirmation dans
  la commande API et une confirmation visible dans l'interface.
- Un segment possède une surcharge facultative, `NULL` signifiant héritage.
  Sa protection **effective est la plus forte** de la tâche et de la surcharge :
  une dérogation ne peut pas affaiblir implicitement un engagement parent.
  La surcharge peut être supprimée par `null`; aucun segment ne devient
  un agrégat autonome. Abaisser la protection effective d'un segment requiert
  la même confirmation explicite.
- Une simulation de déplacement reçoit deux instants hypothétiques explicites,
  originaux et proposés, tous deux avec fuseau. Ce ne sont **pas** des créneaux
  enregistrés. Le backend détermine la protection effective, le retard mesuré,
  le motif, les conséquences, l'incertitude liée à l'estimation et le fait
  que le nouveau début atteigne l'échéance ou la franchisse. La comparaison
  d'instants est faite en UTC. Sans connaissance de la disponibilité continue,
  aucune prédiction de date de fin n'est faite.
- Lorsqu'une tâche entière est déplacée, un segment ouvert protégé ne peut pas
  être ignoré : la protection effective la plus forte s'applique.
- Les aperçus sont **sans effets** : pas de plan accepté, de changement
  d'échéance, d'affectation hebdomadaire ou de mutation Google Calendar/Reclaim.
  Chaque mouvement effectif nécessitera une confirmation explicite dans une
  tranche ultérieure; TP-021 ne fournit aucune commande d'application.
- Un fait de protection est émis uniquement lorsqu'une valeur change réellement.
  Une modification de protection et son historique sont transactionnels.

## Limites et suites

TP-030 définira propositions, alternatives et décisions de planification.
Les créneaux futurs ne sont ni inférés à partir du statut `IN_PROGRESS` ni
créés en TP-021. La comparaison ne prétend pas modéliser les contraintes
externes, les dépendances ou les conséquences causales non observées.
