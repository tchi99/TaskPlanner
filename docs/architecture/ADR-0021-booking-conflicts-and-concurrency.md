# ADR-0021 — Conflits de disponibilité, décisions de réservation et concurrence (ASTRA-TP022)

**Statut : Accepted**  
**Date : 2026-10-12**  
**WorkItem : ASTRA-TP022 / TP-022 (issue #43)**  
**Décision produit : approuvée par l'utilisateur le 2026-10-12**  
**Références : ADR-0002, 0005, 0006, 0008, 0009, 0010, 0019, 0020.**

## Contexte

ADR-0010 conserve les réservations locales confirmées immuables dans TP-041 et rejette la suppression d'un bloc manuel portant une réservation. Une indisponibilité réelle peut pourtant survenir après la confirmation : refuser de l'enregistrer oblige l'utilisateur à mentir sur sa disponibilité. L'utilisateur a explicitement choisi une **gestion des conflits avec résolution confirmée**, plutôt qu'un blocage systématique des dérogations.

Une simple empreinte d'aperçu ne sérialise pas deux confirmations concurrentes, et les réservations TP-041 ne sont pas actuellement annulables ou déplaçables. Il faut étendre ce contrat **uniquement** dans un flux de résolution explicite.

## Décision

### 1. Déclaration d'indisponibilité et préservation des réservations sont distinctes

Une dérogation ou modification indiquant une **indisponibilité réelle** peut être enregistrée même si une réservation confirmée la chevauche. La modification de disponibilité est conservée immédiatement après confirmation de la déclaration, et le moteur crée un **conflit ouvert** référencé aux deux faits. L'enregistrement de l'indisponibilité **ne modifie pas** la réservation existante et ne prétend pas que le travail a été exécuté.

Le système doit :
- montrer avant application les réservations incompatibles et les conséquences connues;
- proposer explicitement un déplacement, une annulation ou « conserver temporairement le conflit »;
- après application, rendre visibles les conflits non résolus et empêcher de nouvelles réservations sur ces intervalles indisponibles;
- conserver les réservations existantes comme engagements persistés jusqu'à une décision autorisée de résolution; ne pas les compter comme « temps libre » ni les cacher;
- signaler aux vues planification, matin et revue que la réservation demeure en conflit et que le plan doit être réconcilié.

La dérogation n'accorde aucune permission implicite d'écraser une plage **PROTECTED** pour planifier un autre type : cette réaffectation requiert une opération spécifique selon ADR-0020. Les modifications structurelles non causées par une indisponibilité restent soumises au contrôle des conflits et à la prévisualisation. Aucune modification incompatible n'est **silencieuse**.

### 2. Résolutions explicites, auditables et atomiques

Trois décisions utilisateur sont admises :

1. **Déplacer la réservation** : choisir/présenter un autre créneau compatible, prévisualiser conséquences et revalider toutes les contraintes; enregistrer transactionnellement l'annulation de l'ancienne réservation et la création de la nouvelle, ou échouer sans mutation partielle.
2. **Annuler la réservation** : annulation locale explicite, avec historique et raison; la tâche, son estimation, son niveau de protection et son avancement ne changent pas implicitement.
3. **Conserver temporairement le conflit** : ne changer ni l'heure ni l'état de confirmation du bloc; persister ou rendre reconstructible un état de conflit ouvert, exploitable par les revues et la planification ultérieure.

Le changement de disponibilité et la résolution peuvent être deux opérations distinctes, et l'absence d'une solution de remplacement ne doit pas annuler l'enregistrement véridique de l'indisponibilité. Si une opération combinée est proposée, sa portée et son atomicité doivent être définies; aucune « résolution réussie » ne peut être affichée avant validation de la transaction.

**Aucune action automatique sur Google Calendar.** Les réservations TaskPlanner restent locales (ADR-0009/0010). Un événement Google concurrent est un fait externe, non une commande à déplacer.

### 3. Modèle des conflits et états de réservation

Représenter chaque incompatibilité par un diagnostic stable ou un enregistrement de conflit :
- réservation et version concernées;
- règle/exception ou événement à l'origine;
- intervalle et type impactés;
- raison structurée, date de détection, état `OPEN/RESOLVED` ou projection équivalente;
- décision de résolution et références d'audit.

Le statut `CONFIRMED` signifie qu'une réservation a été explicitement acceptée; **il n'est pas synonyme de « sans conflit aujourd'hui »**. La vue peut dériver `CONFLICTED` à partir de l'état courant sans effacer le fait historique de confirmation. L'application ne doit ni ignorer une réservation conflictuelle ni lui attribuer une disponibilité fictive.

Des réservations historiques sans provenance de règles conservent leurs UUID et instants; aucune provenance n'est inventée. Le domaine devra définir les commandes et états de révocation (par exemple `CANCELLED` / `SUPERSEDED`) et conserver une piste de décision dans l'historique append-only d'ADR-0005.

### 4. Empreintes, revalidation et concurrence

Un aperçu est un **calcul non engageant**, jamais une autorisation durable. Son empreinte doit couvrir :
- semaine/période, fuseau, version de l'algorithme;
- séries, révisions, exceptions, blocs manuels et intervalles effectifs pertinents;
- événements Google réellement relus (si requis), réservations locales, charge/segments/échéances et ordre utilisateur;
- option sélectionnée, allocations/transferts et conséquences proposées;
- version partagée de l'état de planification.

Avant chaque confirmation de réservation, annulation, déplacement ou résolution :
1. vérifier l'identité autorisée et la décision explicite;
2. acquérir un verrou/transaction d'écriture adapté au SGBD sur le périmètre local de planification;
3. recharger état et versions, y compris les contraintes externes nécessaires au choix;
4. recalculer la proposition et rejeter les empreintes ou versions obsolètes par `409 Conflict`;
5. valider le non-chevauchement des **nouvelles** réservations entre elles et avec les réservations actives et le temps occupé;
6. appliquer atomiquement les mutations internes et l'historique, ou tout annuler.

Implémentation cible : verrou de ligne/revision de planification sur PostgreSQL, transaction d'écriture sérialisée sur SQLite. Une lecture suivie d'un test Python sans verrou ni contrainte n'est pas suffisante. Les modifications de règles, exceptions, blocs manuels et changements de charge pertinents doivent participer au versionnement commun. Prévoir contrôles de version sur les commandes/API et idempotence de confirmation pour éviter les doubles enregistrements.

Une API Google en lecture seule ne garantit pas l'absence de changement juste après la vérification; cette limite doit rester visible, sans prétendre à un verrou externe.

### 5. Options de planification et protections

La proposition de réaffectation d'une plage `PREFERRED` reste distincte de l'acceptation; elle détaille les transferts de minutes et le coût pour le type donneur. Une plage `PROTECTED` nécessite une dérogation explicite avant un nouveau placement. Les réservations actives incompatibles ne sont jamais déplacées par le simple placement d'une nouvelle tâche.

Une stratégie gloutonne qui échoue ne doit pas être annoncée comme preuve mathématique d'impossibilité : indiquer « aucun placement trouvé selon les règles courantes ».

La disponibilité déclarée inclut les dérogations véridiques; le temps libre planifiable exclut les occupations Google et les réservations actives, ainsi que les zones litigieuses. Un conflit ne crée ni ne libère automatiquement une minute.

### 6. Périmètre de livraison contrôlé

- **TP-022A** : préparer le contrat de version et les entités récurrentes, sans exposer une mutation dangereuse.
- **TP-022B** : autoriser la dérogation réelle avec détection/restitution des conflits et garde-fous sur les réservations existantes; jamais de déplacement automatique.
- **TP-022C** : intégrer le moteur de propositions/confirmation, les empreintes, la sérialisation et les vues de capacité.
- **TP-022R (nouvelle sous-tranche)** : commandes d'annulation et déplacement des réservations locales, suivi des conflits ouverts/résolus, audit et tests de simultanéité; aucune écriture externe.
- **TP-022D** : interface et recette, incluant l'aperçu du conflit, les trois résolutions et le traitement d'un conflit conservé.

La sous-tranche R est explicitement distincte pour préserver les clés TP-022A/B/C/D déjà présentes au roadmap. Les commandes d'annulation/déplacement **ne sont pas autorisées** tant que TP-022R n'a pas été livrée; TP-022B peut seulement enregistrer l'indisponibilité et conserver les réservations en conflit visibles.

## Conséquences et limites

- Cet ADR **étend explicitement** la limite d'immuabilité initiale d'ADR-0010 pour les futures commandes de TP-022R; il ne modifie pas rétrospectivement le comportement de TP-041 déjà livré.
- La suppression automatique des réservations, l'option `force=true`, un conflit dissimulé, une confirmation sans transaction et l'effacement du passé sont exclus.
- Les tests doivent couvrir conflit déclaré/visible, absence de déplacement lors d'une dérogation, conservation temporaire du conflit, annulation et déplacement après confirmation, recalcul du temps libre, concurrence de deux confirmations et aperçu périmé, préservation de l'historique, et échec Google.
- Aucune donnée n'est migrée ni aucun bloc modifié par l'acceptation du présent ADR; la réalisation suit les tranches du roadmap #1.
