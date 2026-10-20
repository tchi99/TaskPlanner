# ADR-0026 — Grille hebdomadaire unique, cibles éditables et manipulations directes (ASTRA-TP027)

**Statut : Accepted — décisions D1, D2 et D3 approuvées explicitement par l'utilisateur le 2026-10-20**  
**Date : 2026-10-20**  
**WorkItem : ASTRA-TP027 (gate architecture) / TP-027 (issue [#76](https://github.com/tchi99/TaskPlanner/issues/76))**  
**Roadmap maître : [#1](https://github.com/tchi99/TaskPlanner/issues/1)**  
**Analyse en lecture seule : `main@60c57ae1dfc299c9c3f7526a245396125d27f42b`**  
**Références :** AGENTS.md; ADR-0002, ADR-0005, ADR-0009, ADR-0010, ADR-0020, ADR-0021, ADR-0022, ADR-0023, ADR-0024, ADR-0025.  
**Portée :** décision d'architecture **documentaire**; aucun code, schéma, migration, réservation, reset de base, Google Calendar write ou déploiement n'est autorisé par l'ADR lui-même. La gate se clôt après validation et fusion documentaires puis réconciliation du roadmap. TP-080D demeure en standby.

## 1. Problème et portée

Les travaux TP-025 (permissions superposables et priorités contextuelles) et TP-026 (modèle neuf unifié, premier démarrage) sont livrés. L'utilisateur trouve encore peu intuitives les représentations parallèles de l'horaire (cartes par jour, formulaire « + Nouvelle plage », grille 24 h comprimée) et demande **un seul éditeur hebdomadaire** où créer, déplacer et redimensionner les plages directement, y compris en superposition.

Le rapport ASTRA-TP027 sur le `main` cité ci-dessus établit notamment :
- `weekly-schedule` couvre déjà le brouillon/aperçu/confirmation des **enveloppes physiques**, mais son aperçu et son empreinte doivent rendre compte des permissions affectées;
- `eligibility-edits` révise une série entière : cibler seulement un mardi dans une série mardi/jeudi, supplanter des révisions futures et gérer les exceptions futures exigent un complément de contrat;
- les exceptions de permission `REMOVE/MOVE` existent dans domaine/persistance, mais ne disposent pas d'un parcours HTTP d'édition d'occurrence; les exceptions futures actives peuvent bloquer la révision de série via `UNRESOLVED_ELIGIBILITY_EXCEPTIONS`;
- la grille actuelle dessine des **fragments de projection** et non des cibles d'édition fiables; un fragment peut n'être qu'une partie d'une permission ou agréger plusieurs sources;
- les réservations devenues entièrement hors enveloppe peuvent manquer des barres d'occupation; le panneau contextuel peut sélectionner une révision future et reprendre à tort le fuseau d'affichage;
- la recette E2E existante est principalement interceptée (`page.route`), sans attester de bout en bout navigateur → FastAPI → base réelle.

**Décision :** conserver le moteur Python, les modèles de permissions/enveloppes et les commandes spécialisées; étendre uniquement leurs garanties manquantes, puis remplacer les éditeurs parallèles par une seule grille. Ne pas stocker un deuxième modèle de grille ni introduire une bibliothèque de calendrier comme autorité métier.

## 2. Décisions produit approuvées

### D1 — Modification récurrente ciblée par jours et supersession du futur

Tout geste sur une permission récurrente doit permettre de choisir précisément **le ou les jours touchés** et une **date d'effet future**. À compter de cette date, la commande **supplante les configurations et révisions futures** pour ces jours; elle conserve intégralement la chronologie des jours non sélectionnés, les occurrences passées et l'audit.

Une série mardi/jeudi dont l'utilisateur modifie le mardi **ne modifie pas le jeudi**. Une révision programmée plus tard ne peut pas faire réapparaître une permission supprimée ou déplacée. La sauvegarde d'une transformation mardi → mercredi est **atomique** : ni retrait seul ni ajout seul en cas d'échec. Réutiliser les principes de division, filiation, versions et révisions immuables d'ADR-0022, adaptés aux `EligibilitySeries`. Prendre en charge deux sauvegardes à la même date d'effet.

Le choix d'une portée est explicite dans l'aperçu : **cette occurrence datée**, **les occurrences futures des jours ciblés**, et **toute la série uniquement si le backend peut inventorier et garantir ses conséquences**. « Toute la série » n'est pas un raccourci qui écrase des jours non choisis sans avertissement. L'édition récurrente ne commence pas avant le lendemain civil dans le fuseau IANA de la règle; une modification d'aujourd'hui passe par une exception datée.

Inventorier les exceptions de permission futures touchées; proposer de **conserver, remplacer ou désactiver** chacune des exceptions affectées selon l'effet voulu, avec décisions explicites. Une occurrence `REMOVE/MOVE` doit avoir un chemin applicatif/HTTP dédié, sans effet sur les permissions voisines. Lorsqu'une exception possède une clé série/date d'origine immuable, conserver sa trace et, si nécessaire, désactiver l'ancienne par révision puis créer un successeur lié par audit, **dans la même transaction**. Un `REMOVE` demeure le retrait d'une permission; il ne devient jamais un ajout ni une suppression de capacité physique.

### D2 — Réduction d'enveloppe et incohérence structurelle

**Refuser une réduction ou transformation d'enveloppe qui crée une nouvelle permission hors capacité physique du parent**, avec diagnostic et liste des permissions à ajuster; ne jamais tronquer ou déplacer automatiquement ces permissions. Une validation structurelle interparent ne peut pas être contournée par simple reconnaissance de conflit.

**Distinguer** ce refus d'une **indisponibilité physique datée** : celle-ci peut être déclarée avec reconnaissance explicite des conflits de réservations conformément à ADR-0021, sans annuler ou déplacer les réservations confirmées. Une occupation locale `CONFIRMED` devenue incompatible reste visible en conflit même si elle se trouve entièrement hors de l'enveloppe courante.

L'enveloppe est unique et physique par parent, sans chevauchement entre parents; plusieurs permissions peuvent être admises simultanément **dans le même parent** sans compter deux fois la capacité. `WorkType.scope_id` demeure direct et immuable (ADR-0025). Les permissions et occupations ne sont pas interchangeables.

### D3 — Orientation, navigation et précision

Grille **jours en colonnes / heures verticales**, cadrage initial **06:00–20:00 paramétrable**, avec accès et zoom jusqu'à la **journée complète (00:00–24:00)**. Mobile : **un jour à la fois** avec navigation. Toujours offrir un bouton persistant `+ Nouvelle plage`, la création sur créneau vide et les actions équivalentes via panneau, clavier, toucher et lecteur d'écran.

Le geste utilise un **snap par défaut de 15 minutes**, configurable, qui n'arrondit **jamais** une plage préexistante enregistrée à la minute; le panneau permet une saisie exacte, y compris une borne finale `24:00`. Le rendu des jours de DST 23/25 heures exploite les repères, instants et décalages déterminés par Python (heures inexistantes/dupliquées désambiguïsées), **pas** une conversion uniforme pixels → 1 440 minutes. Le fuseau d'une série est conservé sauf demande explicite de changement; il ne doit pas être remplacé par le fuseau d'affichage.

## 3. Contrat d'édition et frontières d'autorité

Flux commun des interactions, sans écriture métier au relâchement du pointeur :

```text
Geste grille / clavier / panneau → intention + brouillon React local
  → commande spécialisée existante ou étendue (enveloppe / permission / exception)
  → projection et validation Python → aperçu avant/après, sources, impacts, diagnostics
  → visualisation du brouillon et des conflits → confirmation explicite
  → revalidation des versions/empreintes sous verrou → transaction + audit + reçu
  → mise à jour de la grille, ou 409 avec brouillon conservé
```

- Le contexte commun porte **parent sélectionné, semaine affichée, fuseau de lecture et empreinte de projection**. La **date d'effet** est distincte de la semaine affichée : une modification future ne doit pas paraître applicable aujourd'hui.
- Distinguer dans la projection les **fragments physiques** (minutes, choix admissibles, occupations, provenance et diagnostics) et les **objets éditables** (permission entière, série/identité, version, révision applicable à la date, bornes complètes, occurrence originale et exception éventuelle). Une barre fragmentée ne devient jamais plusieurs commandes. Une agrégation visuelle ne perd jamais ses sources.
- React dessine les coordonnées, le fantôme de déplacement, le snap et les couches; **seul Python** tranche capacité, collision, priorité, récurrence, conflits et validité DST. Tant que le preview n'est pas revenu, la validité métier du fantôme est **indéterminée**.
- Le panneau ouvre la **révision applicable à la date sélectionnée**, jamais simplement la dernière enregistrée, et conserve le **fuseau source** de la série. Les fonctions TP-026 de premier démarrage (parent, sous-catégorie, enveloppe, première permission) sont réutilisées sur une grille vide.
- La même grille propose les couches **Configuration**, **Occupation réelle vérifiée** et **Plan proposé**, avec styles distincts pour enveloppe, permissions, exceptions, événements occupés Google, réservations confirmées, conflits et propositions. Trois permissions simultanées sont lisibles sans capacité additive. Une lecture Google inconnue n'est jamais présentée « libre ».
- Réutiliser en priorité `weekly-schedule` pour l'enveloppe, `eligibility-edits` pour les séries de permissions et `exceptions` pour les exceptions physiques; compléter leurs contrats sans créer une API générique parallèle. Exposer les commandes de `EligibilityException` lorsque manquantes.
- Les previews d'enveloppe et d'exception physique doivent fournir les diagnostics de permissions et conséquences pertinentes, et leur empreinte doit inclure **séries, révisions et exceptions de permission concernées**. Les vues d'occupation sont indépendantes de la présence d'un fragment d'enveloppe actuel; elles montrent les engagements extérieurs encore confirmés.
- `409` : conserver le brouillon, marquer l'aperçu périmé, relire les sources et proposer un nouveau preview. Ignorer toute réponse réseau obsolète d'un brouillon précédent. Après réponse de confirmation perdue, rejouer **le même `command_id` et le même contenu**, puis restituer le reçu initial si déjà appliqué.
- Chaque confirmation conserve la propriété/authentification, la granularité de portée, le `command_id` lié au contenu normalisé, une empreinte versionnée, le verrou **avant** relecture/revalidation, l'historique append-only corrélé et le rollback transactionnel complet SQLite/PostgreSQL. Un conflit de réservation ne crée aucun droit de déplacer/annuler cette réservation ni d'écrire sur Google Calendar.

**Bornes de confiance :** l'inventaire des réservations et exceptions futures persistées doit couvrir le futur effectivement affecté; la projection numérique est bornée (93 jours dans les contrats existants) et ne prouve pas l'absence de conflits pour une série infinie. Expliquer la fenêtre d'analyse; Google n'est pas verrouillable.

## 4. Relation aux ADR antérieurs

**Substitution ciblée et prospective** : cet ADR **remplace explicitement la seule restriction « pas de glisser-redimensionner V1 » de la décision D5 d'ADR-0024**, ainsi que la répétition de cette exclusion dans la section UX d'ADR-0025, **pour la nouvelle évolution TP-027 après livraison des garanties A/B/C**. L'interdiction était une limite de portée de V1, pas une interdiction durable. **Ne pas réécrire les ADR historiques.** Les autres exigences de D5 — panneau contextualisé, choix/protection des couches, accessibilité, perception correcte de la capacité et `draft → preview → confirm` — restent applicables.

Complète ADR-0022 sur la supersession des jours futurs en l'étendant aux **séries de permission**; respecte ADR-0025 (base neuve, `WorkType.scope_id`, pas de legacy), ADR-0024 (priorité contextuelle et capacité unique), ADR-0021 (bookings en conflit conservés), ADR-0020 (temporalité/DST), ADR-0002/0005 (proposition vs consentement, audit) et ADR-0009 (Google lecture seule). **Aucune autre décision de ces ADR n'est abrogée.**

## 5. Découpage autorisé et validations bloquantes

**Gate ASTRA-TP027 :** les arbitrages D1/D2/D3 sont approuvés. Clôture `DONE` uniquement après ADR/index fusionnés et validation documentaire, puis réconciliation atomique du roadmap #1 et de l'issue #76. L'autorisation humaine cadre permet ensuite de promouvoir **TP-027A seul** à `MAIN READY`; B/C demeurent `BLOCKED` jusqu'à leurs dépendances réellement livrées.

- **TP-027A — contrats backend :** édition récurrente ciblée par jours et supersession future, exceptions `REMOVE/MOVE` et arbitrage de leurs révisions, commandes preview/confirm cohérentes enveloppe/permission/exception, objets éditables, empreintes, audit/idempotence et rollback. Tests : mardi/jeudi isolés, révisions futures et deuxième sauvegarde à date identique, déplacement atomique, exceptions en semaines différentes, conflits de réservation et perte de réponse, courses édition/réservation sous **SQLite et PostgreSQL**, DST/24:00 et occupation hors enveloppe visible.
- **TP-027B — grille et édition directe :** grille unique orientée jour-colonne/heure-verticale, cadrage/zoom, couches, objets entiers et superpositions, création sur vide, poignées, déplacement, fantôme et snap sans arrondi destructif, panneau commun, clavier/mobile/lecteurs d'écran, `409` conservant brouillon et réponses tardives ignorées. Retirer les cartes et éditeurs redondants **uniquement après parité démontrée**; aucune logique métier de placement en React.
- **TP-027C — recette intégrée :** E2E navigateur avec **vraie API FastAPI et base initialisée via Alembic** (pas seulement `page.route`), validation PostgreSQL/SQLite, consentement/concurrence/rollback, jour DST 23/25 h, fuseau navigateur différent, `24:00`, trois admissions, occupation incompatible hors enveloppe, absence de double capacité, accessibilité, état vide TP-026 et parité de toutes les commandes. CI backend, frontend, PostgreSQL et E2E requises vertes avant merge.

**Ordre canonique :** ASTRA-TP027 → TP-027A → TP-027B → TP-027C. Une seule tranche `MAIN READY` à la fois; B/C ne sont pas lancées prématurément. Le mandat ne modifie pas `TP-080D BLOCKED` en standby et n'autorise ni reset local/distant, ni déploiement, ni Go-Live, ni écriture Google Calendar.
