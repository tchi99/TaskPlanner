# ADR-0018 — Authentification Supabase et frontière d'accès API (TP-080A)

**Statut : Accepted**  
**Date : 2026-10-10**  
**Issue : #30**

## Contexte

Le frontend React/Vite et FastAPI devront être exposés sur Render, avec une base
PostgreSQL Supabase dans une tranche ultérieure. Les endpoints actuels ne
portent pas d'identité : une exposition publique serait dangereuse.

## Décision

- **Supabase Auth authentifie un compte précréé** par email + mot de passe
  (signInWithPassword). Désactiver l'inscription publique et les providers
  non nécessaires dans le dashboard Supabase. Seul le UUID immutable du `sub`
  est autorisé; jamais l'adresse email.
- Le navigateur reçoit seulement l'URL Supabase et une clé publishable.
  Le SDK gère et renouvelle la session; tous les appels métier restent
  dirigés vers FastAPI, avec bearer JWT. La déconnexion efface immédiatement
  le bearer en mémoire et appelle Supabase signOut.
- FastAPI protège par défaut toutes les routes (GET, POST, etc.), aussi
  `/docs` et `/openapi.json`; seul `/api/health` est public. JWT : vérifier
  signature via les clés publiques JWKS du projet configuré, et strictement
  `exp`, `iat`, `iss` exact, `aud` attendu, `sub` UUID autorisé. Algorithmes
  acceptés : RS256/ES256 uniquement. 401 pour identité invalide/absente,
  403 si identité authentifiée mais non autorisée. L'URL JWKS est calculée
  côté serveur, jamais extraite d'un jeton.
- Le projet Supabase doit activer une clé de signature asymétrique RS256
  ou ES256 présente dans le JWKS. Les anciens tokens HS256 sont refusés.
  Clés JWKS mises en cache 300 secondes, timeout réseau de 3 secondes.
- La configuration Supabase et CORS HTTPS explicite sont requises dès
  l'initialisation en production. Pas de configuration = refus de démarrer.
  Le mode local nécessite un opt-in explicite, est interdit hors
  development/test, et un build Vite production n'active jamais ce bypass.
- Les secrets Google, OpenAI et SQL demeurent côté backend. React ne lit
  ni n'écrit directement dans les tables métier Supabase. Migration SQL,
  hébergement et sauvegardes relèvent de TP-080B/C/D.

## Conséquences

- Aucune migration ni modification du domaine dans TP-080A.
- Les tests vérifient chaque route, les jetons valides/invalides, CORS
  et le démarrage fail-closed; les tests métier restent offline en mode local.
- Création du compte et désactivation des inscriptions : étapes manuelles
  d'administration Supabase; aucun compte n'est provisionné par l'application.
- Pas de mise en ligne publique avant TP-080D. TLS et proxy Render sont
  des exigences d'exploitation distinctes.
