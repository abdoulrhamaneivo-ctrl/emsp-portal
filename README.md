# EMSP — Portail de candidature

Le candidat ne « s'inscrit » pas : il **cande**. Toute l'expérience tient dans
un seul fil conducteur — de l'accueil à l'admission.

Pour l’hébergement du portail avec **Vercel, Render et Neon**, voir
[le guide de déploiement](DEPLOIEMENT.md).

```
Découvrir → Candidater (numéro de dossier) → 7 étapes → Soumettre
         → Suivi → Convocation → Résultat
```

## L'institution et le concours

Le portail est celui de l'**École Multinationale Supérieure des Postes**
(EMSP), école intergouvernementale créée en 1970 sous l'égide de l'Union
Postale Universelle par huit pays d'Afrique de l'Ouest. Siège à Treichville,
Abidjan.

L'entrée en **Licence 1** (Formation Spécialisée, FS MENUM) se fait par
concours. Cinq spécialités sont ouvertes :

| Code | Spécialité | Ce qu'on y apprend | Débouché |
|------|-------------|--------------------|----------|
| **LNUM** | Logistique et Numérique | gestion des flux, du transport et de l'entreposage | exploitant logistique, gestionnaire de flux |
| **FDIG** | Finance Digitale | comptabilité, finance d'entreprise, paiements numériques | comptable, analyste financier |
| **MDIG** | Marketing Digital | étude de marché, communication, commerce numérique | chargé de marketing digital, community manager |
| **DSER** | Digitalisation des Services | conception de services numériques, conduite du changement | chef de projet numérique, analyste de processus |
| **GARE** | Gestion des Activités Régulées de l'Économie | cadre juridique des activités économiques, régulation | chargé de régulation, contrôleur |

Séries de baccalauréat admises : **A, B, C, D, F1, F2, G2**.

Ces valeurs ont **une seule source de vérité côté serveur**
(`backend/app/schemas.py`). Le front et le serveur n'ont jamais le droit de
diverger : c'est arrivé une fois, avec une liste de six filières qui
n'appartenaient à aucun concours de cet établissement pendant que le serveur
en refusait cinq. Deux tests verrouillent l'alignement
(`test_les_cinq_specialites_du_concours_sont_acceptees`,
`test_le_front_et_le_serveur_annoncent_la_meme_pecialite`).

## Les 7 étapes (source de vérité : `frontend/js/parcours.js`)

| | Étape | Contenu |
|---|---|---|
| I | Informations personnelles | identité, pièce d'identité, coordonnées, résidence, code TrésorPay |
| II | Parcours académique | année/série du bac, n° bac et table, mention, moyenne, 4 notes |
| III | Choix de formation | 6 filières, choix 1 obligatoire, choix 2 facultatif, jamais identiques |
| IV | Tuteurs | tuteur 1 obligatoire (nom, contact, lien, résidence), tuteur 2 facultatif |
| V | Pièces justificatives | les 10 pièces, PDF/JPG/PNG, 5 Mo, remplacement et retrait |
| VI | Vérification | résumé des 5 rubriques + « Modifier » vers l'étape concernée |
| VII | Soumission | certification, envoi au jury, verrouillage du dossier |

Puis, une fois soumis : **Suivi** (chronologie), **Convocation** (date, centre,
document), **Résultat** (décision et filière).

## Qui voit quoi

| État | Pages accessibles |
|---|---|
| Anonyme | Accueil, Conditions, **Candidater** (ouvre le dossier), Contact, Connexion |
| Connecté | Mon espace, Ma candidature, Mes pièces, Suivi, Convocation, Résultat, Profil |

Toutes les pages protégées cachent leur contenu tant que la session n'est pas
validée (`js/session.js` : `requireAuth` → `/connexion.html?next=…`).
Le cookie de session `emsp_session` est HttpOnly + SameSite, expire au bout de
2 h et se renouvelle tant que le candidat travaille.

## Arborescence

- `backend/app/` — API FastAPI : `routes_auth.py` (accès, session glissante,
  `logout-all`), `routes_candidature.py` (7 étapes, `submit` exige 10/10 pièces
  + champs requis), `routes_documents.py` + `storage_service.py` (fichiers hors
  base, dans `storage/candidats/{numero_dossier}/{type}/`, métadonnées en base),
  `routes_misc.py` (convocation, admission, contact).
- `backend/tests/test_emsp.py` — 10 tests (parcours complet, upload/IDOR,
  contact, sessions, soumission sans pièces).
- `frontend/` — interface servie en `/` : 14 pages, `js/parcours.js` porte les 7 étapes
  et les 10 pièces ; `js/session.js` la session ; `js/nav.js` l'en-tête et le pied
  factorisés, dépendants de la session ; `admin.html` + `js/admin.js` l'espace
  d'administration. Le style vient de `css/app.css`, **compilé** (voir « Styles »).

> L'ancien `frontend-v2/` a été retiré : c'est lui que les pages et scripts actuels
> remplaçaient. Son vocabulaire de classes a été récupéré dans `frontend/src/legacy.css`
> parce que le markup en dépendait toujours.

## Styles — une feuille, compilée

Le CSS n'est **plus compilé dans le navigateur** (Play CDN retiré : il rendait 12 pages
sur 14 entièrement sans style). Il est compilé localement et versionné :

```
frontend/src/app.css + frontend/src/legacy.css
  + frontend/tailwind.config.js
        │  cd frontend && npm run build:css
        ▼
frontend/css/app.css      ← la feuille que sert le portail
```

Les 14 pages ne déclarent qu'un `<link rel="stylesheet" href="./css/app.css">`.
Le détail des tokens, de la palette et des composants est dans **[DESIGN.md](DESIGN.md)**.

Palette institutionnelle : **vert `#056839`** (structure) et **jaune `#FFDC00`**
(action principale, couleur du logo), sur papier chaud `#F6F5F1`. L'encre est un noir
adouci `#16191A`. Une seule famille : **Public Sans**, monospace réservé aux numéros de
dossier et codes de spécialité.

**Photos** : `frontend/img/` (issues de `Photos/`, optimisées 1200–1600 px).
Le logo officiel `frontend/img/logo.png` (341×110, fourni par l'école) est affiché
dans l'en-tête via `frontend/js/nav.js` (`LOGO_OFFICIEL_PRESENT = true`, 136×44) ;
le monogramme ne sert que de repli. Favicon + apple-touch-icon sur les 14 pages.

## Administration

Le super admin gère **toutes** les soumissions. Le lien « Administration » n'apparaît
que pour lui, et le serveur refuse tout le reste.

```bash
cd backend
python3 -m app.admin_cli create --email admin@emsp.ci --password '…' --nom "Scolarité"
python3 -m app.admin_cli list          # lister les comptes
```

Variables d'environnement équivalentes (création automatique au démarrage) :
`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NOM` — sans elles, aucun compte privilégié
n'existe.

Ce que fait l'administration : vue d'ensemble (compteurs), liste filtrable de tous les
dossiers, fiche complète (identité, bac, notes, tuteurs, 10 pièces), décision du jury
(statut, filière, date et centre de composition, notes d'admission, note interne),
dépôt de la convocation officielle, messagerie, comptes, et **journal des actions**.

Sécurité : rôle vérifié côté serveur sur chaque route (403 pour un candidat, 401 anonyme),
téléchargement de pièce toujours journalisé, aucune donnée d'administration renvoyée
au candidat.

Routes : `GET /api/admin/overview`, `GET /api/admin/candidatures`,
`GET|PATCH /api/admin/candidatures/{n}`, `POST /api/admin/candidatures/{n}/statut`,
`GET /api/admin/documents/{id}/download`, `POST /api/admin/candidatures/{n}/convocation`,
`GET /api/admin/messages`, `GET /api/admin/comptes`.

```
Anonyme : Accueil · Conditions · Candidater · Contact
Candidat : Mon espace · Ma candidature · Mes pièces · Suivi · Convocation · Résultat · Profil
Admin    : Administration · Contact · Profil
```

## Lancement

```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000
```

Puis <http://localhost:8000/>. Contrôle de santé : `GET /health`.

## Jeu de démonstration

Une commande crée des dossiers à **tous les stades** du parcours, avec de vrais PDF,
pour tester l'administration sans remplir sept formulaires.

```bash
cd backend
python3 seed_demo.py            # crée ce qui manque
python3 seed_demo.py --reset    # supprime puis recrée
```

| Compte | Mot de passe | État | Ce qu'il permet de vérifier |
|---|---|---|---|
| `brouillon@demo.emsp.ci` | `DemoEmsp2026` | brouillon, 1/7 | le formulaire vide, la reprise |
| `presque@demo.emsp.ci` | `DemoEmsp2026` | brouillon, 5/7, 0/10 pièces | le blocage « 10 pièces manquantes » |
| `soumis@demo.emsp.ci` | `DemoEmsp2026` | dossier soumis, 10/10 | la liste admin, le suivi |
| `convoque@demo.emsp.ci` | `DemoEmsp2026` | composition programmée | la page convocation + le PDF officiel |
| `admis@demo.emsp.ci` | `DemoEmsp2026` | **admis** (LNUM — Logistique et Numérique) | la page Résultat célébratoire |
| `refuse@demo.emsp.ci` | `DemoEmsp2026` | non retenu | le refus, et le motif **invisible** du candidat |
| `admin@emsp.ci` | `AdminEmsp2026` | administration | toutes les soumissions, décisions, journal |
| `directeur@emsp.ci` | `AdminEmsp2026` | administration | second compte admin |

Les pièces sont de vrais PDF lisibles, déposés dans
`backend/storage/candidats/CDT_XXXX/<type>/`. Les comptes de démo sont
reconnaissables à leur adresse `@demo.emsp.ci` (et `admin@emsp.ci`).

Ces identifiants sont réservés au développement et à la démonstration. Le
script sans option crée uniquement les dossiers absents et conserve les comptes
déjà présents.

## Courriels transactionnels Brevo

Le portail peut envoyer un courriel de bienvenue à la création du compte, un
lien de réinitialisation à usage unique (30 minutes par défaut), puis une
notification après modification du mot de passe. Les envois restent inactifs
tant qu’une clé API et une adresse expéditeur vérifiée ne sont pas configurées.

Depuis `backend/`, copiez `.env.example` vers `.env`, puis renseignez :

```dotenv
BREVO_API_KEY=votre_cle_api_v3
BREVO_SENDER_EMAIL=portail@votre-domaine.ci
BREVO_SENDER_NAME=EMSP · Portail candidat
APP_PUBLIC_URL=https://portail.votre-domaine.ci
```

Gardez la clé API uniquement dans l’environnement du serveur et activez HTTPS
sur le domaine public avant d’utiliser les liens de réinitialisation en production.

## Agents d'interface

Trois agents ont travaillé en parallèle sur des périmètres disjoints, sous
un contrat d'interface commun. Le point de méthode compte autant que le
résultat.

**`DOSSIER-INTERFACE.md`** est ce contrat : échelles d'espacement, quatre
voix typographiques, palette, composants existants, seuils de
lisibilité. Sans lui, trois agents produisent trois interprétations
différentes du même bouton, et le site devient incohérent — ce qu'il
était précisément avant.

**Le partage de fichiers est la vraie difficulté.** Le CSS est global par
nature : deux agents qui éditent `app.css` se marchent dessus. Chaque
agent s'est donc vu attribuer des fichiers disjoints, avec interdiction
explicite de toucher aux feuilles partagées, et le droit de créer **une**
feuille qui lui appartient. Ses besoins de règles partagées il les
remonte, il ne les édite pas. C'est ce qui a permis de corriger ensuite,
sur un seul fichier, un défaut qui touchait six pages.

```
frontend/src/app.css        appartient à l'agent « style partagé »
frontend/src/legacy.css     vocabulaire métier,lecture seule
frontend/js/texte.js        langue : accord et énumération
```

### La langue fait partie de l'interface

`js/texte.js` centralise l'accord en nombre. « 10 pièce(s) manquante(s) »
était l'action principale du site pour un candidat : sur une application
institutionnelle française, c'est le détail qui fait crier « provisoire »
plus fort que n'importe quel défaut de mise en page.

```js
accord(1, 'pièce', 'pièces')                 // « 1 pièce »
accord(10, 'pièce', 'pièces')                // « 10 pièces »
avecArticle(0, 'dossier', 'dossiers')        // « aucun dossier »
enumeration(10, 3, ['Attestation', 'Relevé']) // « Attestation, Relevé et 8 autres »
```

Règle : 0 et 1 au singulier, le pluriel à partir de 2. Les nombres
s'écrivent à la française — « 12,75 », jamais « 12.75 ».

### Nettoyer après une campagne de tests

```bash
cd backend
python3 nettoyer_comptes_test.py --apercu   # voir
python3 nettoyer_comptes_test.py           # supprimer
```

Ne touche que les comptes `test-*` : comptes de démonstration, dossiers
et pièces sont intacts, et les répertoires de fichiers orphelins partent
avec la base.


## Vérification des dossiers

L'administration compare chaque dossier à ses propres pièces. **Elle
signale, elle ne décide jamais** : aucun chemin de vérification n'écrit
dans `candidatures`, et un test le prouve.

### Ce qui est contrôlé aujourd'hui

Aucun réseau, aucun modèle, aucun coût. Le SHA-256 étant déjà calculé à
chaque dépôt, ces contrôles sont gratuits et immédiats.

| Contrôle | Constat | Gravité |
|---|---|---|
| `doublon_piece` | fichier identique au bit près sur un **autre** dossier | majeur |
| `nature_fichier` | le contenu n'est pas le format enregistré (PDF renommé en image) | majeur |
| `origine_fichier` | produit par un logiciel d'images ; image sans trace d'appareil ; fichier modifié plus d'un jour après son dépôt | mineur / info |
| `coherence_notes` | note hors de l'échelle 0-20 ; moyenne annoncée hors de la bande des notes saisies | majeur / mineur |
| `coherence_temps` | année du bac dans le futur ; date de naissance future ; âge au bac anormal | majeur / mineur |

Un contrôle qui ne peut pas conclure produit un constat **indéterminé**,
jamais « conforme ». Un seuil heuristique est annoncé comme tel dans le
message : la moyenne du bac porte sur une dizaine de matières, pas sur les
quatre notes saisies.

### Ce que la machine ne fera pas

Rien ne s'appelle « vérification d'authenticité » dans ce logiciel, et le
mot est absent du rapport. Ce que l'outil mesure, c'est la **cohérence**
entre ce que le candidat déclare et ce que sa pièce dit. Savoir si un
relevé a été réellement délivré par un établissement est une question à
poser à l'établissement : aucun modèle n'y répond, et une réponse
inventée serait pire que l'absence de réponse. Le rapport réserve la
place pour que le jury consigne sa propre vérification.

### Utilisation

Dans la fiche dossier, un bloc **« Contrôles de cohérence »** s'affiche
entre les pièces et la décision du jury. Le bouton lance l'analyse ; le
rapport est ensuite joint à la fiche. Lancer les contrôles est journalisé
(`VERIFICATION_LANCEE`) ; **consulter** le rapport ne l'est pas — ouvrir
une fiche n'est pas un acte d'administration.

```
POST /api/admin/candidatures/{numero}/controles   lance et rend le rapport
GET  /api/admin/candidatures/{numero}/controles   rapport déjà calculé
```

Pour éprouver le rapport sur un dossier volontairement douteux :

```bash
cd backend
python3 outils_dossier_fictif.py            # rend le dossier CDT_0004 suspect
python3 outils_dossier_fictif.py restaurer  # remet les valeurs d'origine
```

### Lecture assistée du contenu des pièces par un modèle

**Désactivée par défaut** : aucun appel réseau sans configuration serveur
complète et accord candidat horodaté. Les contrôles déterministes fonctionnent
toujours sans IA. L'interface retenue est celle de l'API OpenAI Chat
Completions, ce qui couvre d'un seul code :

| Cible | `VERIF_BASE_URL` |
|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` |
| OpenAI | `https://api.openai.com/v1` |
| modèle servi en local (vLLM, Ollama) | `http://localhost:8000/v1` |

La dernière ligne mérite d'être connue : en gardant cette interface, on
peut basculer sur un modèle vision **local**, et les pièces de mineurs
cessent alors de quitter le serveur. Ce n'est pas un autre projet, c'est
une ligne de configuration.

Dans Render, renseignez `VERIF_ACTIF=true`, `VERIF_BASE_URL`, `VERIF_CLE_API`
et `VERIF_MODELE`. Les PDF textuels sont lus sur le serveur ; les JPG/PNG
nécessitent un modèle vision compatible. `VERIF_PIECES_MAX` vaut 3 par défaut
pour limiter les appels. Les pièces ne partent vers le fournisseur qu'après
consentement explicite ; le modèle ne décide jamais d'une admission et ne
certifie pas l'authenticité d'un document. La lecture d'une image ou l'appel
du modèle peut consommer un quota ou être facturé par le fournisseur.

En local, les mêmes variables peuvent être renseignées dans `backend/.env`,
ignoré par Git. Une clé ne doit jamais être versionnée.

### Consentement du candidat

Étape 7 du formulaire, dans un encadré distinct de la certification
d'exactitude : l'un porte sur les informations, l'autre sur le traitement
des documents. Le refus est explicite et **n'empêche jamais de déposer un
dossier** — le candidat est alors examiné normalement, sans contrôle
automatisé. Un consentement est horodaté ; un accord sans date n'est pas un
accord.


## Agent de vérification

```bash
python3 tools/verif.py           # vérifie, répare, rend compte + diff
python3 tools/verif.py --check   # signale sans rien toucher
```

Une commande. Elle démarre l'API, ouvre un vrai navigateur et mesure
**36 rendus** (12 pages × 3 largeurs : 390, 900, 1440 px), puis rend
compte.

### Ce qu'il mesure

| Famille | Exemple de constat |
|---|---|
| Lisibilité | texte à 1,4:1 sur fond clair (seuil AA : 4,5:1) |
| Typographie | corps sous 11 px, ligne de plus de 105 caractères |
| Mise en page | débordement hors écran, texte tronqué, en-tête épaissi |
| Ergonomie | cible tactile sous 24 px (norme) ou 36 px (confort) |
| Parcours | 7 étapes, 10 pièces, 6 états de candidature, 10 pièces entières |
| Sécurité | motif interne de refus exposé, API d'administration hors session |

Chaque écart porte sa mesure et son seuil : « 1,38:1, attendu 4,5:1 ».
Aucun n'est une impression.

### Ce qu'il corrige, et ce qu'il refuse de corriger

Il ne répare que les défauts dont la **cause est mesurée** :

- contraste insuffisant → il calcule la teinte qui atteint le seuil en
  gardant la teinte d'origine, et réutilise un jeton du site
  (`var(--blanc)`) quand elle s'en approche ;
- cible tactile sous la norme → il agrandit la cible.

Tout le reste est **constaté, pas deviné** : un titre tronqué, un
chevauchement, un parcours cassé n'ont pas de correction universelle.
Inventer une règle pour ces cas-là produirait plus de dégâts que de
réparations.

Trois garde-fous :

1. **CSS seulement.** Jamais de JavaScript, de balisage métier, de Python
   ni de base. Une régression fonctionnelle n'est pas un défaut d'apparence.
2. **Confirmation par la mesure.** Une correction n'est retenue que si la
   re-mesure confirme l'effet. Sinon elle est annulée.
3. **Annulation sur régression.** Si le re-contrôle du parcours ou de la
   sécurité détecte une régression, **tout** est remis à l'état initial et
   l'agent s'arrête avec un code de sortie dédié.

Les corrections sont écrites dans `frontend/css/verif-repares.css`,
régénéré à chaque exécution, et le diff est affiché. Rien n'est conservé
sans que la mesure le justifie.

### Calibrage

Un rapport qui cries au loup ne sert à rien. Deux réglages :

- **24 px** est le minimum de la norme (WCAG 2.5.8, AA) ; **36 px** est une
  question de confort. Un écart entre les deux est signalé *mineur*, pas
  *majeur*.
- Les liens insérés **dans une phrase** (« Pas encore de dossier ? Candidater
  maintenant. ») sont exclus : la norme les exempte, et les agrandir
  casserait le paragraphe.

### Prérequis

Playwright **Node** dans un projet voisin (`node_modules/playwright`) et
son Chromium installé dans `~/.cache/ms-playwright`. L'agent choisit
automatiquement le paquet dont le build de navigateur est présent — plusieurs
versions coexistent sur cette machine et ne demandent pas la même.

Le limiteur de connexion est désactivé **sur le serveur de test que l'agent
lance lui-même** (il ouvre des dizaines de sessions). La valeur du site reste
à 5 tentatives/minute/IP et est vérifiée par les tests.


## Tests

```bash
cd backend && python3 -m pytest tests/ -q      # 16 passed (dont 6 sur l'administration)
```

## Docker

```bash
docker build -f backend/Dockerfile -t emsp-portal .
docker run --rm -p 8000:10000 -v emsp-storage:/app/backend/storage emsp-portal
```
