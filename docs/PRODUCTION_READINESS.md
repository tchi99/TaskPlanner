# TP-080D — Recette et décision de mise en ligne

**État : procédure préparée, production NON validée.** Ce document est un
protocole de recette et de preuve, pas une attestation que Render ou Supabase
sont déployés. L'issue #33 ne peut être considérée DONE qu'après preuve
opérationnelle et consentement de l'utilisateur. Ne jamais inscrire de tokens,
identifiants de tâches, credentials, copies de données ou emails dans la PR.

## Barrières obligatoires, ordre d'exécution

1. Confirmer explicitement le **projet Supabase dédié**, la propriété du compte,
   le plan de chaque fournisseur, les limites/risques de l'offre gratuite
   (veille du service, indisponibilités, quotas, sauvegardes, rétention,
   bande passante), et tout coût potentiel. **Ne pas acheter ni activer un
   service Render publiquement joignable sans accord humain**. Vérifier que
   les noms du Blueprint ne ciblent aucun service préexistant.
2. Configurer Supabase Auth selon ADR-0018 : inscription publique désactivée,
   fournisseur email/mot de passe nécessaire seulement, compte précréé, UUID
   stable autorisé, JWKS asymétrique RS256/ES256. Vérifier la révocation et
   la suppression de session. Auth Supabase ne protège pas le SQL à lui seul.
3. Réserver le schéma privé \`taskplanner\` selon ADR-0019 et
   \`docs/PRODUCTION_DATABASE.md\`. Confirmer qu'il est absent de Data API >
   Exposed schemas; vérifier les droits effectifs \`anon\` et \`authenticated\`
   (aucun USAGE ni accès aux tables). Chiffrer la connexion SQL avec TLS et
   isoler les secrets sur le backend. Aucune table métier accessible en direct
   depuis React.
4. Préparer un emplacement de backup logique **indépendant** de Supabase
   (stockage chiffré et privé, hors dépôt/Render, politique de rotation et
   test d'accès). Vérifier rétention ET restauration permise par le forfait,
   sans présumer de backups automatiques pour les forfaits gratuits.
5. **Avant toute migration ou activation**, produire un backup logique,
   restaurer ce backup dans **une seconde base temporaire isolée**, valider
   la version Alembic, chaque table, les volumes, les références, l'historique
   et les séquences. Consigner résultat daté sans données privées.
   Ne jamais restaurer sur la base active. Les commandes de préparation
   figurent dans \`docs/PRODUCTION_DATABASE.md\`. L'exercice CI jetable
   ci-dessous ne remplace PAS la preuve de restauration Supabase réelle.
6. Après sauvegarde et accord explicite sur l'exposition publique, créer les
   services Render à partir de \`render.yaml\` (déploiement initial manuel).
   \`autoDeployTrigger: off\` ne bloque **pas** la première publication.
   Configurer les variables backend et frontend séparément suivant
   \`docs/RENDER_DEPLOYMENT.md\`. En production utiliser uniquement
   \`TASKPLANNER_ENV=production\`, \`TASKPLANNER_AUTH_MODE=supabase\`.
7. Lors d'une fenêtre de maintenance, avec un seul exécuteur d'administration,
   vérifier \`alembic current\`, exécuter \`alembic upgrade head\` une seule
   fois, revérifier \`alembic current\`. Démarrer le backend seulement après
   succès. Ne pas exécuter les migrations au démarrage de chaque worker.

## Exercice automatisé local, sans effet sur la production

La CI GitHub \`postgres\` exécute la suite d'intégration TP-080B, puis :

    python -m scripts.verify_disposable_restore

Le script accepte **uniquement** \`TASKPLANNER_PG_TEST_URL\` en
\`postgresql+psycopg\` local vers la base exacte \`taskplanner_test\`;
il exige \`pg_dump\` et \`pg_restore\`. Il crée une base restaurée à nom
aléatoire, compare pour chaque table nombres de lignes et empreintes du
contenu, vérifie révision Alembic et positions des séquences, puis efface
sa **propre base jetable**. Il ne détruit ni ne modifie la source et ne
conserve aucun dump. Il refuse toute URL Supabase ou de production et
n'imprime ni credentials ni données. Ce test prouve la **mécanique locale**
et non l'existence d'un backup indépendant de production.

## Matrice de recette manuelle — preuve à consigner

Créer un document de preuve privé et inscrire : date UTC, SHA livré,
environnements testés, statut, incident et responsable pour chaque bloc.
Ne pas joindre de captures contenant des données personnelles à GitHub.

| Bloc | Vérification requise | Acceptation |
| --- | --- | --- |
| Migration | \`alembic current\` = head, tables dans schéma privé, droits SQL | Pas d'erreur ni droits \`anon\` / \`authenticated\` |
| API | \`/api/health\` sous HTTPS, erreur contrôlée en panne DB | Santé seule publique, aucune fuite d'identifiants |
| Auth | visite anonyme des routes métiers, \`/docs\`, \`/openapi.json\`, JWT absent/invalide/expiré/autre \`sub\` | 401 ou 403; seul compte autorisé voit les données |
| Browser | CORS depuis l'origine exacte et une origine hostile, recharge SPA et URL profonde | Autorisé sur site, origine hostile refusée, pas de fallback HTML sur API |
| Capture | Inbox, création/modification de projet, clarification, tâche, segments | CRUD attendu, aucune mutation silencieuse |
| Plan | contraintes/protection, capacité, time blocks, arbitrages proposés | Option explicable; confirmation avant changement |
| Revues | quotidienne, hebdomadaire, éléments sans prochaine action | Données cohérentes après rechargement |
| Exécution | starter, point de reprise, sessions, projections | Observations non cliniques, révisions correctes |
| Intégrations | Calendar lecture/time blocks et OpenAI, seulement si activés | Erreur externe non destructrice, secret non exposé |
| Devices | téléphone et desktop, connexion/déconnexion, expirations, réseau coupé | Mobile lisible, erreurs compréhensibles, réauthentification |
| Durabilité | créer un enregistrement témoin non personnel; redéployer; reconnecter | Témoin inchangé après redéploiement/reprise |
| Restauration | restore d'un vrai dump sur DB isolée, puis lectures comparées | Tables/volumes/références/historique/séquences validés |
| Secrets | logs Render et navigateur, en-têtes, bundles JS, erreurs | Aucun JWT, URL SQL, mot de passe, token OAuth ou clé secrète |
| Disponibilité | sonde HTTPS de /api/health, erreurs 5xx et quota/veille Render/Supabase | Canal d'alerte et procédure d'escalade confirmés |

**N'effectuer aucune écriture de recette dans des données réelles sans
approbation.** Utiliser un environnement isolé ou un témoin explicitement
autorisé. Une CI verte n'équivaut pas à une recette de production.

## Observabilité, sauvegarde récurrente et alertes

- Configurer une vérification de disponibilité HTTPS de \`/api/health\`
  et un destinataire d'alerte; noter l'heure, la fréquence et le délai
  réel du contrôle. La santé HTTP n'atteste ni la BD ni les JWT.
- Lire les erreurs et redémarrages des services Render, surveiller la
  capacité/quota Supabase et l'expiration des credentials. Ne pas activer
  la journalisation des corps ni des jetons; \`--no-access-log\` est
  configuré dans le Blueprint.
- Définir propriétaire, fréquence, rétention, stockage chiffré externe
  et test périodique de restauration des backups PostgreSQL. Une sauvegarde
  non restaurée n'est pas une preuve de reprise.
- Confirmer les garanties réelles de l'offre choisie auprès des fournisseurs
  au moment de l'activation. Aucun SLA ou backup gratuit n'est présumé.

## Rollback

1. **Geler les écritures** et prévenir le propriétaire; identifier SHA,
   version Alembic, UTC et sauvegarde précédente.
2. Si panne frontend ou backend **sans changement de schéma incompatible**,
   redéployer manuellement le dernier SHA sain, vérifier health, auth et
   lecture/écriture contrôlée. Ne pas activer les déploiements automatiques.
3. Si panne de données ou migration incompatible : maintenir le service
   arrêté, restaurer **une nouvelle base isolée** depuis le backup vérifié,
   comparer schéma et volumes, puis commuter la connexion backend pendant
   une fenêtre autorisée. Ne pas exécuter \`alembic downgrade\` comme
   restauration; ne pas écraser la base défaillante avant enquête.
4. Vérifier les cookies/sessions, cache frontend, CORS, lectures métiers,
   témoins de persistance et intégrations activées. Documenter la décision
   et garder les backups avant toute purge.

## Décision humaine de Go / No-Go

Revue datée à compléter **hors GitHub public** :

- [ ] Supabase dédié et comptes autorisés vérifiés.
- [ ] Render et Supabase : coûts, limites gratuites et risques acceptés.
- [ ] Schéma privé, JWT, CORS, secrets, CI et sécurité validés.
- [ ] Backup externe créé; restauration **réelle** sur cible isolée validée.
- [ ] Matrice desktop + mobile + intégrations activées validée.
- [ ] Persistance après redéploiement et rollback validés.
- [ ] Monitoring et destinataire d'alertes configurés.
- [ ] Accord explicite du propriétaire pour l'exposition publique de l'API.
- [ ] SHA de production, heure UTC, responsable et décision archivés.

Si une case manque : **NO-GO**, garder les services non publiés. La
réconciliation du roadmap TP-080D en DONE est réservée à une recette
opérationnelle réellement attestée après fusion et autorisation humaine.
