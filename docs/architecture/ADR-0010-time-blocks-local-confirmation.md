# ADR-0010 — Propositions de créneaux et confirmation locale (TP-041)

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-041**

## Contexte

TP-041 doit proposer des créneaux de travail dans les blocs manuels (ADR-0006), tout en respectant les événements occupés Google Calendar (ADR-0009), les unités ouvertes (ADR-0004), les échéances et les réservations déjà confirmées. L'authentification Google existante ne garantit que la lecture; ADR-0009 ne permet pas d'ajouter des écritures externes implicitement.

## Décision

- Une sélection explicite et ordonnée de tâches clarifiées ouvertes produit un aperçu **éphémère** déterministe, par tâche ou segment ouvert, avec créneaux, minutes restantes et raisons de non-placement.
- Chaque segment ouvert constitue l'unité de charge; les segments clos et l'estimation du parent décomposé ne sont pas replanifiés. Les estimations inconnues ne sont pas converties en zéro.
- Seuls les blocs manuels du même type de travail peuvent fournir du temps; le type non classé reste distinct. Les événements occupés Google et les réservations locales confirmées sont soustraits en UTC avec arrondi conservateur à la minute. Les échéances bornent la fin des nouveaux créneaux.
- Les unités peuvent être fragmentées entre plages libres; l'ordre explicitement donné par l'utilisateur est conservé. Une proposition partielle peut être montrée, mais pas confirmée. Aucun arbitrage de priorité ou déplacement d'engagement existant n'est automatisé.
- L'aperçu expose une empreinte des données de planification. La commande de confirmation exige une acceptation explicite et **recharge** les événements Google, les blocs manuels, les unités et les réservations. Toute divergence d'empreinte répond par un conflit; les propositions incomplètes sont refusées.
- Une confirmation enregistre transactionnellement des **réservations locales** dans SQLite (migration 0005), distinctes des blocs de disponibilité et des événements Google. Aucun appel d'écriture Google Calendar, création de tâche, mutation de statut ou modification de priorité. Les réservations existantes ne sont jamais déplacées par les nouvelles propositions.
- L'indisponibilité ou l'absence de configuration Google empêche les propositions et confirmations, sans inventer un calendrier libre. Les créneaux enregistrés localement ne sont **pas synchronisés** avec Google Calendar. Il faut une autorisation produit et OAuth distinctes pour toute écriture future.

## Limites

- Les réservations locales sont initialement immuables dans TP-041; la modification/annulation et la synchronisation Google sont des tranches ultérieures. Supprimer un bloc manuel porteur d'une réservation est refusé.
- Une nouvelle modification externe après confirmation peut créer un conflit ultérieur : aucune garantie de verrouillage de Google Calendar n'est possible avec une API en lecture seule.
- La sérialisation forte des confirmations simultanées n'est pas traitée au-delà de la transaction SQLite locale initiale; un protocole de concurrence multi-utilisateur demandera un ADR distinct.
