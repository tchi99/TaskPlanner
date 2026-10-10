# ADR-0011 — TP-050 : décomposition assistée, sans autorité métier

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-050**

## Contexte

TP-050 introduit un copilote de décomposition après les règles d'agrégat et
d'estimation stabilisées par ADR-0003 et ADR-0004. Les dépendances persistées
entre segments et une hiérarchie Task/Task ne font pas partie du modèle livré.
Les engagements, contraintes et calendriers restent gouvernés par les moteurs
déterministes et par une confirmation utilisateur.

## Décision

- Une requête explicite sur une tâche clarifiée ouverte produit une proposition
  éphémère avec segments amorçables, idées de sous-tâches, fourchettes de durée,
  dépendances indicatives entre suggestions et questions de clarification.
- Les indices de dépendance ne référencent que des éléments antérieurs de la
  même liste. Il ne s'agit pas de relations persistées, ni d'ordonnancement
  imposé sur les tâches existantes.
- Les suggestions sont validées côté Python (tailles, textes, durées,
  références sans cycle ni doublons), puis marquées AI_SUGGESTION / PROPOSED.
  Une durée inconnue reste inconnue; le moteur métier n'en tire aucune charge.
- Aucune génération n'appelle de commande de mutation : pas de création de
  tâche/segment, modification de statut, estimation, priorité, capacité,
  échéance ou calendrier. L'utilisateur peut reprendre un titre dans le
  formulaire de segment existant puis enregistrer avec la commande utilisateur
  normale et son historique.
- Le fournisseur OpenAI est un adaptateur optionnel côté serveur. Un secret
  TASKPLANNER_OPENAI_API_KEY est nécessaire à l'appel; modèle configurable.
  Le titre, jusqu'à 4000 caractères des notes, l'estimation de référence et
  jusqu'à 30 titres de segments ouverts sont transmis uniquement sur demande.
  Aucun contenu de calendrier, historique ni identifiant OAuth n'est transmis.
- Sans configuration, échec explicite (503); réponse fournisseur invalide ou
  indisponible, échec sûr (502). Aucune suggestion factice n'est produite.
  Les tests utilisent des substituts, jamais un service distant.

## Conséquences et limites

- Aucun changement de schéma ou de migration.
- Un brouillon IA peut devenir périmé après modification de la tâche; la
  commande de création de segment demeure autoritaire et distincte.
- La hiérarchie de sous-tâches, les dépendances durables, l'arbitrage assisté
  (TP-051) et l'écriture dans un calendrier sont hors périmètre.
