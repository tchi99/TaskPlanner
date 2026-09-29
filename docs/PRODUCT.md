# TaskPlanner — principes produit

## Problème à résoudre

Les tâches arrivent de plusieurs sources et restent facilement en tête plutôt que dans un système fiable. Les projets trop gros créent de la friction d'amorçage; un plan trop ambitieux crée ensuite de la procrastination, des retards et une impression de surcharge.

TaskPlanner doit rendre la situation concrète :

- ce qui existe;
- ce qui est réellement faisable;
- ce qui ne doit pas dérailler;
- ce qui peut glisser;
- quels compromis sont disponibles;
- quelle est la prochaine unité de travail;
- comment réduire la friction pour commencer ou reprendre.

Le produit vise à **réduire la charge cognitive entre l'intention et l'action**, sans prendre les décisions importantes à la place de l'utilisateur.

## Modèle mental

Le cœur métier part du modèle suivant :

```text
Inbox
  ↓
Project
  ↓
Task
  ↓
TaskSegment
  ↓
PlanningProposal
  ↓
User decision
```

Autour de ce cœur, les capacités futures complètent la boucle :

```text
capture
→ clarification
→ décomposition
→ capacité
→ arbitrage
→ proposition
→ amorçage
→ exécution / reprise
→ observation
→ apprentissage
→ adaptation
```

Les catégories ou blocs de temps sont des contraintes/capacités, pas des tâches.

## Politique de décision

TaskPlanner ne doit pas « prendre le contrôle » du calendrier.

Quand une surcharge ou un conflit existe, l'application présente des options et leurs conséquences. L'utilisateur choisit l'action à appliquer.

Les mutations significatives doivent donc distinguer :

1. le fait observé;
2. la projection/statistique lorsqu'elle existe;
3. la suggestion ou proposition;
4. la décision acceptée;
5. l'état appliqué.

Une observation comportementale ou une suggestion IA n'est jamais une preuve de causalité ni une décision utilisateur.

## Soutien aux fonctions exécutives

TaskPlanner doit explicitement aider à compenser certaines frictions liées à l'organisation et à l'exécution du travail :

- externaliser rapidement ce qui autrement resterait en mémoire;
- réduire le nombre de choix visibles au moment d'agir;
- décomposer les gros travaux en unités amorçables;
- faire ressortir ce qui ne doit pas dérailler;
- tenir compte de la capacité réelle;
- proposer une prochaine action claire;
- aider à amorcer une action lorsqu'elle reste difficile à commencer;
- rendre une interruption récupérable grâce à un point de reprise;
- faire remonter les éléments qui dérivent ou disparaissent du champ d'attention;
- apprendre de tendances observées sans diagnostiquer ni imposer une conclusion.

La matrice complète, les limites du produit et les extensions futures sont documentées dans [EXECUTIVE_FUNCTION_SUPPORT.md](./EXECUTIVE_FUNCTION_SUPPORT.md).

## Travail protégé et travail flexible

La classification de base est :

- **PROTECTED** — ne doit pas dérailler sans décision explicite;
- **REPLANNABLE** — important, mais peut être déplacé avec un compromis;
- **FLEXIBLE** — peut glisser avec un coût limité.

Le domaine possède déjà `ProtectionLevel`; TP-021 doit stabiliser les règles avancées de glissement, d'explication et de conséquences.

## Amorçage

La prochaine action déterministe et l'aide à l'amorçage sont deux concepts distincts :

- **Next Action** : quelle unité vient logiquement ensuite;
- **Starter Action** : quelle micro-action peut aider à commencer maintenant.

Une Starter Action est une suggestion temporaire; elle ne devient pas automatiquement une Task ou un TaskSegment.

Cette extension est suivie par **#11 — TP-070**.

## Exécution, interruption et perception du temps

Le temps écoulé entre un statut « commencé » et un statut « terminé » ne doit pas être interprété comme du temps travaillé.

Une future notion de `WorkSession` doit permettre d'observer explicitement les périodes de travail actives, les interruptions et la reprise, afin de comparer les estimations aux observations réelles sans transformer ces données en jugement.

Cette extension est suivie par **#12 — TP-071**.

## Historique et apprentissage

ADR-0005 conserve des faits métier structurés afin que TaskPlanner puisse ultérieurement produire des projections descriptives.

La chaîne cible reste :

```text
faits métier
→ historique append-only
→ projections/statistiques déterministes
→ hypothèse ou suggestion IA
→ options
→ décision utilisateur
→ résultat observé
```

Exemples futurs :

- tâches d'un WorkType souvent reportées;
- écarts récurrents entre estimation et temps actif;
- tâches qui démarrent plus facilement lorsqu'elles sont segmentées;
- interruptions fréquentes;
- éléments ouverts qui dérivent sans interaction récente.

Les tendances doivent exposer l'incertitude et ne jamais être présentées comme un diagnostic ou une causalité démontrée.

Cette extension est suivie par **#13 — TP-072**.

## Boucle anti-oubli

Aucune tâche ouverte ne doit pouvoir disparaître indéfiniment du système simplement parce qu'elle n'est plus visible.

Les revues quotidiennes et hebdomadaires doivent pouvoir refaire émerger les éléments sans interaction récente et proposer des choix explicites : remettre en circulation, reporter, revoir plus tard, annuler/abandonner ou utiliser un futur état « someday ».

Une absence d'interaction est un fait; l'interface ne doit pas la transformer en formulation culpabilisante.

## IA

L'IA peut réduire la friction cognitive en aidant à :

- reformuler une tâche;
- proposer une première action;
- proposer une Starter Action;
- décomposer un projet;
- estimer une fourchette de durée;
- proposer des dépendances;
- présenter des options d'arbitrage;
- expliquer des tendances issues de projections déterministes;
- suggérer des interventions possibles.

L'IA ne doit pas :

- modifier automatiquement le calendrier;
- inventer une priorité métier;
- masquer une contrainte;
- remplacer les règles déterministes de capacité;
- transformer une corrélation en causalité;
- diagnostiquer un état psychologique ou médical;
- faire d'une suggestion un engagement sans confirmation utilisateur.

## Limites du produit

TaskPlanner n'a pas vocation à devenir une application de santé ou de surveillance comportementale.

Restent hors du noyau produit :

- diagnostic ou traitement médical;
- sommeil;
- alimentation et besoins corporels;
- caféine ou médication;
- sensibilité au rejet;
- régulation émotionnelle clinique;
- addiction ou comportements compulsifs;
- surveillance clavier/souris;
- blocage coercitif d'applications;
- plateforme sociale de body doubling.

Le body doubling peut être proposé comme **stratégie externe d'amorçage**, mais TaskPlanner n'a pas à construire la plateforme elle-même.

## Références

- Roadmap maître : #1
- TP-011 — Projets, tâches et segments : #6
- ADR-0004 — unités de travail et projections
- ADR-0005 — historique comportemental et faits métier
- TP-070 — amorçage et reprise : #11
- TP-071 — sessions de travail et calibration : #12
- TP-072 — projections comportementales et interventions adaptatives : #13
