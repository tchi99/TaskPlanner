# TP-025D — Recette de l'édition contextuelle

## Portée et contraintes

Cette tranche ajoute l'édition de séries d'admissibilité depuis les barres de la
grille hebdomadaire. La grille de TP-025C reste une **projection en lecture seule**
jusqu'à la confirmation explicite. L'éditeur est un formulaire; aucun
glisser-redimensionner n'est introduit. Aucune écriture Google Calendar,
déploiement, migration destructive ou activation TP-080D.

Routes : GET \`/api/availability/eligibility-edits/series/{series_id}\`,
POST \`/preview\` et POST \`/confirm\`. Les commandes ne manipulent que
les séries de permission ou un cutover opt-in d'une règle exclusive PREFERRED.
Les règles PROTECTED ne sont pas converties; les exceptions futures liées
bloquent l'opération jusqu'à résolution séparée. Les réservations
CONFIRMED ne sont jamais mutées.

## Procédure de recette fonctionnelle

1. Créer un parent **Travail** avec une enveloppe GENERAL couvrant les fenêtres
   souhaitées. Vérifier que **Personnel** conserve son enveloppe séparée.
2. Créer les activités **Focus work** et **Réunions** affiliées à Travail;
   depuis une barre du parent, ouvrir le détail (clic, entrée au clavier,
   toucher) puis le formulaire contextuel. Pour une ancienne fenêtre
   CATEGORIZED PREFERRED, choisir explicitement la transition opt-in.
3. Déclarer Focus les mardi, mercredi et jeudi, 09:00–12:00 et
   13:00–15:00; déclarer Réunions les jours ouvrables 10:00–12:00 et
   13:00–16:00. Chaque intervalle d'une même journée correspond à une
   série distincte lorsque les heures diffèrent; ne pas modifier GENERAL.
4. Attribuer le rang contextuel Focus pour mardi/jeudi 10:00–12:00.
   Les autres fenêtres restent **neutres** (rang non renseigné).
   Les rangs sont portés par les fenêtres, jamais par la couleur.
5. Vérifier dans **Configuration** deux barres le mardi 10:00–12:00,
   un seul total physique de 120 minutes et deux potentiels de 120 minutes
   non additifs. Le mercredi et l'après-midi n'affichent pas de
   préférence implicite. Trois activités superposées restent consultables
   dans la grille et la table.
6. Vérifier le parcours *brouillon → aperçu → reconnaissance des réservations
   futures si présentes → confirmation explicite*. L'aperçu est borné à
   93 jours pour la projection, mais l'inventaire des réservations persistées
   n'est pas borné. Il ne prétend jamais que Google est libre sans vérification.
7. Tester les dates effet futur, invalidité d'heure locale inexistante,
   instants ambigus avec premier/deuxième fold, changement concurrent de rang
   ou de version entre aperçu et confirmation (**409**), et rejeu de
   commande idempotente. Après 409 le brouillon doit rester éditable.
8. Une réservation CONFIRMED et une occupation Google vérifiée doivent être
   respectées par le moteur de placement; l'édition de la permission ne doit
   déplacer ni l'une ni l'autre. Vérifier également les conflits historiques,
   les exceptions ciblées, l'affiliation datée et la capacité non-additive
   entre parents.
9. Sur mobile et avec le clavier, tester barre → détail → édition, prévisualisation,
   validation, erreurs, retour sans sauvegarde et alternative tabulaire.

## Validation

Contrôles ciblés inclus dans cette PR :
- \`tests/test_tp025d_contextual_edit.py\` (SQLite : création, priorités,
  concurrence optimiste, idempotence, transition, réservations et DST);
- \`frontend/e2e/availability.spec.ts\` (Playwright : clavier, mobile,
  persistance du brouillon sur 409, reconnaissance et confirmation explicite);
- suite existante de régression TP-022/023/024 et TP-025A/B/C sans modification
  des anciens contrats.

Commandes de validation locale/CI : \`python -m compileall -q app tests\`,
\`pytest -q\`, \`cd frontend && npm ci && npm run build\`, et la suite
Playwright configurée par le dépôt. Les jobs GitHub de la PR sont l'autorité
pour l'état de CI; cette recette documentaire n'affirme pas leur résultat.

## Limites conservatrices

Les exceptions futures non résolues et les conflits structurels nouvellement
créés **bloquent** la commande : pas d'éditeur des exceptions de permission
ni de conversion automatique du passé. Un changement d'heure/rang peut
nécessiter des séries supplémentaires; il n'y a pas d'édition gestuelle V1.
Google reste une lecture distincte; même un aperçu fondé sur une lecture
vérifiée ne garantirait pas l'état futur de Google.
