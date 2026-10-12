# TP-022D — recette de l'interface Disponibilités

## Périmètre

Vue **Planification → Disponibilités**, avec **Horaire habituel** et **Semaine réelle**, sans modifier le moteur TP-022A/B/C/R. Toutes les écritures passent par FastAPI, les aperçus d'exception et de résolution restent non engageants, et la confirmation envoie les empreintes/versions reçues. Google Calendar reste en lecture seule.

## Vérifications automatisées

Depuis le dépôt (avec Node 22) :

```bash
cd frontend
npm install --no-audit --no-fund
npm run test:auth
npm run build
npx playwright install chromium
npm run test:e2e
```

Les scénarios Playwright lancent Vite en mode local et **simulent uniquement les réponses HTTP** pour vérifier les interactions et la présentation sans secrets, Google Calendar ni base réelle. Les deux projets de navigateur couvrent Chromium desktop et mobile. En CI le job `frontend-e2e` installe Chromium avec ses dépendances système. Les tests backend TP-022A/B/C/R assurent séparément la logique et les transactions.

## Recette intégrée (backend réel local, aucune donnée de production)

1. Ouvrir l'application locale desktop, puis écran mobile 390 × 844 et navigation clavier. Confirmer les deux onglets de Planification, le focus visible, l'absence de défilement horizontal et la grille lundi → dimanche.
2. Créer une enveloppe générale hebdomadaire, puis une plage **CATEGORIZED** mardi/jeudi 09:00–11:30, **PREFERRED**. Vérifier dans la semaine réelle la projection déclarée (300 min catégorisées, non ajoutées à l'enveloppe) et l'origine des plages. Créer une autre plage **PROTECTED**; vérifier la distinction visuelle.
3. Annuler le mardi via « Annuler » de l'occurrence et **prévisualiser**. Vérifier que jeudi reste, que la semaine suivante retrouve mardi + jeudi, et que la capacité n'est pas automatiquement transférée vers NULL.
4. Remplacer une occurrence et confirmer; vérifier la date d'origine conservée. Réviser la série dès une date future; vérifier que les semaines antérieures ne changent pas. Essayer une date invalide, une édition obsolète et une heure DST inexistante : le backend doit refuser.
5. Ajouter une **UNAVAILABLE** chevauchant une réservation locale. Vérifier l'aperçu, le code de conflit, l'accusé explicite à la confirmation, et la réservation toujours inchangée après création de l'exception.
6. Résoudre le conflit avec **KEEP** (il reste OPEN), puis avec **CANCEL** (disparaît de la vue réelle). Sur un second jeu de données, prévisualiser puis confirmer **MOVE** vers un créneau compatible; vérifier la nouvelle réservation et l'historique append-only. Un aperçu périmé doit être rejeté par HTTP 409 et reproposé, jamais appliqué silencieusement.
7. Sans connexion Google, vérifier que la capacité déclarée reste visible, mais que le bouton « Vérifier avec Google Calendar » montre une erreur explicite et n'annonce jamais la capacité libre comme vérifiée. Avec connexion de lecture, vérifier que les occupations déduisent les minutes même sur une plage protégée.
8. Confirmer que la vue manuelle « Capacité et propositions » et le planificateur TP-041 restent accessibles, que les règles/exception ne créent aucune écriture Google ni modification automatique de tâche, et que les états vide, chargement et erreur restent compréhensibles.

**Limite explicite** : les scénarios Playwright utilisent des API simulées; ils ne remplacent pas la recette intégrée avec SQLite/PostgreSQL et un Google Calendar de test. La recette de production TP-080D demeure distincte et non autorisée par TP-022D.
