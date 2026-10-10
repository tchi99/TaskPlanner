# Développement local

## Prérequis

- Python 3.12+
- Node.js 22+
- npm

## Backend

```bash
python -m venv .venv
# activer l'environnement
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API de santé :

```text
GET http://localhost:8000/api/health
```

API Inbox :

```text
POST /api/tasks
GET  /api/tasks/inbox
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Le frontend Vite écoute par défaut sur `http://localhost:5173` et proxifie `/api` vers le backend local sur le port 8000.

## Migrations

Toute évolution de schéma persisté doit utiliser Alembic.

```bash
alembic upgrade head
```

Ne pas remplacer une migration par un `Base.metadata.create_all()` dans le runtime applicatif.

## Validation

```bash
python -m compileall -q app tests migrations
pytest -q
cd frontend
npm install --no-audit --no-fund
npm run build
```

## Configuration

Copier `.env.example` vers `.env` pour la configuration locale. Ne jamais committer `.env`.

Les intégrations externes doivent rester facultatives pendant le développement du cœur métier.


## TP-040 — Google Calendar, lecture seule

La capacité manuelle reste la source des plages potentiellement disponibles.
Le bouton « Lire Google Calendar » consulte à la demande les événements occupés
et soustrait leur union (seulement lorsqu'ils croisent un bloc manuel). Un
événement hors des blocs n'augmente ni ne diminue cette capacité. Un événement
transparent, annulé, de localisation de travail ou refusé par l'utilisateur
est ignoré; les événements récurrents sont développés côté API Google.

Configuration locale facultative dans .env (ne jamais committer ce fichier) :

- TASKPLANNER_GOOGLE_CALENDAR_IDS=primary (liste séparée par des virgules si plusieurs calendriers);
- soit TASKPLANNER_GOOGLE_ACCESS_TOKEN (jeton OAuth temporaire);
- soit TASKPLANNER_GOOGLE_CLIENT_ID, TASKPLANNER_GOOGLE_CLIENT_SECRET
  et TASKPLANNER_GOOGLE_REFRESH_TOKEN (obtenu par consentement OAuth externe
  avec le scope https://www.googleapis.com/auth/calendar.readonly).

TP-040 n'introduit pas de connexion OAuth interactive : le consentement et
la fourniture du jeton sont réalisés hors de TaskPlanner. Le backend rafraîchit
un access token au besoin avec un refresh token configuré; ni jeton ni contenu
du calendrier ne sont persistés. Les comptes sans credentials continuent de
fonctionner, mais la lecture du calendrier signale une indisponibilité plutôt
que d'assimiler le calendrier à une semaine vide.

Endpoint : GET /api/capacity/weeks/{week_start}/calendar?timezone_name=America/Toronto.
La semaine commence le lundi dans ce fuseau IANA; la fenêtre de fin est
exclusive. Les réservations toute la journée et les passages heure d'été/hiver
sont traités en temps réel écoulé. La capacité restante est un aperçu :
les endpoints de faisabilité et les propositions TP-020/TP-030 restent basés
sur les blocs manuels et ne sont pas modifiés par TP-040. Aucune écriture
Google Calendar, aucune conversion événement→tâche, aucune migration.

## TP-080A — Authentification et sécurisation

**Ne jamais exposer publiquement le projet avant TP-080D.**

### Local/CI sans credentials

Copier `.env.example` vers `.env` et `frontend/.env.example` vers
`frontend/.env.local`. Le mode `TASKPLANNER_AUTH_MODE=local` avec
`TASKPLANNER_ENV=development` et `VITE_TASKPLANNER_AUTH_MODE=local` pour
Vite DEV est un **bypass explicite réservé à un poste local non exposé**.
Le backend interdit ce mode en production. Sans configuration Supabase,
le mode par défaut refuse de démarrer. Les tests CI optent pour
`TASKPLANNER_ENV=test` et `TASKPLANNER_AUTH_MODE=local`.

### Activation de Supabase Auth

1. Utiliser le projet Supabase dédié à TaskPlanner, sans accès direct du
   frontend aux tables métier.
2. Dans Authentication > Providers, activer Email/mot de passe; dans les
   paramètres d'inscription, **désactiver les signups publiques**.
   Désactiver les providers et invitations non utilisés.
3. Dans Authentication > Users, créer et confirmer manuellement l'unique
   compte autorisé avec mot de passe fort. Copier son **User ID UUID**
   (claim `sub`) plutôt que son adresse email.
4. Configurer des clés de signature Auth JWT **RS256 ou ES256**.
   Vérifier le JWKS public à
   `https://<project>.supabase.co/auth/v1/.well-known/jwks.json`.
   Si le projet utilise encore HS256 legacy, prévoir la rotation avant
   activation. Les JWT HS256 seront refusés.
5. Dans Authentication > URL Configuration, définir Site URL sur
   l'origine HTTPS du frontend Render et autoriser les URL de redirection
   (par exemple `https://taskplanner.example.com/**`). Pour du dev,
   ajouter explicitement `http://localhost:5173/**` si utile.
6. Backend (variables secrètes/privées, jamais préfixées VITE) :
   - `TASKPLANNER_ENV=production`
   - `TASKPLANNER_AUTH_MODE=supabase`
   - `TASKPLANNER_SUPABASE_URL=https://<project>.supabase.co`
   - `TASKPLANNER_SUPABASE_ALLOWED_SUB=<UUID autorisé>`
   - `TASKPLANNER_SUPABASE_AUDIENCE=authenticated`
   - `TASKPLANNER_CORS_ORIGINS=https://<frontend Render>`
     (origines multiples séparées par virgules; jamais un wildcard).
7. Frontend (valeurs **publiques** uniquement) :
   - `VITE_SUPABASE_URL=https://<project>.supabase.co`
   - `VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxx`
   Ne pas définir le mode local. Les appels métier passent exclusivement
   par `/api` et le routage Render sera traité en TP-080C.

Jamais de service_role, secret de signature JWT, mot de passe SQL,
secret Google ou OpenAI dans le frontend ou le dépôt. Anonymous, jeton
falsifié/expiré, mauvais issuer/audience et absence de jeton → 401;
compte valide avec autre `sub` → 403. `/api/health` est public.
Un bearer JWT déjà délivré reste utilisable jusqu'à sa date d'expiration;
les durées de vie courtes et HTTPS sont indispensables.

### Vérifications

```bash
python -m compileall -q app tests migrations
pytest -q tests/test_tp080a_security.py
pytest -q
cd frontend
npm install --no-audit --no-fund
npm run test:auth
npm run build
```

Tester aussi manuellement : connexion autorisée, lecture/écriture,
déconnexion, rechargement anonyme, compte différent et accès GET sans JWT.
La mise en production exige une revue de sécurité distincte (TP-080D).
