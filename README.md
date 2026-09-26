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
