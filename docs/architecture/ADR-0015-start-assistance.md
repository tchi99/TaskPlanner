# ADR-0015 — Amorçage non autoritaire et point de reprise

**Statut : Accepted**  
**Date : 2026-10-10**

## Contexte

TP-070 doit distinguer une aide à commencer de la prochaine action calculée
dans TP-011/ADR-0004. Une interruption peut nécessiter une courte note de
reprise, sans introduire les WorkSession de TP-071 ou de nouvelles mesures
comportementales.

## Décision

- \`TaskAggregate.next_action()\` reste la seule source de vérité de la Next Action.
- L'aide d'amorçage est calculée à la demande, côté backend, par règles
  déterministes. Elle expose une suggestion de 5 ou 10 minutes et un catalogue de
  stratégies purement indicatives. Ni la suggestion ni le choix d'une stratégie
  ne créent une tâche, un segment, un bloc ou une session.
- \`resume_points\` contient au plus un marqueur local par tâche : texte court
  (240 caractères maximum), type et identifiant de l'action au moment du
  dépôt, date UTC et révision. Seule une commande utilisateur explicitement
  confirmée peut écrire ou effacer ce marqueur.
- Un marqueur n'est présenté que si son action cible correspond à la Next Action
  courante. Une modification des segments ne peut donc afficher une note sous
  une action erronée. L'API renvoie néanmoins la révision pour permettre de
  remplacer ou d'effacer une note masquée.
- L'écriture exige la cible actuelle et une révision attendue; les requêtes
  périmées sont rejetées. L'effacement conserve la révision, évitant de réutiliser
  le numéro initial. La note est un état courant, pas un fait métier historique.
- Les événements ADR-0005 continuent à décrire exclusivement des changements
  métier sémantiques. Aucun contenu libre de reprise, prompt ou suggestion n'y
  est copié.
- La capture Inbox demeure possible directement depuis la vue d'exécution.
  Capturer ne déclenche aucune modification de la tâche en cours.

## Conséquences

Une migration additive crée \`resume_points\`. Le fonctionnement reste local et
possible sans OpenAI, Google Calendar ou Reclaim. Aucun chronométrage, inférence
comportementale, changement de priorité ou mutation de calendrier n'est ajouté.
Les sessions, calibrations et projections agrégées restent réservées à TP-071/072.
