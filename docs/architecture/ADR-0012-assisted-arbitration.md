# ADR-0012 — TP-051 : arbitrage assisté ancré dans les scénarios déterministes

**Statut : Accepted**
**Date : 2026-10-10**
**WorkItem : TP-051**

## Contexte

TP-030 / ADR-0008 établit des propositions hebdomadaires éphémères, une capacité évaluée de façon déterministe et des conséquences visibles. TP-050 / ADR-0011 établit un adaptateur OpenAI optionnel, sans autorité métier. TP-051 doit aider à comprendre les compromis sans inventer des priorités, dates ni gains.

## Décision

- Une commande de lecture explicite `POST /api/capacity/weeks/{week_start}/arbitration-suggestions` prend la même sélection que TP-030, **recalcule** le scénario à partir des faits actuels, puis demande uniquement une explication des options existantes.
- Le résultat contient **intégralement** la proposition déterministe (faits, capacité par type, conséquences, protections déjà appliquées, indication de confirmation), séparée des textes IA marqués `AI_SUGGESTION / PROPOSED`. Les textes IA ne remplacent jamais ces faits.
- Une explication est obligatoire pour chaque option, indexée par sa position dans la réponse éphémère. Les résultats incomplets, dupliqués, réordonnés ou inventant une option sont rejetés. Les textes restent des suggestions non garanties; l'interface les présente sous les faits d'origine.
- L'adaptateur OpenAI est facultatif, exécuté côté serveur, et reçoit seulement les résumés issus du moteur : états de capacité, chiffres de charge, motifs, labels et conséquences. Pas de notes, événements Calendar, historiques, tokens ni détails d'identité. Il utilise la clé serveur déjà optionnelle de TP-050 et un modèle configurable.
- Sans clé ou si l'IA échoue, la route retourne une erreur explicite et sûre; les propositions déterministes TP-030 demeurent disponibles. Les tests ne dépendent pas de l'API distante.
- Aucune écriture de tâche, protection, priorité, calendrier, choix utilisateur ou état de proposition. La limite de 25 options concerne uniquement l'enrichissement IA, pas le moteur de proposition.

## Conséquences

Pas de migration ni d'acceptation automatique. L'IA peut se tromper dans son langage; l'interface conserve toujours les faits calculés et exige un arbitrage humain distinct avant une éventuelle application future. Ce découplage ne constitue ni un ranking automatique ni une nouvelle règle de capacité.
