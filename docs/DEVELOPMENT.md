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
uvicorn app.main:app --reload
```

API de santé :

```text
GET http://localhost:8000/api/health
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Le frontend Vite écoute par défaut sur `http://localhost:5173`.

## Validation

```bash
python -m compileall -q app tests
pytest -q
cd frontend
npm install --no-audit --no-fund
npm run build
```

## Configuration

Copier `.env.example` vers `.env` pour la configuration locale. Ne jamais committer `.env`.

Les intégrations externes doivent rester facultatives pendant le développement du cœur métier.
