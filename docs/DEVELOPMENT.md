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
