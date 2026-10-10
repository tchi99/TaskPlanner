# ADR-0009 — Google Calendar comme contrainte éphémère de lecture seule (TP-040)

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-040**

## Contexte

ADR-0006 définit les plages de capacité saisies manuellement et les évaluations
déterministes; ADR-0001 impose un adaptateur pour les APIs externes. TP-040
introduit une lecture du calendrier sans créer de tâches, sans accepter de
proposition ni réserver de créneau (TP-041).

## Décision

- L'intégration est facultative, déclenchée explicitement à la demande, et
  hébergée dans le backend. Elle utilise l'API Google Calendar events.list
  avec singleEvents=true, un ou plusieurs calendriers configurés et un
  accès OAuth en lecture seule fourni hors de TaskPlanner. Aucun flux de
  consentement OAuth ni stockage de tokens n'est introduit à cette tranche.
- Les événements occupés (opaque ou transparence absente) sont des faits
  externes éphémères, jamais des Task, TaskSegment ou AvailabilityBlock.
  Les événements transparents/annulés, les localisations de travail et les
  invitations explicitement refusées sont ignorés. Les événements toute la
  journée bloquent leur plage locale et la fin est exclusive.
- Pour chaque bloc manuel, on intersecte les événements et on calcule l'union
  des occupations en UTC (pas de double comptage de calendriers superposés).
  On arrondit conservativement les secondes occupées à la minute supérieure.
  Les minutes restantes sont présentées par type sans transférer du temps
  entre types. Aucune capacité n'est inventée hors des blocs manuels.
- Le résultat est une projection distincte des évaluations et propositions
  TP-020/TP-030. Ces API restent manuelles et ne prétendent pas intégrer
  les engagements Google. La planification de créneaux et l'acceptation d'un
  choix relèvent de TP-041 ou d'une décision ultérieure.
- Échec d'authentification, réseau ou réponse invalide : signal explicite
  d'indisponibilité. Aucun fallback « calendrier vide » qui surestimerait la
  capacité. Rien n'est persisté; aucun secret ni donnée privée en journal.

## Conséquences

- La lecture reste testable via un port/faux lecteur sans credentials et ne
  change pas le schéma SQLite.
- Le rapprochement calendar+capacité est informatif, non un plan engagé.
- Une connexion OAuth interactive, l'assimilation d'événements à des tâches,
  la détection de disponibilité hors des blocs manuels et toute écriture du
  calendrier demanderaient une tranche/autorisation distincte.
