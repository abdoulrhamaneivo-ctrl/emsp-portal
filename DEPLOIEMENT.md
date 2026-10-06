# Déploiement EMSP — Vercel, Render et Neon

Ce guide décrit le déploiement de **ce dépôt**. L’architecture conseillée est :

| Service | Rôle |
|---|---|
| **Neon** | Base PostgreSQL : comptes, dossiers, sessions et métadonnées des pièces |
| **Render** | Application FastAPI, pages HTML, API, photos et fichiers téléversés |
| **Vercel** *(facultatif)* | Domaine d’entrée et proxy HTTPS vers Render |

Les pages sont rendues par FastAPI dans `backend/app/ui.py`. `frontend/` contient
les ressources statiques (CSS, JavaScript, logo), pas une application HTML
autonome que Vercel peut publier en « Static Site ». Le proxy Vercel ci-dessous
conserve les URL relatives (`/api`, `/assets`, `/media`) et garde le navigateur
sur un seul domaine. Vercel sait aussi exécuter FastAPI, mais ce projet stocke les
pièces sur le disque local : il faut d’abord connecter un stockage objet durable
avant d’en faire l’hébergeur de production.

## Plan de déploiement recommandé

Déployer en deux temps : une préproduction Render reliée à Neon, puis le domaine
public après validation des parcours. Vercel est facultatif : Render peut servir
directement l’application et son domaine personnalisé avec HTTPS. Garder Vercel en
frontal seulement si le domaine ou une exigence d’architecture le justifie.

| Phase | Action | Critère de passage |
|---|---|---|
| 0 · Versionner | Dépôt privé `abdoulrhamaneivo-ctrl/emsp-portal`, branche `main`. | Dépôt poussé ; `.env`, bases locales et pièces `storage/` ignorés. |
| 1 · Base | Créer Neon dans une région proche de Render et une branche de production. | `DATABASE_URL` est dans le gestionnaire de secrets, jamais dans le dépôt. |
| 2 · Préproduction | Créer le Web Service Render depuis une branche de test et relier Neon. | Le build Docker réussit et `/health` répond `200`. |
| 3 · Données durables | Monter le disque Render sur `/app/backend/storage`; essayer dépôt et téléchargement après redémarrage. | Les pièces et données de test sont conservées. |
| 4 · Mise en ligne | Configurer l’admin, Brevo, `COOKIE_SECURE=true` et l’URL HTTPS canonique. | Connexion, courriels, pièces, convocations et espace admin sont validés. |
| 5 · Domaine | Ajouter le domaine à Render; ajouter Vercel en proxy seulement si nécessaire. | API, sessions, liens par courriel et dépôts fonctionnent sur le domaine final. |

**Décision importante pour les fichiers :** l’application accepte des pièces jusqu’à
5 Mo et les conserve sur le système de fichiers. Le service Render gratuit ne fournit
pas de disque persistant et son système de fichiers est éphémère ; il ne convient
donc pas au portail en production. Le disque persistant est réservé aux services
payants, limite le service à une instance et désactive les déploiements sans
interruption. Si une courte coupure à chaque déploiement ou une instance unique ne
convient pas, migrer d’abord `DocumentStorageService` vers un stockage objet partagé.
Vérifier les tarifs et quotas actuels avant de choisir les offres.

**État au 7 octobre 2026 :** le dépôt privé GitHub est relié à `origin`, sa branche
`main` est publiée, et le CLI Render est authentifié sur `My Workspace`. Le fichier
`render.yaml` décrit le service à créer. Sa création démarre un plan payant et
demande les secrets dans Render.

## 1. Préparer Neon

1. Créer un projet Neon et une branche de production. Choisir une région proche
   du service Render.
2. Dans **Connect**, sélectionner la branche, la base et le rôle applicatif,
   puis copier l’URL PostgreSQL fournie par Neon. La forme ressemble à :

   ```text
   postgresql://ROLE:MOT_DE_PASSE@HOTE.neon.tech/BASE?sslmode=require&channel_binding=require
   ```

3. Garder l’URL complète et ses paramètres SSL. Ne pas la déposer dans Git, dans
   ce document, dans `vercel.json` ou dans les journaux.

L’application convertit l’URL PostgreSQL standard de Neon en dialecte SQLAlchemy
Psycopg 3. Le pilote est installé depuis `backend/requirements.txt`. Le serveur
exécute actuellement `create_all` et ses migrations légères au démarrage ; le
rôle PostgreSQL doit donc pouvoir créer et modifier les tables. Une sauvegarde
est recommandée avant le premier déploiement sur une base déjà utilisée.
Pour commencer, utiliser l’URL directe fournie par Neon. Son URL avec `-pooler`
est disponible si le nombre de connexions concurrentes le justifie.

> Changer `DATABASE_URL` ne copie pas les données de `backend/emsp.db` vers Neon.
> Les fichiers déposés ne sont pas dans PostgreSQL : ils restent dans le stockage
> local. Il faut exporter/importer séparément la base et les pièces si l’on doit
> conserver des données déjà présentes.

## 2. Déployer l’application sur Render

Le dépôt contient maintenant le Blueprint [`render.yaml`](render.yaml). Une fois
créé dans Render, le service utilisera ces réglages :

| Réglage Render | Valeur |
|---|---|
| Root directory | Laisser vide pour utiliser la racine du dépôt |
| Dockerfile path | `backend/Dockerfile` |
| Docker build context | Racine du dépôt (`.`) : le Dockerfile copie `backend/`, `frontend/` et `Photos/` |
| Health check path | `/health` |
| Port | Laisser Render fournir `PORT` (par défaut `10000`) |
| Région | Ohio, proche de l’endpoint Neon `us-east-2` |
| Compute | `0.5c-512mb` : 512 Mo RAM, plan payant |
| Auto-deploy | Chaque commit sur `main` |

Le Dockerfile écoute sur `0.0.0.0:$PORT`. Le build context doit rester la racine,
car le Dockerfile copie `backend/` et `frontend/`. Le `.dockerignore` exclut les
fichiers `.env`, les bases SQLite et le stockage local de l’image. Le répertoire
`Photos/` est copié dans l’image et servi sous `/media`. Au démarrage, le conteneur
prépare les droits du disque puis lance FastAPI sous un compte non privilégié.

### Stockage des pièces

Les justificatifs et convocations sont écrits sous
`DOCUMENT_STORAGE_ROOT=/app/backend/storage`. Attacher un **Persistent Disk**
Render à ce chemin et garder **une seule instance** du service tant que le
stockage est local. Sans disque persistant, les fichiers sont perdus au prochain
redémarrage ou déploiement. Les disques Render nécessitent un service payant,
empêchent de monter plusieurs instances avec ce même disque et désactivent les
déploiements sans interruption : prévoir une courte indisponibilité à chaque
déploiement.

Le Blueprint commence avec un disque de 1 Go. Au tarif Render affiché le
7 octobre 2026, `0.5c-512mb` coûte 7 USD/mois et un disque de 1 Go coûte
0,25 USD/mois, soit environ 7,25 USD/mois hors trafic et taxes. Render autorise
l’agrandissement du disque, mais pas sa réduction.

Pour plusieurs instances ou une architecture sans disque, remplacer d’abord le
stockage `DocumentStorageService` par un stockage objet partagé, puis migrer les
fichiers existants.

### Variables d’environnement Render

Dans **Environment**, ajouter les valeurs suivantes. Garder les clés secrètes
dans Render uniquement.

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | URL Neon complète copiée depuis **Connect** |
| `DOCUMENT_STORAGE_ROOT` | `/app/backend/storage` |
| `COOKIE_SECURE` | `true` |
| `SESSION_EXPIRE_MINUTES` | `120` (ou la durée souhaitée) |
| `APP_PUBLIC_URL` | URL canonique publique, Render ou Vercel |
| `SESSION_SECRET` | Facultatif, actuellement non utilisé par les sessions |
| `ADMIN_EMAIL` | Adresse du premier compte administrateur |
| `ADMIN_PASSWORD` | Mot de passe robuste pour l’initialisation de l’admin |
| `ADMIN_NOM` | Nom affiché, par exemple `Scolarité EMSP` |
| `BREVO_API_KEY` | Facultatif : clé API Brevo v3 |
| `BREVO_SENDER_EMAIL` | Facultatif : expéditeur validé dans Brevo |
| `BREVO_SENDER_NAME` | Facultatif : `EMSP · Portail candidat` |

`SESSION_SECRET` est prévu pour de futurs usages de signature ; le mécanisme de
session actuel utilise des jetons aléatoires opaques enregistrés dans Neon et ne
lit pas cette variable. Elle peut donc être omise pour le déploiement actuel.

`/health` exécute maintenant `SELECT 1` sur la base : un service qui ne peut pas
joindre Neon échoue au contrôle de santé au lieu d’être déclaré prêt.

**Après la création initiale du compte admin**, supprimer `ADMIN_EMAIL` et
`ADMIN_PASSWORD` des variables Render. Au démarrage, ces variables réinitialisent
le mot de passe d’un administrateur déjà présent ; les laisser en place annulerait
un changement de mot de passe effectué depuis le profil.

Les migrations de schéma démarrent automatiquement avec l’application. Ne pas
exécuter `backend/seed_demo.py` en production : il crée des comptes de démonstration.

### Courriels Brevo

Brevo est facultatif. Sans `BREVO_API_KEY` et expéditeur vérifié, le portail reste
utilisable mais les messages de bienvenue et de réinitialisation ne partent pas.
Configurer `APP_PUBLIC_URL` avec l’URL HTTPS réellement utilisée par les candidats
afin que les liens de compte arrivent sur le bon domaine.

## 3. (Facultatif) Mettre Vercel devant Render

Render peut aussi porter directement le domaine personnalisé et son certificat
HTTPS ; Vercel n’est pas requis pour mettre le portail en ligne. Ne pas déployer
FastAPI directement comme Vercel Function avec la configuration actuelle : le
portail accepte des pièces de 5 Mo, alors que les requêtes vers une Vercel Function
sont limitées à 4,5 Mo, et les fichiers doivent rester sur un stockage durable.
Si Vercel est utilisé, garder Render comme origine et valider un téléversement de
5 Mo via le proxy avant le basculement.

Une fois l’application Render déployée, remplacer
`emsp-portail.onrender.com` ci-dessous par son vrai sous-domaine. Ajouter le
fichier suivant **à la racine du dépôt** sous le nom `vercel.json`, puis importer
le dépôt dans Vercel en gardant la racine comme répertoire du projet :

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "rewrites": [
    {
      "source": "/",
      "destination": "https://emsp-portail.onrender.com/"
    },
    {
      "source": "/:path*",
      "destination": "https://emsp-portail.onrender.com/:path*"
    }
  ]
}
```

Les rewrites externes Vercel agissent comme un proxy et laissent l’URL du
navigateur inchangée. Ici, **toutes** les routes sont envoyées à Render, y compris
les formulaires, pages protégées, `/api`, `/assets` et `/media`. Ne pas activer de
cache de proxy pour les pages authentifiées ou les réponses contenant des données
de candidature.

Après avoir associé le domaine de Vercel :

1. Définir `APP_PUBLIC_URL=https://votre-domaine-vercel` dans Render.
2. Garder `COOKIE_SECURE=true` ; les utilisateurs ouvrent le site en HTTPS.
3. Utiliser l’URL Vercel comme adresse communiquée aux candidats. Les appels
   navigateur et API restent sur cette même origine ; le CORS local du projet
   n’a pas à autoriser un domaine Vercel.

Si le site est servi directement depuis Render, ignorer cette section et utiliser
l’URL `https://…onrender.com` comme `APP_PUBLIC_URL`. Ne pas appeler l’API Render
directement depuis une page Vercel sans configurer le CORS du backend : le CORS
actuel est limité aux adresses locales.

## 4. Mise en production et vérification

1. Créer ou connecter le dépôt Git privé, puis pousser la branche de préproduction.
2. Créer Neon, choisir une région proche de Render et définir `DATABASE_URL` sur Render.
3. Déployer le Web Service Render avec le contexte Docker à la racine, attacher le
   disque persistant et renseigner les variables de préproduction.
4. Vérifier `/health`, puis les parcours avec un compte admin et des comptes candidats
   de test dédiés :
   - accueil, logo, photos, `/assets/emsp.css` et `/media` ;
   - création de compte, connexion par e-mail et numéro de dossier, rechargement
     d’une page privée, déconnexion puis reconnexion ;
   - candidat : espace, candidature, pièces, suivi, convocation et résultat ;
   - admin : page admin, décisions, comptes et accès refusé aux pages candidat ;
   - dépôt et téléchargement d’un PDF, puis vérification de sa persistance après
     redémarrage du service ;
   - inscription, oubli et modification du mot de passe par Brevo.
5. Retirer les comptes et données de test. Après création du premier admin, retirer
   `ADMIN_EMAIL` et `ADMIN_PASSWORD`, puis confirmer que l’accès admin fonctionne.
6. Configurer l’expéditeur Brevo vérifié, l’URL publique HTTPS et `COOKIE_SECURE=true`.
7. Ajouter le domaine personnalisé à Render et le définir comme `APP_PUBLIC_URL`.
   Render gère le certificat TLS et redirige HTTP vers HTTPS.
8. Si Vercel est requis, déployer ensuite le proxy, tester toutes les routes et les
   téléversements, puis basculer `APP_PUBLIC_URL` vers le domaine Vercel.
9. Avant l’annonce, sauvegarder Neon et les pièces, vérifier la procédure de
   restauration et observer les logs Render lors du premier jour d’usage.

Le contrôle `/health` vérifie l’accès à Neon. Une réponse `200` à l’accueil ne
prouve pas à elle seule qu’un utilisateur peut se connecter ou que le stockage de
fichiers est persistant : faire aussi les parcours ci-dessus.

### Retour arrière

En cas de problème après le lancement, remettre en service le dernier déploiement
Render connu comme stable. Restaurer Neon seulement si une migration de schéma ou
des données l’exige ; restaurer les fichiers du disque séparément. Un retour arrière
du code n’annule pas les changements de base ni les dépôts faits entre-temps.

## Références officielles

- [Neon — connexion avec une URL PostgreSQL](https://neon.com/docs/get-started/connect-neon)
- [Neon — connection pooling](https://neon.com/docs/connect/connection-pooling)
- [Neon — gestion des connexions et endpoints](https://neon.com/docs/manage/endpoints/)
- [Render — Docker](https://render.com/docs/docker)
- [Render — Blueprint et contexte Docker](https://render.com/docs/blueprint-spec)
- [Render — Web Services et port `PORT`](https://render.com/docs/web-services)
- [Render — Persistent Disks et limites](https://render.com/docs/disks)
- [Render — déploiements sans interruption et disques](https://render.com/docs/deploys)
- [Render — domaines personnalisés et TLS](https://render.com/docs/custom-domains)
- [Render — health checks](https://render.com/docs/health-checks)
- [Render — limites des offres gratuites](https://render.com/docs/free)
- [Vercel — rewrites externes](https://vercel.com/docs/routing/rewrites)
- [Vercel — FastAPI](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel — limite de taille de requête pour les fonctions](https://vercel.com/docs/errors/function_payload_too_large)
