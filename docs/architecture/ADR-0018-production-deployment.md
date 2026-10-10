# ADR-0018 — Hébergement de production, identité et frontières de confiance

**Statut : Proposed**
**Date : 2026-10-10**
**Portée : TP-080A à TP-080D (#30–#33), roadmap maître #1**

## Contexte

TaskPlanner a terminé ses fonctionnalités TP-001 à TP-072 sur une architecture React/Vite → FastAPI → domaine Python → SQLAlchemy → SQLite initial. Les routes métier FastAPI actuelles ne demandent pas d'authentification. Le frontend utilise un proxy Vite de développement et PostgreSQL n'a pas encore été validé.

La plateforme cible a été approuvée par le propriétaire du projet : Render pour React et FastAPI, Supabase PostgreSQL pour les données. La cible est une application personnelle accessible depuis ordinateur et téléphone.

## Décision

### Responsabilités et hébergement

- Render Static Site : React + TypeScript + Vite, fichiers statiques compilés, aucune clé privée.
- Render Web Service : FastAPI, autorité métier et seule frontière d'accès aux données opérationnelles.
- Supabase : projet dédié à TaskPlanner pour PostgreSQL et Supabase Auth. Ne pas réutiliser les bases BudgetPlanner/Menuo.
- SQLAlchemy + Alembic restent la persistance autoritaire. SQLite est conservé pour le développement/CI, PostgreSQL devient la cible de production.
- Google Calendar et OpenAI restent des adaptateurs facultatifs derrière FastAPI, avec secrets côté backend.

## Authentification et autorisation

- Supabase Auth produit les sessions. Toutes les routes métier GET/POST/PATCH/DELETE, IA, calendrier, sessions et projections requièrent un accès autorisé. Seul /api/health peut rester public, avec réponse non sensible.
- FastAPI vérifie la signature JWT via JWKS de Supabase et une bibliothèque de validation, avec émetteur, audience, date d'expiration, sujet stable et algorithme de signature asymétrique autorisé. Ne jamais accepter de JWT seulement décodé sans validation.
- Le premier déploiement est mono-utilisateur : l'identifiant stable Supabase Auth du compte principal (claim sub) doit appartenir à une liste positive configurée côté backend. Un JWT valide ne donne pas automatiquement accès.
- Désactiver l'inscription publique; identité créée/administée explicitement. Pas d'autorisation basée sur l'adresse courriel ou sur user_metadata, qui peut être modifié.
- Toute configuration manquante d'auth en production fait échouer le démarrage. Aucun mode bypass de développement actif en production. Les tests hors-ligne restent possibles grâce à l'injection de dépendances/test doubles.
- Le multi-utilisateur, les comptes partagés et RBAC avancé sont exclus de cette phase.

## Base PostgreSQL et secrets

- Le frontend ne lit pas les tables métier via Supabase Data API. Une clé Auth publishable côté React est acceptable; mot de passe PostgreSQL, clés service_role/secret, OAuth Google Calendar et clés OpenAI restent côté backend.
- Privilégier un schéma PostgreSQL non exposé à la Data API. Si des tables sont dans un schéma exposé, verrouiller privilèges et RLS deny-all, vérifier par Security Advisor. RLS n'annule pas les privilèges de propriétaire/compte SQL privilégié utilisé par FastAPI.
- FastAPI se connecte à PostgreSQL via TLS, URL de connexion stockée en variable d'environnement Render; utiliser un pooler Supabase mode session si nécessaire pour la connectivité IPv4 des services persistants.
- Tester les migrations Alembic sur PostgreSQL, en particulier types, contraintes, historique append-only, transactions et rollback. Le démarrage des workers n'exécute pas les migrations concurrentes.
- La migration depuis SQLite contenant des données privées est optionnelle et nécessite sauvegarde et validation.

## Routage, CI et exploitation

- Le proxy Vite local ne fonctionne pas comme reverse proxy de production. TP-080C configure soit une URL d'API explicite côté React, soit une rewrite Render vérifiée; ne jamais confondre /api avec le fallback SPA index.html.
- HTTPS, CORS à liste positive et contrôle Authorization sur toutes les routes. Aucun secret, note ou token dans logs/erreurs.
- Les PR sont petites, testées, CI vertes; réconciliation du roadmap canonique après chaque fusion.
- Aucun déploiement public sans sécurisation TP-080A et validation TP-080B; aucune création de ressource payante, suppression de projet existant, migration destructive ou exposition publique sans consentement explicite.
- Sauvegardes indépendantes et restauration testée avant utilisation courante; documenter rollback du code et de la DB séparément.
- Les offres gratuites impliquent des limites de veille, de disponibilité et de quotas : le choix tarifaire n'est pas inclus dans cette décision.

## Ordre de livraison

1. TP-080A (#30) : authentification et sécurité.
2. TP-080B (#31) : PostgreSQL Supabase et migrations.
3. TP-080C (#32) : React et FastAPI sur Render.
4. TP-080D (#33) : tests de bout en bout, sauvegardes et recette.

## Conséquences

Cette décision ajoute des dépendances Render et Supabase sans réécriture de la couche métier Python. Elle impose un jalon sécurité avant exposition, conserve le test hors ligne et garde les coûts/activations externes à la décision humaine.

Elle complète ADR-0001 et ADR-0005.
