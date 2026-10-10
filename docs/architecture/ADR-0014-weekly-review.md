# ADR-0014 — Revue hebdomadaire factuelle et décisions explicites (TP-061)

**Statut : Accepted**  
**Date : 2026-10-10**  
**WorkItem : TP-061**

## Décision

- La revue hebdomadaire est une **photographie des tâches actuelles pour une semaine locale commençant lundi**, non une reconstruction historique de l'état d'une semaine révolue.
- La capacité compare hypothétiquement **toutes les unités de travail clarifiées ouvertes** aux blocs manuels de cette semaine, par WorkType avec les inconnues conservées; ce n'est ni une allocation ni un plan validé.
- Afficher les projets actifs, les projets sans prochaine action actuellement exploitable, les tâches protégées, les échéances antérieures à la semaine non closes, l'Inbox non clarifiée et les éléments sans interaction observée depuis 14 jours à la fin de la semaine choisie.
- Une interaction est fondée uniquement sur le dernier événement d'historique réellement enregistré avant la fin de semaine. **Aucun événement observé** est affiché séparément de **aucune interaction récente**. Pas de causalité, diagnostic ou faute inférée.
- L'utilisateur peut confirmer individuellement RECIRCULATE, POSTPONE, REVIEW_LATER, DELEGATE et ABANDON pour une tâche ouverte/Inbox ou un projet actif; POSTPONE et REVIEW_LATER exigent une future date de revue. Enregistrement local SQLite (migration 0007), clé semaine/fuseau/cible et révision attendue pour éviter l'écrasement silencieux.
- Ces choix sont des **intentions de revue consignées**, pas l'exécution métier : une décision de délégation n'affecte pas de ressource, un abandon ne ferme pas une tâche ou un projet, un report ne modifie ni échéance ni calendrier. Les commandes de mutation existantes et leurs confirmations restent les seules autorités. La vue avertit explicitement de cette distinction.

## Hors périmètre

Notifications, inférences comportementales TP-072, mesure des sessions TP-071, Starter Action TP-070, application automatique de décisions, écriture Google Calendar/Reclaim et synchronisation externe. Une révision concurrente SQLite locale n'est pas une garantie de sérialisation multi-utilisateur.
