# TP-080C — Préparation de Render (sans déploiement)

Ce runbook prépare **uniquement** une configuration versionnée. **Ne pas
synchroniser le Blueprint, créer les services ou publier l'API** pendant
TP-080C. Même avec les déploiements automatiques désactivés, une première
synchronisation de Blueprint peut créer des services exposés publiquement.
TP-080D exige recette, sauvegarde/restauration et autorisation humaine
explicite avant toute exposition ou dépense.

## Architecture et routage

- `taskplanner-web` : Render Static Site (React/Vite), sous-dossier
  `frontend`, compilation vers `dist`, HTTPS géré par Render.
- `taskplanner-api` : Render Web Service Python/FastAPI, `/api/health`
  comme liveness HTTP, démarrage `uvicorn` sur le port `$PORT`.
- `/api/*` : le navigateur appelle **directement** l'origine HTTPS
  définie par `VITE_TASKPLANNER_API_URL`. Le Static Site ne fait **pas**
  de reverse proxy vers FastAPI. Le proxy Vite local continue de servir
  les URL relatives en développement.
- La règle Render `/* → /index.html` ne concerne que la navigation SPA
  sur le domaine statique; elle ne transporte pas de requêtes API.
- La base PostgreSQL reste dans Supabase avec le schéma privé
  `taskplanner`. Seul FastAPI possède l'accès SQL. Aucune ressource
  Render Postgres n'est créée.

## Variables à préparer (jamais dans Git)

Backend **uniquement**, dans l'environnement du Web Service Render :

| Variable | Valeur attendue |
| --- | --- |
| `TASKPLANNER_ENV` | `production` (fixée par Blueprint) |
| `TASKPLANNER_AUTH_MODE` | `supabase` (fixée) |
| `TASKPLANNER_DATABASE_SCHEMA` | `taskplanner` (fixée) |
| `TASKPLANNER_DATABASE_URL` | URI psycopg privée avec `sslmode=require` |
| `TASKPLANNER_SUPABASE_URL` | origine HTTPS du projet Supabase |
| `TASKPLANNER_SUPABASE_ALLOWED_SUB` | UUID canonique de l'unique compte autorisé |
| `TASKPLANNER_CORS_ORIGINS` | origine HTTPS exacte du Static Site, sans slash final |

Le `TASKPLANNER_SUPABASE_AUDIENCE` par défaut est `authenticated`.
Ne jamais utiliser `TASKPLANNER_AUTH_MODE=local` en production.
Render saisit les valeurs `sync: false` sans les committer au dépôt.
La base, l'authentification et les règles de sécurité sont détaillées
dans `docs/PRODUCTION_DATABASE.md` et ADR-0018/ADR-0019.

Frontend **public, à la compilation seulement**, dans le Static Site :

| Variable | Valeur attendue |
| --- | --- |
| `VITE_SUPABASE_URL` | même origine HTTPS du projet Supabase |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | clé *publishable* (jamais service_role) |
| `VITE_TASKPLANNER_API_URL` | origine HTTPS exacte du Web Service (p. ex. `https://taskplanner-api.onrender.com`) |

Les variables `VITE_*` sont visibles dans le JavaScript livré; aucune
clé SQL, clé secrète, token OAuth ou clé OpenAI ne doit y figurer. Elles
sont figées lors de chaque `npm run build`, et toute modification
nécessite un nouveau build du Static Site. Le client refuse en production
une URL d'API absente, non HTTPS ou contenant chemin/query/credentials.

Vérifier que `TASKPLANNER_CORS_ORIGINS` correspond **exactement** à
l'origine de la page. Ne pas utiliser `*`. FastAPI vérifie le bearer JWT
de chaque route métier; `/api/health` est public, mais ne valide ni SQL
ni Auth Supabase.

## Étapes opératoires réservées à TP-080D

1. Valider le projet Supabase dédié, un compte précréé, les signups
   désactivés, les clés JWKS asymétriques et le schéma privé. Avoir une
   sauvegarde ET une restauration vérifiée avant bascule.
2. Vérifier les domaines réels Render; mettre les origines exactes en
   correspondance dans CORS, Auth > URL Configuration et Vite.
3. Appliquer `render.yaml` **après accord humain**, revoir le choix de
   plan/coûts et éviter une modification d'un service existant du même
   nom. `autoDeployTrigger: off` empêche les nouveaux déploiements à
   chaque commit, mais ne bloque pas le déploiement initial si Blueprint
   est activé.
4. Exécuter la migration `alembic upgrade head` **une seule fois**
   depuis un environnement d'administration isolé, après le
   provisionnement du schéma, avant de permettre le trafic; jamais
   au démarrage Uvicorn ni à chaque worker.
5. Recetter HTTPS, CORS preflight, santé, connexion compte autorisé,
   401/403, CRUD, reload SPA, erreurs réseau et session expirée; s'assurer
   qu'aucune route métier ni table SQL ne contourne FastAPI.
6. Contrôler l'observabilité Render : logs de processus et disponibilité
   `/api/health` sans logs d'accès détaillés (`--no-access-log`).
   Ne pas journaliser le corps des requêtes, JWT, URL SQL, courriels
   ou contenu des tâches. Liveness ne remplace pas une recette.
7. Documenter rollback, restauration et autorisation avant de déclarer
   la production accessible. Cela appartient à TP-080D.

## Commandes de validation sans déploiement

    python -m pip install pyyaml
    python tests/check_render_blueprint.py
    python -m compileall -q app tests migrations
    pytest -q
    cd frontend
    npm install --no-audit --no-fund
    npm run test:auth
    npm run build

Le dépôt ne possède pas encore de `frontend/package-lock.json`.
Le Blueprint génère donc un lock temporaire à chaque build, puis utilise
`npm ci`. **Ce n'est pas un build entièrement déterministe** tant qu'un
lock audité n'est pas committé; ne pas prétendre le contraire. Le passage
à un lock versionné est à prévoir avant la mise en ligne TP-080D.
Aucune commande ici ne déclenche un déploiement public.

## Recette TP-080D

Le contrôle Go/No-Go, la validation mobile/desktop, le restore réel,
les sauvegardes indépendantes, la surveillance et le rollback sont décrits
dans [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md). Cette procédure
ne déclenche aucun déploiement : l'accord humain reste obligatoire avant
l'exposition de l'API.
