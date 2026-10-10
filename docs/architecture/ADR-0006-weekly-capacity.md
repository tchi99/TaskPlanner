# ADR-0006 — Capacité hebdomadaire manuelle et évaluation déterministe

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-020**

## Contexte

TP-020 doit représenter les disponibilités par semaine et type de travail et
détecter les plans irréalisables sans attendre TP-040 (Google Calendar) ni
TP-030 (propositions et décisions). ADR-0004 impose une seule source de charge
pour une tâche décomposée.

## Décision

- Une semaine commence le lundi (date locale ISO). Les blocs explicites,
  datés et munis d'un décalage UTC, sont saisis manuellement et persistés dans
  SQLite avec leur décalage original. Leur durée est le temps réel écoulé.
- Les blocs ne peuvent pas se chevaucher, même si leur type de travail diffère.
  Les plages adjacentes sont autorisées. Les types de travail sont des
  références UUID persistées; le type NULL est un compartiment **non classé**
  distinct et non une réserve allouable à plusieurs compartiments.
- Une évaluation est un aperçu **sans effet** pour une sélection explicite
  de tâches clarifiées ouvertes. TP-020 ne crée ni plan accepté, ni assignation
  de tâches à une semaine, ni bloc calendrier externe.
- On agrège les unités ouvertes : segments ouverts quand ils existent,
  sinon tâche non décomposée. Un parent dont tous les segments sont terminaux
  ne génère plus de charge en attente. Les types effectifs héritent des
  règles d'ADR-0004.
- Les minutes connues sont comparées au compartiment correspondant, sans
  emprunter silencieusement aux autres types. Une estimation inconnue reste
  explicitement inconnue. Le verdict est `OVER_CAPACITY` si une charge connue
  dépasse sa capacité, `INCOMPLETE` s'il manque une estimation sans dépassement
  connu, sinon `FEASIBLE`.
- Aucune décision de glissement (TP-021), planification automatique (TP-030)
  ou intégration Google/Reclaim (TP-040) n'est introduite ici.

## Conséquences

- Le backend Python est la seule autorité du verdict, et React en affiche le
  résultat sans recalculer la faisabilité.
- L'utilisateur reste libre de modifier explicitement ses blocs et la
  sélection de simulation, sans mutation tacite des tâches.
- Les estimations restent des efforts prévisionnels, pas des durées observées.
- L'absence de blocs n'est pas présentée comme une disponibilité infinie.
- Le modèle actuel cible un utilisateur local; il n'implémente pas encore de
  contrôle concurrent complexe sur la saisie simultanée de blocs.
