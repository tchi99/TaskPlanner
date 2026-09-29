# Soutien aux fonctions exécutives — vision produit

## Pourquoi ce document

TaskPlanner n'est pas seulement un gestionnaire de tâches. Le produit vise à réduire la charge cognitive entre l'intention et l'action :

```text
beaucoup de choses à retenir
→ difficulté à choisir
→ tâche trop grosse ou floue
→ difficulté à amorcer
→ report
→ urgence
→ exécution sous pression
→ anxiété / fatigue
```

Le produit doit compenser une partie de cette friction par la structure, la visibilité, la réduction du nombre de décisions et des interventions choisies par l'utilisateur.

Ce document décrit :
- les difficultés que TaskPlanner doit explicitement aider à compenser;
- les mécanismes déjà prévus;
- les manques identifiés;
- les limites volontaires du produit;
- les extensions futures #11, #12 et #13.

Il ne constitue pas un modèle clinique et TaskPlanner ne doit pas diagnostiquer une condition médicale ou psychologique.

---

## Principes directeurs

1. **Externaliser plutôt que retenir.** Une information capturée dans un système fiable ne doit plus dépendre de la mémoire de travail de l'utilisateur.
2. **Réduire le choix au moment d'agir.** Les écrans d'exécution doivent présenter peu d'options utiles plutôt qu'un backlog complet.
3. **Distinguer priorité et amorçage.** Savoir ce qui est prioritaire ne garantit pas qu'il soit facile de commencer.
4. **Petites unités concrètes.** Les projets doivent pouvoir devenir des tâches puis des segments réellement amorçables.
5. **Capacité réelle avant ambition.** Un plan irréalisable augmente la friction et les reports.
6. **Proposer sans imposer.** Les arbitrages importants restent des décisions utilisateur.
7. **Rendre l'interruption récupérable.** Reprendre une tâche ne devrait pas exiger de reconstruire tout son contexte mental.
8. **Observer sans juger.** L'historique sert à décrire des tendances, pas à attribuer une cause ou un diagnostic.
9. **Apprendre sans devenir autoritaire.** Les observations futures peuvent alimenter des suggestions; elles ne deviennent pas des règles métier implicites.
10. **Prévenir la disparition silencieuse.** Une tâche ouverte ne doit pas pouvoir rester indéfiniment hors du champ de revue.

---

## Modèle fonctionnel cible

```text
CAPTURE
Tout sort de la tête
        ↓
CLARIFICATION
Qu'est-ce réellement?
        ↓
DÉCOMPOSITION
Quelle unité est assez petite?
        ↓
CAPACITÉ
Qu'est-ce qui rentre réellement?
        ↓
ARBITRAGE
Qu'est-ce qui ne doit pas dérailler?
        ↓
PROPOSITION
Voici quelques options, l'utilisateur choisit
        ↓
AMORÇAGE
Comment commencer maintenant?
        ↓
EXÉCUTION
Travail réel, interruption, reprise
        ↓
OBSERVATION
Que s'est-il réellement passé?
        ↓
APPRENTISSAGE
Quelles tendances se répètent?
        ↓
ADAPTATION
Quelle intervention pourrait rendre le prochain plan plus réaliste?
```

Les étapes `AMORÇAGE`, `EXÉCUTION` et `APPRENTISSAGE` complètent le roadmap initial sans modifier le périmètre de TP-011C/TP-011D.

---

## Matrice des besoins

| Enjeu | Couverture cible | Mécanisme TaskPlanner | Décision produit |
| --- | --- | --- | --- |
| Difficulté à commencer | PARTIEL → À RENFORCER | Next Action, segments, TP-050 | Ajouter Starter Action et mode amorçage dans #11 |
| Procrastination / reports | PARTIEL → À RENFORCER | protection, propositions, revues, historique | Détecter les reports répétés via #13 sans les interpréter comme une cause certaine |
| Motivation dépendante de l'intérêt / urgence | PARTIEL | échéances, WorkType, protection | Utiliser contexte/WorkType et suggestions; ne pas créer un score psychologique |
| Trop de choses en tête | COUVERT | Inbox TP-010 | Maintenir une capture à très faible friction |
| Mémoire de travail fragile | PARTIEL → À RENFORCER | Inbox, Next Action, segments | Ajouter point de reprise dans #11 |
| Difficulté à prioriser | COUVERT CIBLE | TP-021, TP-030, TP-031 | Présenter peu d'options avec conséquences, décision utilisateur |
| Organisation / séquençage | COUVERT CIBLE | Project → Task → TaskSegment | TP-011C/TP-011D restent la fondation |
| Perception du temps / estimation | PARTIEL → À RENFORCER | estimation, capacité | Ajouter WorkSession et calibration dans #12 |
| Hyperfocus / difficulté à sortir d'une tâche | NON COUVERT → OPTIONNEL | futur contexte calendrier/session | #12 peut proposer pause/réévaluation, jamais imposer l'arrêt |
| Idées qui interrompent le travail | PARTIEL | Inbox | La capture rapide doit rester accessible depuis les vues d'exécution |
| Oubli de ce qui n'est plus visible | PARTIEL → À RENFORCER | revues TP-031/060/061 | Ajouter boucle anti-oubli/resurfacing dans #13 |
| Interruption puis perte du fil | NON COUVERT → À AJOUTER | — | Point de reprise #11 + WorkSession #12 |
| Besoin de stimulation | HORS NOYAU / CONTEXTE POSSIBLE | WorkType indirectement | Peut alimenter une suggestion; pas un moteur de stimulation |
| Body doubling | HORS NOYAU / STRATÉGIE POSSIBLE | — | Peut être proposé comme stratégie externe dans #11/#13; ne pas construire une plateforme dédiée |
| Oublier de manger / besoins corporels | HORS PÉRIMÈTRE | — | Ne pas transformer TaskPlanner en application de santé |
| Sommeil | HORS PÉRIMÈTRE | — | Hors produit |
| Caféine | HORS PÉRIMÈTRE | — | Hors produit |
| Anxiété liée à l'accumulation / retard | COUVERT INDIRECTEMENT | capture, capacité, protection, planification, revue | Réduire les générateurs de surcharge sans prétendre traiter l'anxiété |
| Sensibilité au rejet | HORS PÉRIMÈTRE | — | Hors produit |
| Régulation émotionnelle | HORS NOYAU | contexte éventuel déclaré par l'utilisateur | Pas de diagnostic ni de déduction psychologique |
| Distractions / comportements compulsifs | HORS NOYAU | planification/focus indirectement | Pas de surveillance de l'appareil ni de blocage coercitif |

---

## 1. Capture et externalisation

### Intention

L'utilisateur ne devrait pas avoir à conserver une idée, une obligation ou une tâche en mémoire en attendant de trouver le bon endroit où la classer.

### Règles produit

- un titre doit suffire pour capturer;
- la clarification peut venir plus tard;
- la capture doit rester disponible depuis les écrans de travail, afin qu'une nouvelle idée puisse être déposée sans changement de contexte;
- capturer une idée ne doit pas automatiquement la rendre prioritaire;
- les éléments Inbox doivent revenir dans une boucle de clarification.

TP-010 fournit le socle initial.

---

## 2. Réduction du choix et priorisation

TaskPlanner ne doit pas utiliser un grand backlog comme écran principal d'exécution.

Les vues quotidiennes doivent privilégier :
- ce qui ne doit pas dérailler;
- ce qui est faisable dans la capacité restante;
- une petite quantité d'options pertinentes;
- les conséquences d'un report;
- les décisions qui nécessitent réellement l'utilisateur.

TP-021, TP-030 et TP-031 portent cette responsabilité.

---

## 3. Next Action vs Starter Action

### Next Action

La `Next Action` est une projection déterministe du domaine définie par TP-011 :
- clarifier une tâche Inbox;
- travailler sur la tâche;
- travailler sur le premier segment pertinent;
- revoir la clôture.

Elle répond à :

> **Quelle unité de travail vient logiquement ensuite?**

### Starter Action

Une `Starter Action` est une suggestion temporaire et non autoritaire qui répond à :

> **Quelle est la plus petite action concrète qui peut me faire commencer maintenant?**

Exemple :

```text
Next Action
Analyser les données du rapport

Starter Action
Ouvrir le classeur, afficher l'onglet Données et y rester 10 minutes.
```

Une Starter Action :
- ne remplace pas la Next Action;
- ne devient pas automatiquement une Task ou un TaskSegment;
- peut être générée par règle ou IA;
- n'effectue aucune mutation métier significative sans confirmation;
- peut proposer un engagement court plutôt qu'un objectif de complétion.

Voir #11 — TP-070.

---

## 4. Interruption et point de reprise

Lorsqu'un travail est interrompu, TaskPlanner doit pouvoir conserver un marqueur minimal du type :

> **Reprendre ici :** vérifier le mapping des tags PLC avec le tableau Excel.

Le point de reprise :
- reste court;
- est explicitement fourni ou confirmé par l'utilisateur;
- n'est pas une note complète de projet;
- réapparaît avec la prochaine action;
- peut être associé à une interruption/session lorsqu'elles existent;
- ne change pas automatiquement la priorité.

Voir #11 et #12.

---

## 5. WorkSession et perception du temps

Les événements de statut ne constituent pas une mesure de temps travaillé.

Une future `WorkSession` doit observer explicitement :
- début;
- fin;
- interruption;
- cible Task/Segment;
- durée active;
- motif structuré facultatif.

Les données permettront notamment de comparer :
- estimation initiale;
- estimation révisée;
- temps actif observé;
- nombre et durée des sessions;
- interruptions.

Les statistiques doivent rester descriptives :
- une durée élevée ne prouve pas une difficulté d'attention;
- une hausse d'estimation ne prouve pas une sous-estimation initiale;
- une interruption ne révèle pas automatiquement sa cause.

Voir #12 — TP-071.

---

## 6. Sortie de tâche et hyperfocus

TaskPlanner peut aider sans devenir coercitif.

Exemples de garde-fous optionnels :
- « cette session dépasse le bloc prévu »;
- « un engagement protégé commence bientôt »;
- « veux-tu continuer, faire une pause ou replanifier? ».

Le système ne doit pas :
- interrompre de force;
- verrouiller l'application;
- décider qu'une durée de travail est pathologique;
- déduire un état mental.

---

## 7. Historique comportemental et apprentissage

ADR-0005 établit déjà la séparation :

```text
faits
→ historique
→ projections/statistiques
→ hypothèse/suggestion
→ décision utilisateur
```

Les futures projections peuvent décrire, avec suffisamment de données :
- WorkType fréquemment repoussé;
- écart estimation / temps actif;
- durée typique des sessions;
- fréquence des interruptions;
- effet observable de la segmentation;
- périodes/contextes où certains travaux sont plus souvent commencés;
- motifs déclarés de report;
- éléments qui dérivent sans interaction.

Les résultats doivent toujours préciser les limites des données et éviter les conclusions causales.

Voir #13 — TP-072.

---

## 8. Boucle anti-oubli / resurfacing

Une tâche ouverte ne doit pas disparaître indéfiniment simplement parce qu'elle n'est plus visible.

Les revues quotidienne et hebdomadaire doivent pouvoir faire remonter :
- tâches ouvertes sans interaction récente;
- projets actifs sans prochaine action exploitable;
- tâches reportées plusieurs fois;
- Inbox non clarifiée;
- engagements proches d'une échéance;
- éléments explicitement mis en attente lorsqu'une date de revue arrive.

Les options possibles incluent :
- remettre en circulation;
- reporter explicitement;
- définir une prochaine date de revue;
- convertir en « someday » si ce concept est introduit;
- abandonner/annuler.

L'interface doit éviter les formulations culpabilisantes. Une absence d'interaction est un fait, pas un échec.

Voir TP-031, TP-060, TP-061 et #13.

---

## 9. Contexte, énergie et stimulation

`WorkType` doit rester un concept métier configurable pour catégoriser le type de travail.

Des attributs futurs de contexte peuvent aider à formuler des propositions, mais TaskPlanner ne doit pas inventer un état interne de l'utilisateur.

Exemples de données déclarées ou observables possibles :
- type de travail;
- créneau disponible;
- durée disponible;
- préférence de contexte;
- motif déclaré `LOW_ENERGY`;
- interruption ou blocage déclaré.

Ces données peuvent influencer les options proposées, jamais produire un diagnostic.

---

## 10. Body doubling

TaskPlanner ne doit pas construire une plateforme sociale ou vidéo de body doubling.

Le body doubling peut exister comme **stratégie d'amorçage externe** proposée lorsque pertinent :

```text
J'ai de la difficulté à démarrer
→ commencer 10 min
→ décomposer davantage
→ faire une session accompagnée
```

L'utilisateur choisit. L'option peut ouvrir ou rappeler un outil externe si une intégration est un jour approuvée.

---

## 11. Limites explicites du produit

TaskPlanner ne cherche pas à traiter ou gérer directement :
- diagnostic TDAH ou autre diagnostic;
- traitement médical;
- sommeil;
- alimentation et besoins corporels;
- caféine ou médication;
- sensibilité au rejet;
- régulation émotionnelle clinique;
- addiction ou comportements compulsifs;
- surveillance clavier/souris;
- blocage coercitif d'applications;
- interprétation automatique de l'état mental.

Le produit peut seulement réduire certaines sources de charge cognitive liées à la gestion et à l'exécution du travail.

---

## 12. Ordre de livraison

Les besoins décrits ici **ne modifient pas la séquence actuelle de TP-011**.

Ordre conservé :
1. terminer TP-011C;
2. terminer TP-011D;
3. livrer capacité/protection/planification/calendrier/IA/revues selon le roadmap;
4. introduire ensuite les extensions :
   - #11 / TP-070 — amorçage et reprise;
   - #12 / TP-071 — sessions de travail et calibration;
   - #13 / TP-072 — projections comportementales et interventions adaptatives.

Certaines capacités des issues #11–#13 peuvent être déplacées plus tôt ultérieurement si une analyse d'architecture le justifie, mais aucune ne doit être injectée opportunément dans TP-011C ou TP-011D sans décision de roadmap.

---

## Références

- Roadmap maître : #1
- TP-011 — Projets, tâches et segments : #6
- ADR-0004 — unités de travail et projections
- ADR-0005 — historique comportemental et faits métier
- TP-070 — amorçage et reprise : #11
- TP-071 — sessions de travail et calibration : #12
- TP-072 — projections comportementales et interventions adaptatives : #13
