# ADR-0001 — Architecture fondatrice

**Statut : Accepted**  
**Date : 2026-09-26**

## Contexte

TaskPlanner doit offrir une interface web simple, un moteur de règles explicable et des intégrations futures avec le calendrier et une assistance IA. Les règles de capacité et de planification ne doivent pas dépendre de l'interface ni d'un service externe.

## Décision

L'architecture initiale est un monolithe modulaire :

```text
React + TypeScript + Vite
          ↓ HTTP
       FastAPI
          ↓
 Application / Domain
          ↓
 Infrastructure
          ↓
 SQLAlchemy / adapters externes
```

Décisions associées :

- Python porte les règles métier autoritaires;
- React présente l'état et collecte les décisions;
- SQLite est le stockage local initial;
- les intégrations externes sont derrière des adapters;
- le cœur doit être testable sans Google Calendar, Reclaim ni OpenAI;
- les propositions et les décisions utilisateur sont des concepts distincts.

## Conséquences

- les règles métier ne sont pas dupliquées dans React;
- les futures intégrations n'imposent pas leur modèle au domaine;
- une évolution de la base de données reste possible sans réécrire le produit;
- les mutations automatiques du calendrier ne sont pas implicites.
