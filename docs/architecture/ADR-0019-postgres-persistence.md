# ADR-0019 — PostgreSQL Supabase et schéma de production (TP-080B)

**Statut : Accepted**
**Date : 2026-10-10**
**Issue : #31**

## Décision

Le stockage de production utilise PostgreSQL sur un projet Supabase dédié. Le
backend FastAPI demeure l'unique accès métier : React n'accède jamais aux
tables via Data API, PostgREST ou une clé de service. SQLAlchemy, l'unité
de travail et Alembic restent les autorités d'accès et de migration. SQLite
est conservé pour le développement et la suite de tests offline.

La connexion passe par psycopg 3 avec TLS obligatoire en dehors d'un
environnement de test isolé. Le schéma PostgreSQL applicatif est privé,
nommé taskplanner par défaut, et ne doit jamais figurer dans les schémas
exposés par Supabase Data API. Le schéma est provisionné et ses privilèges
sont restreints avant toute migration. Aucune table métier ne réside dans
public. Le rôle du backend doit posséder les droits nécessaires sur ce
schéma; aucun droit ne doit être accordé à anon ou authenticated.

Render utilise un petit pool SQLAlchemy (3 connexions, dépassement 2,
pre-ping) et le connecteur de session Supabase si la connexion directe IPv6
ne convient pas. Ne pas utiliser le transaction pooler comme alternative
implicite. Chaque connexion définit son search_path avant toute requête.
Une migration Alembic utilise NullPool et se lance comme opération de
déploiement unique, jamais à chaque démarrage d'un worker.

Les migrations historiques sont conservées, hormis la correction du filtre
d'index PostgreSQL de la révision 0009. La révision 0010 rend les colonnes
temporelles PostgreSQL plus récentes timezone-aware en interprétant leurs
anciennes valeurs naïves en UTC. Les UUID, JSON, contraintes, clés
étrangères et séquence de history_events conservent leur sémantique.

## Conséquences et limites

Les tests PostgreSQL tournent contre une base locale jetable et un schéma
fraîchement migré. Ils valident les contraintes, l'index partiel, les
instants UTC, les mutations principales et le rollback. Cela ne constitue
pas une preuve de connexion ou de restauration sur un projet Supabase
réel. Cette validation reste une étape opérationnelle avant TP-080D.

La base existante SQLite n'est ni migrée ni détruite automatiquement.
Un import éventuel exige un inventaire, une sauvegarde testée, une
transformation auditée, une vérification des références et un contrôle
explicite avant de basculer le service. Les restaurations de production
sont effectuées hors des workers.
