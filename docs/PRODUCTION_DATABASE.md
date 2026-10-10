# TP-080B — Runbook PostgreSQL / Supabase

Ce guide prépare la base sans déployer publiquement l'application.
La mise en ligne et les validations de restauration en situation réelle
appartiennent à TP-080D. Ne pas mettre de credentials dans GitHub ou des logs.

## 1. Préparer un projet Supabase dédié

Configurer Supabase Auth suivant ADR-0018. La base PostgreSQL doit rester
non accessible directement depuis React. Dans Supabase Dashboard, vérifier
que taskplanner N'EST PAS dans Data API > Exposed schemas; si possible,
désactiver Data API entièrement. Ne jamais copier la chaîne PostgreSQL,
la clé service_role ou un mot de passe SQL dans les variables Vite.

Depuis SQL Editor, avec un compte administrateur du projet, provisionner
une seule fois (sans contenu métier) :

    CREATE SCHEMA IF NOT EXISTS taskplanner;
    REVOKE ALL ON SCHEMA taskplanner FROM PUBLIC;
    REVOKE ALL ON SCHEMA taskplanner FROM anon, authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA taskplanner
      REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;

Vérifier les propriétaires, le rôle utilisé par FastAPI, et les privilèges
effectifs. Les rôles anon et authenticated existent sur Supabase, mais pas
nécessairement dans une installation PostgreSQL générique. Ne pas ajouter
taskplanner aux schémas exposés ou accorder USAGE/SELECT à ces rôles.

## 2. Connexion et migrations

Configurer exclusivement sur le backend Render, ou dans un terminal
d'administration isolé :

    TASKPLANNER_ENV=production
    TASKPLANNER_DATABASE_SCHEMA=taskplanner
    TASKPLANNER_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB?sslmode=require

Utiliser la connexion PostgreSQL directe si compatible IPv6, sinon le
Supabase Session Pooler (port fourni par le dashboard Supabase).
Ne pas utiliser le Transaction Pooler. Exiger sslmode=require ou
verify-full avec CA configurée, selon les certificats du fournisseur.
Ne jamais utiliser sslmode=disable, prefer ou allow en production.
Les mots de passe comportant des caractères réservés doivent être
encodés dans l'URL (par exemple via sqlalchemy.engine.URL.create).
Le code ne journalise pas l'URL ni le mot de passe.

Après sauvegarde et pendant une fenêtre de maintenance, exécuter UNE
seule fois, avec les variables backend chargées :

    python -m pip install -r requirements.txt
    alembic current
    alembic upgrade head
    alembic current

Attendre le succès avant de démarrer les workers. Ne jamais exécuter
alembic upgrade head au démarrage de chaque worker. Le healthcheck seul
ne certifie pas les permissions, la migration ou les JWT.

## 3. Sauvegarde et restauration

Configurer la politique de sauvegardes Supabase adaptée à la criticité
et à l'offre retenue; vérifier fréquence, rétention, couverture et coût
avant toute souscription. Effectuer aussi une sauvegarde logique chiffrée
vers un lieu sûr, avec accès limité :

    pg_dump --format=custom --no-owner --schema=taskplanner --file=taskplanner.backup "DATABASE_URL"

La valeur DATABASE_URL utilisée par pg_dump est une URI PostgreSQL
libpq, pas l'URI SQLAlchemy postgresql+psycopg. Ne pas enregistrer
de vraie URL de production dans un shell partagé ou des logs.

Restaurer uniquement sur une base temporaire isolée, jamais par-dessus
des données actives, puis vérifier :

    pg_restore --no-owner --no-privileges --dbname="RESTORE_URL" taskplanner.backup
    alembic current

Avant la reprise, vérifier comptes, tables, volumes, références, historique,
séquences, requêtes métier et connectivité de FastAPI. Conserver un plan
de retour au point de sauvegarde précédent, avec service arrêté. Les
opérations DROP SCHEMA ou downgrade ne sont jamais des procédures
de restauration de données.

## 4. Import contrôlé d'un SQLite existant (facultatif)

Aucun import automatique n'est réalisé. Si une base SQLite locale doit
devenir la source de production, procéder hors ligne :

1. Arrêter toute écriture, conserver une copie immuable du fichier SQLite
   et vérifier PRAGMA integrity_check ainsi que PRAGMA foreign_key_check.
2. Inventorier la version Alembic et compter chaque table métier, y compris
   les événements history_events. Sauvegarder aussi la cible PostgreSQL.
3. Faire migrer une cible PostgreSQL VIDÉE vers head, dans le schéma privé.
   Utiliser un ETL SQLAlchemy explicite avec une transaction unique, dans
   l'ordre des dépendances : work_types, projects, tasks, task_segments,
   availability_blocks, confirmed_time_blocks, history_events,
   daily_reviews, weekly_decisions, resume_points, work_sessions.
4. Préserver les UUID, identifiants, dates UTC, JSON, relations, décisions
   et séquences d'historique. N'inventer aucun événement historique et ne
   pas déduire des UTC à partir de dates ambiguës sans validation.
5. Contrôler les comptages par table, les références, les dernières séquences
   et des lectures métier; repositionner la séquence SERIAL de l'historique
   au maximum importé avant de permettre de nouvelles écritures.
6. Tester un rollback intégral de l'ETL sur une copie et vérifier une
   restauration de la sauvegarde. Exiger validation humaine documentée
   avant toute bascule; ne jamais écraser une cible non vide.

L'ETL d'import n'est pas déclenché par une migration Alembic ni par
l'application et doit être approuvé séparément. Si aucune base SQLite
ne contient de données à conserver, initialiser directement PostgreSQL.

## 5. CI et validation

La CI dispose d'un PostgreSQL 16 jetable. Le test dédié supprime
UNIQUEMENT le schéma taskplanner d'une base locale explicitement nommée
taskplanner_test puis rejoue les migrations et valide lecture/écriture,
JSON, UTC, clés étrangères, index partiel, séquence et rollback.

    pytest -q tests/test_tp080b_postgres.py

Sans TASKPLANNER_PG_TEST_URL les tests sont ignorés et la suite SQLite
continue normalement. Une vraie recette Supabase, la preuve d'un restore
et l'autorisation de mise en ligne sont réservées à TP-080D.
