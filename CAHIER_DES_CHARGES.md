# Cahier des charges — Portail de candidature EMSP

**Projet** : EMSP — Portail de candidature
**Établissement** : École Multinationale Supérieure des Postes (EMSP), école
intergouvernementale créée en 1970 sous l'égide de l'Union Postale Universelle
par huit pays d'Afrique de l'Ouest. Siège à Treichville, Abidjan.
**Entrée concernée** : Licence 1 — Formation Spécialisée (FS MENUM), par concours.
**Fil conducteur du produit** :

```
Découvrir → Candidater (numéro de dossier) → 7 étapes → Soumettre
         → Suivi → Convocation → Résultat
```

> Le candidat ne « s'inscrit » pas : il **cande**. Toute l'expérience tient
> dans ce seul fil, de l'accueil à l'admission.

---

## 1. Contexte et objectifs

Le portail remplace l'inscription papier au concours d'entrée de l'EMSP.
Il doit permettre à un candidat de :

1. découvrir l'institution, le concours et ses conditions ;
2. créer un dossier de candidature (numéro de dossier `CDT_XXXX`) et le
   remplir en **7 étapes** ;
3. déposer **10 pièces justificatives** ;
4. soumettre son dossier au jury (verrouillage) ;
5. suivre son dossier, recevoir sa convocation et consulter son résultat.

Il doit permettre à l'administration de :

- piloter tous les dossiers (liste, filtres, fiche complète) ;
- prendre la décision du jury (statut, filière, notes, date et centre de
  composition) ;
- déposer la convocation officielle ;
- lire les messages de contact et gérer les comptes ;
- disposer d'un journal des actions et de contrôles de cohérence automatisés.

**Contrainte structurante** : les référentiels métier (spécialités, séries)
n'ont **qu'une seule source de vérité côté serveur** (`backend/app/schemas.py`).
Le front et le serveur ne doivent jamais diverger — une divergence a déjà eu
lieu (six filières n'appartenant à aucun concours de l'établissement pendant
que le serveur en refusait cinq).

## 2. Le concours

Cinq spécialités ouvertes (source de vérité : `backend/app/schemas.py`) :

| Code | Spécialité | Débouché |
|------|------------|----------|
| **LNUM** | Logistique et Numérique | exploitant logistique, gestionnaire de flux |
| **FDIG** | Finance Digitale | comptable, analyste financier |
| **MDIG** | Marketing Digital | chargé de marketing digital, community manager |
| **DSER** | Digitalisation des Services | chef de projet numérique, analyste de processus |
| **GARE** | Gestion des Activités Régulées de l'Économie | chargé de régulation, contrôleur |

Séries de baccalauréat admises : **A, B, C, D, F1, F2, G2**.
Mentions admises : Passable, Assez Bien, Bien, Très Bien, Excellent.

> Écart historique à ne pas reproduire : les intitulés « Prépa Scientifique,
> Informatique, Génie logiciel, Infographie, Création digitale, Prépa
> Économique » ne correspondent à **aucune** formation de l'EMSP.

## 3. Acteurs et droits

| Acteur | Pages accessibles | Droits |
|--------|-------------------|--------|
| Anonyme | Accueil, Conditions, Candidater (ouvre le dossier), Contact, Connexion | créer un compte/dossier |
| Candidat (`CANDIDAT`) | Mon espace, Ma candidature, Mes pièces, Suivi, Convocation, Résultat, Profil | **son seul dossier** (ownership stricte) |
| Administration (`ADMIN`) | Administration, Contact, Profil | toutes les soumissions, décisions, journal |

Le lien « Administration » n'apparaît que pour un admin ; le serveur refuse
tout le reste (403 pour un candidat, 401 pour un anonyme).

## 4. Périmètre fonctionnel

### 4.1 Authentification et compte

- `POST /api/auth/register` — crée en une transaction un dossier `DRAFT`
  (`CDT_XXXX` généré serveur) **et** un compte, puis ouvre la session.
  Rate-limit inscription : 5 tentatives/min/IP.
- `POST /api/auth/login` — rate-limit connexion : 5 tentatives/min/IP.
- `POST /api/auth/logout` et `POST /api/auth/logout-all` (révoque toutes
  les sessions).
- `GET /api/me` — identité de session (rôle, dossier, étape courante).
- Session : cookie `emsp_session` **HttpOnly + SameSite=Lax**, 2 h, **glissante**
  (renouvelée tant que le candidat travaille) ; token opaque stocké en base
  (`sessions`), jamais dérivé du contenu. Mots de passe hashés bcrypt.

### 4.2 Les 7 étapes de la candidature

Source de vérité front : `frontend/js/parcours.js`. PATCH côté serveur :
`routes_candidature.py` (whitelist de champs, `etape_courante` ne régresse
jamais : `max(existante, fournie, inférée)`).

| Étape | Contenu | Champs requis |
|-------|---------|---------------|
| I | Informations personnelles : identité, pièce d'identité, coordonnées, résidence, code TrésorPay | nom, prénoms, sexe, date de naissance, lieu de naissance, nationalité, nature de pièce (CNI / Attestation d'identité / Passeport / Carte consulaire), n° pièce, email, téléphone, commune, ville, adresse |
| II | Parcours académique : année/série du bac, n° bac et n° table, mention, moyenne, 4 notes (math, physique, français, anglais) | année, série, n° bac, n° table, mention, moyenne, choix 1 |
| III | Choix de formation : 5 spécialités, choix 1 **obligatoire**, choix 2 facultatif, **jamais identiques** | choix 1 |
| IV | Tuteurs : tuteur 1 obligatoire (nom, contact, lien, résidence), tuteur 2 facultatif | tuteur 1 complet |
| V | Pièces justificatives : les 10 pièces, remplacement et retrait | 10/10 au dépôt |
| VI | Vérification : résumé des rubriques + « Modifier » vers l'étape concernée | — |
| VII | Soumission : certification, envoi au jury, verrouillage du dossier | confirmation |

**Contrôles de validation** (messages en français, HTTP 422) : email valide,
téléphone, note 0–20, année de bac cohérente, date de naissance passée,
deux choix de spécialité distincts. En cas de conflit (email / code TrésorPay
déjà utilisés) : HTTP 409.

### 4.3 Pièces justificatives

Les 10 pièces exigées (`TYPES_DOCUMENTS_REQUIS`, aligné sur
`storage_service.TYPES_AUTORISES`) :

`attestation_bac`, `releve_notes_bac`, `piece_identite`, `bulletins_seconde`,
`bulletins_premiere`, `bulletins_terminale`, `photo_identite`,
`lettre_motivation`, `acte_naissance`, `cv`.

- Formats : PDF / JPG / PNG, **5 Mo** maximum, **magic bytes** vérifiés
  (anti-renommage), exécutables et doubles extensions rejetés.
- Upsert par `(numero_dossier, type_document)` : remplacement atomique,
  ancien fichier supprimé après succès du nouveau.
- Stockage : fichiers **hors base**, dans `storage/candidats/CDT_XXXX/<type>/`,
  chemins **relatifs** en base (`candidats/...`), écriture atomique,
  `chmod 0o640`, SHA-256 calculé à chaque dépôt.
- Rate-limit upload : 20/min/(IP + dossier).
- Téléchargement : ownership stricte (403 sinon), `Content-Disposition: attachment`,
  aucun chemin absolu jamais exposé.
- Le type `convocation` est interne : un candidat ne peut jamais le déposer.

### 4.4 Soumission (`POST /api/candidature/submit`)

Conditions **toutes** requises : certification `confirmation: true`, champs des
étapes 1–3 complets, **10/10 pièces** déposées, choix 1 renseigné et distinct
du choix 2. Effets : `DRAFT → SUBMITTED`, `dossier_valide = true`,
`submitted_at`, `etape_courante = 7`, dossier verrouillé (409 si déjà soumis).

### 4.5 Suivi, convocation, résultat

- Suivi (`/suivi`) : chronologie du dossier (`historique_statut`).
- Convocation : date, centre et document officiel (PDF généré serveur,
  type `convocation`) — `GET /api/candidature/convocation[/download]`.
- Résultat : décision et filière (`GET /api/candidature/admission`). Le
  **motif interne de refus** (`motif_refus`) et la note interne ne sont
  **jamais** renvoyés au candidat.

### 4.6 Administration (`routes_admin.py`, rôle ADMIN)

| Route | Fonction |
|-------|----------|
| `GET /api/admin/overview` | vue d'ensemble (compteurs) |
| `GET /api/admin/candidatures` | liste filtrable de tous les dossiers |
| `GET /api/admin/candidatures/{n}` | fiche complète (identité, bac, notes, tuteurs, 10 pièces) |
| `PATCH /api/admin/candidatures/{n}` | correction administrative |
| `POST /api/admin/candidatures/{n}/statut` | décision du jury : statut, filière, date/centre de composition, notes d'admission, note interne |
| `GET /api/admin/documents/{id}/download` | téléchargement de pièce (**toujours journalisé**) |
| `GET /api/admin/candidatures/{n}/document/{type}` | pièce par type |
| `POST /api/admin/candidatures/{n}/convocation` | dépôt de la convocation officielle |
| `GET/PATCH /api/admin/messages[/{id}]` | messagerie de contact |
| `GET /api/admin/comptes`, `POST /api/admin/comptes/admin` | comptes |

Journal des actions (`actions_admin`) : qui, quoi, sur quel dossier, quand, IP.
Sécurité : rôle vérifié côté serveur sur chaque route ; aucune donnée
d'administration renvoyée au candidat.

### 4.7 Contrôles de cohérence (`routes_verif.py`, `app/verif/`)

L'administration **signale, elle ne décide jamais** : aucun contrôle n'écrit
dans `candidatures` (un test le prouve). Les constats vivent dans `controles`,
séparés par construction. Contrôles **déterministes, gratuits** (SHA-256
déjà calculé) :

| Contrôle | Constat | Gravité |
|----------|---------|---------|
| `doublon_piece` | fichier identique au bit près sur un **autre** dossier | majeur |
| `nature_fichier` | contenu ≠ format enregistré (PDF renommé en image) | majeur |
| `origine_fichier` | produit par un logiciel d'images ; image sans trace d'appareil ; fichier modifié >1 jour après dépôt | mineur / info |
| `coherence_notes` | note hors 0–20 ; moyenne hors bande des notes saisies | majeur / mineur |
| `coherence_temps` | année du bac dans le futur ; date de naissance future ; âge au bac anormal | majeur / mineur |

Un contrôle qui ne peut pas conclure produit un constat **indéterminé**, jamais
« conforme ». Un seuil heuristique est annoncé comme tel (la moyenne du bac
porte sur une dizaine de matières, pas sur les quatre notes saisies).

**Lecture des pièces par un modèle** : **non configurée par défaut** (aucun
appel réseau, aucune clé). Interface de l'API OpenAI, ce qui couvre
OpenRouter, NVIDIA NIM, OpenAI, **ou un modèle local** (vLLM, Ollama) — les
pièces de mineurs cessent alors de quitter le serveur. Configuration via
`backend/.env` (jamais versionné).

**Consentement du candidat** : encadré distinct de la certification (étape 7) ;
le refus est explicite et **n'empêche jamais** de déposer un dossier. Le
consentement est **horodaté** (`consentement_le`) : un accord sans date n'est
pas un accord.

## 5. Exigences non fonctionnelles

| Domaine | Exigence |
|---------|----------|
| Sécurité | ownership stricte (anti-IDOR : le dossier est résolu depuis la session, jamais depuis les paramètres) ; rate-limiting (5 connexion/inscription, 20 upload/min) ; en-têtes `nosniff`/`DENY`/`same-origin` ; CORS localhost uniquement ; hash bcrypt ; erreur 500 générique FR sans stacktrace |
| Accessibilité | seuil AA (contraste 4,5:1), cibles tactiles ≥ 24 px (norme) / 36 px (confort), corps ≥ 11 px, ligne ≤ 105 caractères — vérifiés par `tools/verif.py` (36 rendus : 12 pages × 390/900/1440 px) |
| Langue | interface entièrement en français ; accord en nombre et nombres à la française (« 12,75 ») via `js/texte.js` |
| Identité visuelle | palette institutionnelle : vert `#056839` (structure), jaune `#FFDC00` (action), papier chaud `#F6F5F1`, encre `#16191A` ; police Public Sans ; monospace réservé aux numéros de dossier et codes de spécialité ; logo officiel 341×110 |
| Traçabilité | journal des actions d'administration, historique des statuts, horodatage des consentements et soumissions (UTC) |

## 6. Architecture technique

```
backend/                          FastAPI + SQLAlchemy + Pydantic v2
  app/main.py                     montage, CORS, headers, session glissante,
                                  statique en /, /health
  app/routes_auth.py              register / login / logout / logout-all / me
  app/routes_candidature.py       GET/PATCH dossier, /submit, /status
  app/routes_documents.py         upload / liste / téléchargement / suppression
  app/routes_admin.py             espace d'administration (rôle ADMIN)
  app/routes_misc.py              convocation, admission, contact, admis public
  app/routes_verif.py             contrôles de cohérence (rôle ADMIN)
  app/storage_service.py          stockage fichier sécurisé (allowlist, magic
                                  bytes, anti-traversal, écriture atomique)
  app/verif/                      moteur de contrôles déterministes
  app/schemas.py                  source de vérité des référentiels
  app/config.py                   toute la configuration (env / .env)
  storage/candidats/CDT_XXXX/     pièces hors base
backend/tests/                    pytest (53 tests, tous passants)
frontend/                         14 pages servies en / (voir §9)
Photos/                           sources des images (optimisées 1200–1600 px)
tools/                            agent de vérification de rendu (verif.py)
```

**Base de données** : SQLite par défaut (`sqlite:///./emsp.db`), Postgres en
production (`DATABASE_URL`). Tables : `candidatures`, `users`,
`documents_candidature`, `messages_contact`, `actions_admin`,
`historique_statut`, `sessions`, `controles`.

**Pages servies par le backend** (14) : `/` (accueil), `/conditions.html`,
`/candidater`, `/connexion.html`, `/espace-candidat.html` (mon espace),
`/candidature.html` (ma candidature), `/pieces.html` (mes pièces),
`/suivi.html`, `/convocation.html`, `/resultat.html`, `/profil.html`,
`/contact.html`, `/admin.html`. Les pages protégées cachent leur contenu tant
que la session n'est pas validée (`requireAuth` → `/connexion.html?next=…`).

**Styles** : une seule feuille compilée et versionnée —
`frontend/src/app.css` + `frontend/src/legacy.css` + `tailwind.config.js`
→ `npm run build:css` → `frontend/css/app.css`. Plus de compilation dans le
navigateur (Play CDN retiré : il rendait 12 pages sur 14 sans style).

## 7. Statuts d'un dossier

`DRAFT` → `SUBMITTED` → (`UNDER_REVIEW` | `VALIDATED` | `RETAINED` |
`REJECTED`) → `COMPOSITION_SCHEDULED` → `ADMITTED`. Chaque transition est
journalisée dans `historique_statut` par l'administration.

## 8. Outils et opérations

```bash
# Administration
python3 -m app.admin_cli create --email admin@emsp.ci --password '…' --nom "Scolarité"
# (ou ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_NOM — création automatique au démarrage)

# Démonstration : dossiers à tous les stades, avec de vrais PDF
python3 seed_demo.py [--reset]

# Nettoyage des comptes de test (test-* uniquement)
python3 nettoyer_comptes_test.py [--apercu]

# Dossier volontairement suspect pour éprouver le rapport de contrôles
python3 outils_dossier_fictif.py [restaurer]

# Agent de vérification des rendus (mesure 36 rendus, corrige le CSS mesurable)
python3 tools/verif.py [--check]

# Tests
python3 -m pytest tests/ -q
```

Comptes de démonstration (mot de passe `DemoEmsp2026`, adresse `@demo.emsp.ci`) :
`brouillon` (1/7), `presque` (4/7, 0/10 pièces), `soumis` (10/10),
`convoque`, `admis` (LNUM), `refuse` (motif interne invisible).
Admins de démo : `admin@emsp.ci` / `directeur@emsp.ci` (`AdminEmsp2026`).

## 9. Environnement, déploiement

```bash
cd backend && pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000   # puis http://localhost:8000/

# Docker
docker build -f backend/Dockerfile -t emsp-portal .
docker run --rm -p 8000:8000 -v emsp-storage:/app/backend/storage emsp-portal
```

Dépendances Python : fastapi, uvicorn[standard], sqlalchemy, pydantic≥2,
pydantic-settings, passlib[bcrypt], python-multipart, bcrypt<4.1, pytest, httpx.

## 10. État actuel et écarts constatés

1. **Le dossier `frontend/` est absent du workspace.** Le README et le code
   (`main.py:find_frontend_dir`) le référencent (14 pages, `js/parcours.js`,
   `js/session.js`, `js/nav.js`, `js/texte.js`, `js/admin.js`, `css/app.css`),
   mais il n'existe pas dans l'arborescence actuelle : le backend sert ses
   pages par repli (JSON/rendus internes) tant que le dossier est introuvable.
   **C'est le principal livrable à reconstituer** conformément au §4.
2. `DESIGN.md` et `DOSSIER-INTERFACE.md` sont référencés par le README mais
   absents : le contrat d'interface (échelles d'espacement, quatre voix
   typographiques, palette, composants, seuils de lisibilité) est à formaliser
   avant toute campagne de production multi-agents.
3. Le README annonce 16 tests ; la mesure actuelle est **53 tests passants**
   (dont administration et contrôles) — la documentation est à resynchroniser.

## 11. Livrables attendus

- [x] API backend complète (authentification, candidature 7 étapes, documents,
      administration, contrôles, messagerie) — 53 tests passants.
- [x] Stockage documentaire sécurisé (hors base, allowlist, magic bytes).
- [x] Outils d'exploitation (admin_cli, seed, nettoyage, dossier fictif).
- [ ] `frontend/` — les 14 pages, les 7 étapes, les 10 pièces, la session,
      l'administration, la feuille compilée `css/app.css` (voir §10.1).
- [ ] `DESIGN.md` / `DOSSIER-INTERFACE.md` — contrat de design et palette.
- [ ] Activation optionnelle de la lecture par modèle (`.env`, consentement).
