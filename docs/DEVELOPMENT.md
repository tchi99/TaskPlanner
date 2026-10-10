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
