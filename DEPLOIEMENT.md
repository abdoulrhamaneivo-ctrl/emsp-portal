# Déploiement EMSP — démonstration gratuite

Cette configuration sert une **démo publique à 0 €** avec le dépôt GitHub privé `abdoulrhamaneivo-ctrl/emsp-portal` : Vercel sert les ressources statiques, Render exécute FastAPI et Neon fournit PostgreSQL ainsi qu’un bucket privé pour les pièces fictives.

| Service | Utilisation | Offre visée |
|---|---|---|
| Vercel | CSS, JavaScript, logo et photos ; les routes métier sont réécrites vers Render | Hobby |
| Render | FastAPI, pages HTML et API | Web Service Free, sans disque persistant |
| Neon | PostgreSQL isolé et bucket S3 privé `candidate-documents` | Free |

## Limites à connaître

- Render Free met en veille un service après 15 minutes sans trafic, avec un redémarrage qui peut prendre environ une minute. Son disque est éphémère ; ce projet conserve donc les pièces dans le bucket Neon. Render indique que cette offre sert aux tests et aperçus, pas aux applications de production.
- Vercel Hobby est réservé à un usage personnel ou non commercial. Vérifier l’éligibilité de l’usage institutionnel avant une mise en ligne officielle ; le déploiement de ce dépôt est une démonstration.
- Les quotas gratuits sont partagés par compte/projet et peuvent évoluer. Surveiller la consommation Neon, Render et Vercel ; le dépassement peut suspendre le service ou bloquer les déploiements.
- Cette démo est isolée de la branche Neon `production`, reçoit uniquement des comptes synthétiques et affiche un bandeau « Données fictives ». Ne pas y déposer de vrai dossier, identité, résultat ou document étudiant. Ne pas connecter Brevo à cette base de démonstration.

## Architecture et routage

Les pages et interfaces utilisateur sont générées par FastAPI dans `backend/app/ui.py`. Le script `scripts/build-vercel-static.sh` copie seulement `frontend/emsp.css`, `frontend/emsp.js`, les éléments de marque et les photos publiques dans `dist/`. Vercel sert ces fichiers depuis son CDN ; grâce à la priorité des fichiers statiques sur les rewrites, les autres chemins (pages, `/api`, `/health`) sont relayés vers Render. Le navigateur reste sur le domaine Vercel et les cookies de session accompagnent les requêtes.

Le Dockerfile à la racine est requis par le flux Render CLI ; il construit depuis la racine afin d’inclure `backend/`, `frontend/` et `Photos/`. `backend/Dockerfile` reste disponible pour le développement Docker existant.

## Neon — branche et stockage

Le projet Neon `Portail_emsp` (`sweet-block-17253757`, région `aws-us-east-2`) existe déjà. La branche `emsp-demo` est une branche **schema-only** créée depuis `production` : elle reprend la structure sans recopier les dossiers étudiants. Le bucket `candidate-documents` est privé. La branche `production` n’est pas modifiée par cette démo.

Les commandes déjà appliquées :

```sh
neon link --project-id sweet-block-17253757 --branch emsp-demo -y --no-env-pull --no-config
neon deploy --project-id sweet-block-17253757 --branch emsp-demo --no-env-pull
neon env pull --project-id sweet-block-17253757 --branch emsp-demo --file .env.demo --service postgres,object-storage
```

Le fichier `neon.ts` décrit le bucket. `neon deploy` provisionne ses ressources et `neon env pull` écrit les secrets dans `.env.demo`, ignoré par Git. Ne jamais copier ces valeurs dans GitHub, `vercel.json`, une capture d’écran ou les variables publiques Vercel.

Render doit recevoir les variables suivantes dans **Environment** :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | `DATABASE_URL` de `.env.demo` (Neon `emsp-demo`) |
| `APP_PUBLIC_URL` | URL HTTPS Vercel finale |
| `DOCUMENT_STORAGE_BACKEND` | `s3` |
| `DOCUMENT_STORAGE_BUCKET` | `candidate-documents` |
| `AWS_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` de `.env.demo` |
| `AWS_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` de `.env.demo` |
| `AWS_ENDPOINT_URL_S3` | `AWS_ENDPOINT_URL_S3` de `.env.demo` |
| `AWS_REGION` | `us-east-2` |
| `COOKIE_SECURE` | `true` |
| `DEMO_MODE` | `true` |

Le bucket reste privé : seuls le backend Render doté des credentials Neon et les contrôles d’accès de l’application peuvent lire les pièces. Le code continue à utiliser le stockage local en développement (`DOCUMENT_STORAGE_BACKEND=filesystem`).

Pour exécuter la démo de comptes et pièces fictifs, télécharger les variables de la branche dans un `.env` local non versionné (`backend/.env`), puis exécuter depuis `backend/` :

```sh
neon env pull --project-id sweet-block-17253757 --branch emsp-demo --file backend/.env --service postgres,object-storage
python seed_demo.py --mot-de-passe 'CHOISIR-UN-MOT-DE-PASSE-DEMO'
```

Le script crée des utilisateurs `@demo.emsp.ci`, deux comptes d’administration de démonstration et des pièces PDF factices. Il n’écrase pas les comptes déjà présents. Après usage, retirer `backend/.env` du poste si les secrets ne doivent plus y rester. Les identifiants de démo ne doivent jamais être réutilisés par un vrai candidat ou un administrateur.

## Render — créer le service gratuit

Le fichier `render.yaml` décrit le Web Service Free et ses variables. Depuis le Dashboard Render, créer un **Blueprint** avec le dépôt GitHub privé `abdoulrhamaneivo-ctrl/emsp-portal`, choisir le plan `Free`, puis fournir les secrets du tableau Neon ci-dessus dans le gestionnaire d’environnement Render. Aucun disque Render ne doit être attaché. Garder la région Ohio, la branche `main`, le Dockerfile `Dockerfile`, le contexte `.` et le contrôle `/health`.

`/health` est un contrôle de vie sans requête DB pour ne pas maintenir Neon éveillé en permanence. `/ready` vérifie explicitement la connexion PostgreSQL après le démarrage. Les deux appels sont manuels pour diagnostiquer un déploiement ; seul `/health` est configuré dans Render.

Récupérer ensuite le domaine fourni par Render, par exemple `https://emsp-portal.onrender.com`. Si Render attribue un autre sous-domaine, remplacer la destination externe dans `vercel.json` avant le déploiement Vercel.

## Vercel — publier les ressources et le proxy de pages

Vercel CLI doit être authentifié (`vercel login`). Depuis la racine du dépôt :

```sh
vercel link
vercel deploy --prod
```

Associer le dépôt privé GitHub au projet Vercel pour activer les futurs déploiements. Conserver `dist` comme répertoire de sortie et `sh scripts/build-vercel-static.sh` comme commande de build. Le fichier `vercel.json` contient les rewrites Render ainsi que les règles de cache des ressources statiques. Aucun secret Neon, Render ou Brevo n’est nécessaire dans Vercel.

Si un déploiement Git est bloqué parce que Vercel ne reconnaît pas l’auteur du commit, configurer localement `git config user.email` avec l’adresse vérifiée du compte GitHub relié au projet Vercel, puis pousser un nouveau commit.

Après publication, copier l’URL HTTPS Vercel dans `APP_PUBLIC_URL` sur Render, redéployer puis vérifier `/`, `/connexion.html`, `/api`, les photos et les fichiers statiques. Vercel Hobby ayant des conditions d’usage spécifiques, ne pas utiliser cette configuration gratuite comme portail officiel sans confirmer que l’usage non commercial de l’école est admissible.

## Vérification de démonstration

1. `https://<domaine-render>/health` répond `{"status":"ok"}` ; `/ready` répond `{"status":"ready","database":"ok"}`.
2. Le domaine Vercel affiche l’accueil, ses images et son bandeau de démonstration ; ses routes métier répondent à travers Render.
3. Se connecter aux comptes `@demo.emsp.ci` créés avec le mot de passe de démo choisi ; vérifier candidat, pièces, convocation, résultat et administration.
4. Déposer puis télécharger une pièce fictive pour confirmer le trajet Render → bucket Neon privé.
5. Ne pas configurer Brevo ou un domaine institutionnel réel avant le passage à une architecture de production, un avis de l’école sur la protection des données et un plan de sauvegarde.

## Retour à un environnement propre

Supprimer `backend/.env` et `.env.demo` du poste. Les déploiements restent sur les offres gratuites tant que les plans sont `Free`/`Hobby`, mais ils ne garantissent ni disponibilité continue ni SLA. Les limites gratuites ne constituent pas un hébergement adapté à des dossiers scolaires réels.
