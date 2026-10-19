# TaskPlanner

TaskPlanner est une application personnelle de gestion et de planification des tâches centrée sur la capacité réelle, la réduction de la charge mentale et la prise de décision explicite.

## Vision

Le produit doit permettre de capturer rapidement ce qui est à faire, transformer les projets en petites unités amorçables, protéger ce qui ne doit pas dérailler et proposer des options réalistes lorsqu'il y a trop de travail pour la capacité disponible.

TaskPlanner **propose** des arbitrages; l'utilisateur **décide**.

## Stack initiale

- Frontend : React + TypeScript + Vite
- Backend : Python + FastAPI
- Domaine : règles Python séparées de HTTP et de la persistance
- Persistance : SQLAlchemy; SQLite pour le développement initial
- Intégrations prévues : Google Calendar / Reclaim, puis assistance OpenAI
- CI : GitHub Actions

## Gouvernance

- `AGENTS.md` contient les règles durables pour les agents de développement.
- Le roadmap maître est l'issue GitHub **#1**.
- `docs/PRODUCT.md` décrit les principes produit.
- `docs/architecture/` contient les ADR et décisions d'architecture.

Le roadmap GitHub doit être mis à jour à chaque tranche structurante afin de refléter l'état réellement livré.

## Démarrage

Backend :

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend :

```bash
cd frontend
npm install
npm run dev
```

Tests backend :

```bash
pytest -q
```

Build frontend :

```bash
cd frontend
npm run build
```

## Préparation Render / Supabase

Le Blueprint versionné `render.yaml` décrit le frontend statique et FastAPI,
sans déploiement automatique. **Ne pas activer Render avant l'autorisation de
mise en ligne de TP-080D.** Suivre `docs/RENDER_DEPLOYMENT.md` pour les
origines, variables, secrets, contrôles d'accès et migrations.

## Tester localement avec Docker

Ce mode facultatif ne crée **aucun** service Render ni projet Supabase. Voir
[docs/LOCAL_DOCKER.md](docs/LOCAL_DOCKER.md) pour les prérequis et les précautions
de sécurité. Depuis PowerShell à la racine du dépôt :

```powershell
if (-not (Test-Path .env)) { Copy-Item docker/.env.example .env }  # ne pas écraser une .env existante
notepad .env                        # remplir TASKPLANNER_DOCKER_DB_PASSWORD
docker compose up --build -d
```

Accès : **http://localhost:5173** uniquement sur l'ordinateur local.
Le volume PostgreSQL survit à `docker compose down` ; **ne pas lancer
`docker compose down -v` sauf pour supprimer volontairement toutes les données de test**.
Ce mode désactive l'authentification exclusivement pour des tests locaux;
ne pas l'exposer sur le réseau ni l'utiliser en production.


## Configuration neuve des disponibilités (TP-026)

Une base **vierge** est requise par la nouvelle baseline Alembic. Après
le démarrage, créer une catégorie parente puis une sous-catégorie, définir
une enveloppe physique hebdomadaire pour le parent et utiliser
**+ Nouvelle plage** pour créer des permissions superposables. Aucune
catégorie de compatibilité ni donnée de démonstration n'est insérée.
Les routes de création de blocs manuels et de règles exclusives sont
retirées. Les réservations confirmées et les protections des tâches
restent soumises à décision explicite. Voir [la recette locale](docs/LOCAL_DOCKER.md).
