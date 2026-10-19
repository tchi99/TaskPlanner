# TP-081 — Tester TaskPlanner localement avec Docker Compose

Cette configuration est **réservée à un seul ordinateur de développement**. Elle
ne crée aucun service Render ou Supabase, ni forfait payant, ni base distante.

Architecture : Vite (React) → FastAPI → PostgreSQL 16, avec un volume persistant.

## Démarrage sur Windows

Installer **Docker Desktop** (moteur démarré) et Git.
Ouvrir PowerShell et exécuter :

```powershell
git clone https://github.com/tchi99/TaskPlanner.git
cd TaskPlanner
# Si ce fichier existe déjà, ne pas le remplacer.
if (-not (Test-Path .env)) { Copy-Item docker/.env.example .env }
notepad .env
```

Renseigner `TASKPLANNER_DOCKER_DB_PASSWORD` avec un mot de passe **long et
alphanumérique**. Pour ce test, éviter les caractères spéciaux réservés
aux URL SQL (`@`, `:`, `/`, `#`) afin que la chaîne PostgreSQL reste valide.
Ne jamais mettre cette valeur dans GitHub ou dans la conversation.

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Ouvrir **http://localhost:5173**. La première initialisation crée la base
PostgreSQL locale et son schéma `taskplanner`. Le service `migrate` applique
les migrations Alembic **avant** le démarrage de FastAPI. Le proxy Vite envoie
les appels `/api` vers `backend:8000` sur le réseau privé Docker.

Si une `.env` existe déjà à la racine du dépôt : **ne pas l'écraser**;
ajouter uniquement la variable `TASKPLANNER_DOCKER_DB_PASSWORD`.
La `.env` locale est ignorée par Git et exclue des images Docker.

## Sécurité : ne jamais exposer cette variante sur le réseau

- Le seul port publié est `127.0.0.1:5173:5173`. Ni PostgreSQL ni FastAPI
  ne publient de port hôte.
- `TASKPLANNER_AUTH_MODE=local` contourne la connexion **uniquement dans le
  mode Vite DEV et le backend `TASKPLANNER_ENV=test`**. Ce bypass n'est pas
  destiné à la production, et le build frontend Render conserve Supabase Auth.
- Ne pas changer le port hôte en `0.0.0.0`, ni déployer ce Compose sur un NAS,
  Internet, ou un réseau partagé.
- L'accès depuis le téléphone sur le Wi-Fi est volontairement désactivé.
- Les intégrations Google Calendar et OpenAI sont facultatives et nécessitent
  des credentials côté serveur si on souhaite les tester.

## Vérifications proposées

1. Créer une tâche et un projet, puis clarifier la tâche.
2. Ajouter et terminer un segment; consulter les revues du jour et de semaine.
3. Rafraîchir la page et vérifier que les données subsistent.
4. Exécuter `docker compose down`, puis `docker compose up -d`, et vérifier
   à nouveau la persistance.
5. Consulter les journaux en cas de problème :

```powershell
docker compose logs --tail 80 db migrate backend frontend
```

## TP-026C — démarrage réellement vierge

Une nouvelle installation applique uniquement la révision Alembic
`0020_tp026_fresh` sur une base **sans tables métier**. Elle n'insère
aucun parent, aucune sous-catégorie et aucune permission précréés.
L'assistant de configuration affiche les étapes parent → sous-catégorie →
enveloppe physique → `+ Nouvelle plage`, avec aperçu et confirmation.

**Aucun reset automatique** n'est exécuté par Compose ou Alembic. Si un
ancien volume local contient la chaîne historique, la migration refuse
de la modifier; l'échec est intentionnel. Avant un éventuel
`docker compose -p taskplanner-local down -v`, vérifier dans Docker
Desktop le projet exact `taskplanner-local`, le conteneur `db` et
le volume de ce projet, puis confirmer que cette **seule base locale**
est jetable. Ne jamais appliquer la commande à un contexte distant,
partagé ou à une base Supabase/Render.

La CI inclut une recette isolée `docker-bootstrap` dans un nouveau
projet Compose éphémère : PostgreSQL vierge → Alembic → FastAPI/Vite →
création parent/sous-catégories → enveloppe → deux permissions qui se
chevauchent → contrôle de non-additivité et absence d'API d'écriture
legacy. Le projet de CI est supprimé à la fin de sa propre exécution;
cela ne touche **aucun** volume local de développement. Hors CI,
exécuter `python -m scripts.verify_tp026c_bootstrap` **seulement**
sur une instance locale jetable **encore vierge**, accessible sur
`127.0.0.1:5173`, car le script crée des données d'essai.

Les anciennes déclarations physiques restent consultables pour
l'affichage et la sélection d'occurrences, mais leurs routes d'écriture
sont fermées. Les nouvelles éditions récurrentes passent par
`/api/availability/weekly-schedule/preview` et `/confirm`;
les permissions par `/api/availability/eligibility-edits`.
Les dérogations physiques datées et décisions sur réservations
conservent leurs prévisualisations et confirmations propres.

## Sauvegarder ses données locales

Le volume `taskplanner_pg_data` demeure après un simple arrêt. Pour obtenir
une sauvegarde PostgreSQL au format binaire personnalisé, même depuis
PowerShell Windows :

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T db sh -c 'pg_dump -U taskplanner -d taskplanner_dev -n taskplanner -Fc -f /tmp/taskplanner-local.dump'
$containerId = docker compose ps -q db
docker cp "${containerId}:/tmp/taskplanner-local.dump" ./backups/taskplanner-local.dump
```

Tester la restauration sur une **autre base isolée** avant de considérer le
fichier comme une sauvegarde validée. Ne pas lancer une restauration par-dessus
les données utilisées.

## Arrêter ou repartir à neuf

```powershell
# Arrêt sans effacer les données
docker compose down

# Effacement volontaire et irréversible de TOUTES les données locales
docker compose down -v
```

Attention : changer le mot de passe dans `.env` après l'initialisation ne
change pas celui déjà stocké dans PostgreSQL. Ne pas effacer le volume pour
résoudre ce problème avant d'avoir sauvegardé les données à conserver.

## Limites

- Le frontend utilise **Vite DEV**, pas un build React de production; c'est
  volontaire pour tester sans dépendre de Supabase Auth. Cela ne remplace pas
  la recette HTTPS/identité/CORS sur Render.
- Le mot de passe et la base sont locaux : aucun lien automatique vers
  Supabase. La future migration de données réelles reste une opération
  contrôlée, pas un simple changement de chaîne de connexion.
- Si le port 5173 est déjà occupé, arrêter le processus existant;
  ne pas l'ouvrir à toutes les interfaces pour contourner l'erreur.
- Si Docker Desktop est indisponible, aucune exécution Docker réelle ne peut
  être présumée : on peut seulement valider statiquement la configuration.

Le Go/No-Go de production reste documenté dans
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
