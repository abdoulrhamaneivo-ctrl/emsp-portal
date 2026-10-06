"""Contrôles déterministes sur un dossier et ses pièces.

Aucun réseau, aucun modèle, aucun coût. Ces contrôles comparent ce que
le candidat a déclaré aux traces laissées par les fichiers eux-mêmes.

Trois règles de conception :

1. **Un contrôle ne modifie jamais un dossier.** Il produit un `Constat`.
   Aucune fonction de ce module n'écrit dans `candidatures` ; un test le
   vérifie, parce que la promesse « l'agent signale et ne décide pas »
   ne vaut rien si elle n'est pas testée.

2. **Un contrôle qui ne peut pas conclure ne ment pas.** Si `exiftool` est
   absent ou échoue, le constat dit « non vérifiable », pas « conforme ».

3. **Un seuil heuristique est annoncé comme tel.** La moyenne du
   baccalauréat porte sur une dizaine de matières, pas sur les quatre
   notes que le formulaire en retient : un écart se signale, il ne se
   prouve pas, et le message le dit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# Signatures binaires reconnues sans se fier à l'extension.
SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

# Logiciels d'images : un bulletin ou un relevé qui en sort est un
# document recomposé, pas un export de l'établissement.
EDITEURS_IMAGES = (
    "photoshop", "gimp", "pixelmator", "affinity photo", "canva",
    "paint.net", "krita", "inkscape", "illustrator",
)

# Un relevé de notes n'a aucune raison d'avoir été produit par cela.
PRODUCTEURS_SUSPECTS = ("wps office", "libreoffice", "openoffice")

GRAVITES = ("info", "mineur", "majeur")


def _nombre(valeur: float) -> str:
    """Un nombre à la française : la virgule décimale, sans zéros inutiles."""
    texte = f"{float(valeur):.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return texte or "0"


@dataclass
class Constat:
    """Un écart constaté, avec sa mesure et sa gravité. Jamais une décision."""

    controle: str
    statut: str                 # conforme | signalement | indeterminate
    gravite: str                # info | mineur | majeur
    message: str
    details: dict = field(default_factory=dict)
    document_id: int | None = None
    type_document: str | None = None

    def __post_init__(self) -> None:
        if self.gravite not in GRAVITES:
            raise ValueError(f"gravité inconnue : {self.gravite}")


@dataclass
class Contexte:
    """Tout ce dont un contrôle a besoin, rassemblé et validé une fois."""

    candidature: object                 # Candidature SQLAlchemy
    documents: list                     # DocumentCandidature SQLAlchemy
    doublons: dict[str, list[str]]      # sha256 -> numéros de dossier concernés
    racine: str                         # racine de stockage, chemin absolu
    aujourdhui: date = field(default_factory=date.today)

    def chemin_absolu(self, chemin_relatif: str) -> str | None:
        """Résout un chemin stocké sans jamais sortir de la racine.

        Même garantie que le service de stockage : un dossier de contrôle
        ne doit pas devenir un moyen de lire n'importe quoi sur le disque.
        """
        if not chemin_relatif or os.path.isabs(chemin_relatif):
            return None
        racine_reelle = os.path.realpath(self.racine)
        cible = os.path.realpath(os.path.join(racine_reelle, chemin_relatif))
        if cible != racine_reelle and not cible.startswith(racine_reelle + os.sep):
            return None
        return cible if os.path.isfile(cible) else None


# ── utilitaires ───────────────────────────────────────────────────────────
def _type_reel(chemin: str) -> str | None:
    """Type déduit des premiers octets, pas de l'extension."""
    try:
        with open(chemin, "rb") as f:
            tete = f.read(8)
    except OSError:
        return None
    for signature, mime in SIGNATURES:
        if tete.startswith(signature):
            return mime
    return None


def _metadonnees_exif(chemins: list[str], delai: int = 30) -> dict[str, dict]:
    """Lit les métadonnées de plusieurs fichiers en un seul appel.

    Un appel par dossier : dix ``exiftool`` coûtent plusieurs secondes.
    """
    if not chemins or shutil.which("exiftool") is None:
        return {}
    try:
        res = subprocess.run(
            ["exiftool", "-json", "-G", "-n", *chemins],
            capture_output=True, text=True, timeout=delai,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return {}
        return {entree.get("SourceFile", ""): entree for entree in json.loads(res.stdout)}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def _valeur(meta: dict, *cles: str):
    for cle in cles:
        if cle in meta and meta[cle] not in (None, ""):
            return meta[cle]
    return None


# ── contrôles ─────────────────────────────────────────────────────────────
def controle_doublons(ctx: Contexte) -> list[Constat]:
    """Un fichier identique déposé sur deux dossiers différents.

    Le SHA-256 est calculé à chaque dépôt : ce contrôle ne coûte rien et
    détecte la fraude la plus courante. Un même fichier renvoyé deux fois
    dans le *même* dossier est un remplacement normal, pas un constat.
    """
    constats: list[Constat] = []
    numero = ctx.candidature.numero_dossier
    for doc in ctx.documents:
        autres = [
            n for n in ctx.doublons.get(doc.sha256, [])
            if n and n != numero
        ]
        if not autres:
            continue
        constats.append(Constat(
            controle="doublon_piece",
            statut="signalement",
            gravite="majeur",
            message=(
                f"Cette pièce est identique, au bit près, à une pièce déposée "
                f"sur le dossier {', '.join(autres)}."
            ),
            details={
                "type_document": doc.type_document,
                "sha256": doc.sha256,
                "dossiers_concernes": autres,
            },
            document_id=doc.id,
            type_document=doc.type_document,
        ))
    return constats


def controle_nature(ctx: Contexte) -> list[Constat]:
    """Le fichier est-il bien ce qu'il pretend ? (PDF renommé en JPG…)"""
    constats: list[Constat] = []
    for doc in ctx.documents:
        chemin = ctx.chemin_absolu(doc.chemin_relatif)
        if chemin is None:
            constats.append(Constat(
                controle="nature_fichier", statut="indeterminate", gravite="mineur",
                message="Pièce référencée en base mais introuvable sur le disque.",
                details={"type_document": doc.type_document},
                document_id=doc.id, type_document=doc.type_document,
            ))
            continue
        reel = _type_reel(chemin)
        if reel is None:
            constats.append(Constat(
                controle="nature_fichier", statut="indeterminate", gravite="mineur",
                message="Format de fichier non reconnu ; ni PDF, ni JPEG, ni PNG.",
                details={"mime_declare": doc.mime_type, "taille": doc.taille},
                document_id=doc.id, type_document=doc.type_document,
            ))
            continue
        if reel != doc.mime_type:
            constats.append(Constat(
                controle="nature_fichier", statut="signalement", gravite="majeur",
                message=(
                    f"Le contenu du fichier est un {reel.split('/')[-1].upper()} "
                    f"alors qu'il a été enregistré comme "
                    f"{doc.mime_type.split('/')[-1].upper()}."
                ),
                details={"mime_reel": reel, "mime_declare": doc.mime_type},
                document_id=doc.id, type_document=doc.type_document,
            ))
    return constats


def controle_origine(ctx: Contexte) -> list[Constat]:
    """D'où vient le fichier ? Traces d'appareil, de logiciel, de retouche.

    Aucun de ces indices ne prouve une fraude : un bulletin retranscrit à
    la main au scanner n'a pas de métadonnées, et c'est fréquent. Ils
    informent le jury, qui seul décide.
    """
    chemins: dict[int, str] = {}
    for doc in ctx.documents:
        chemin = ctx.chemin_absolu(doc.chemin_relatif)
        if chemin:
            chemins[doc.id] = chemin
    meta = _metadonnees_exif(list(chemins.values()))

    constats: list[Constat] = []
    for doc in ctx.documents:
        chemin = chemins.get(doc.id)
        if chemin is None:
            continue
        entree = meta.get(chemin) or meta.get(os.path.abspath(chemin)) or {}
        if not entree:
            # exiftool absent ou fichier sans métadonnées : on ne conclut pas.
            constats.append(Constat(
                controle="origine_fichier", statut="indeterminate", gravite="info",
                message="Aucune métadonnée exploitable : origine du fichier inconnue.",
                details={"type_document": doc.type_document},
                document_id=doc.id, type_document=doc.type_document,
            ))
            continue

        producteur = " ".join(str(x) for x in (
            _valeur(entree, "PDF:Producer", "XMP:CreatorTool", "EXIF:Software",
                    "Application", "PNG:Software", "Image:Software"),
        ) if x).strip()
        if producteur:
            minuscule = producteur.lower()
            if any(outil in minuscule for outil in EDITEURS_IMAGES):
                constats.append(Constat(
                    controle="origine_fichier", statut="signalement", gravite="mineur",
                    message=f"Document produit ou retraité par « {producteur} ».",
                    details={"producteur": producteur, "signalement": "editeur_images"},
                    document_id=doc.id, type_document=doc.type_document,
                ))
            elif any(outil in minuscule for outil in PRODUCTEURS_SUSPECTS):
                constats.append(Constat(
                    controle="origine_fichier", statut="signalement", gravite="info",
                    message=(
                        f"Document recomposé avec un traitement de texte "
                        f"(« {producteur} ») plutôt qu'avec le logiciel de "
                        f"l'établissement."
                    ),
                    details={"producteur": producteur, "signalement": "producteur_suspect"},
                    document_id=doc.id, type_document=doc.type_document,
                ))

        if (doc.mime_type or "").startswith("image/"):
            appareil = _valeur(entree, "EXIF:Make", "EXIF:Model", "MakerNotes:Model")
            if not appareil:
                constats.append(Constat(
                    controle="origine_fichier", statut="signalement", gravite="info",
                    message=(
                        "Image sans information d'appareil : ce n'est pas une "
                        "photo prise directement, elle a été scannée ou réexportée."
                    ),
                    details={"signalement": "image_sans_appareil"},
                    document_id=doc.id, type_document=doc.type_document,
                ))

        cree = _valeur(entree, "File:FileModifyDate", "EXIF:DateTimeOriginal",
                       "PDF:CreateDate", "XMP:CreateDate")
        if cree and doc.created_at and _posterieur(cree, doc.created_at):
            constats.append(Constat(
                controle="origine_fichier", statut="signalement", gravite="mineur",
                message=(
                    f"Le fichier a été modifié ({_court(cree)}) après son dépôt "
                    f"({doc.created_at.strftime('%d/%m/%Y %H:%M')})."
                ),
                details={"fichier": _court(cree),
                         "depot": doc.created_at.isoformat(),
                         "signalement": "modifie_apres_depot"},
                document_id=doc.id, type_document=doc.type_document,
            ))
    return constats


def _court(valeur) -> str:
    texte = str(valeur)
    return texte[:19].replace(":", " à ", 1) if ":" in texte else texte[:19]


_GABARITS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%dT%H:%M:%S")


def _instant_utc(valeur) -> datetime | None:
    """Convertit un horodatage exiftool en instant UTC.

    exiftool rend une heure **locale** suivie de son décalage
    (`2026:09:28 17:58:21+02:00`) alors que la base stocke de l'UTC
    naïf. Comparer les deux directement produit un faux positif sur
    presque toutes les pièces : 17h58 locales et 15h58 UTC désignent la
    même seconde. Le décalage fait donc partie de la donnée, pas du
    décor.
    """
    texte = str(valeur).strip()
    decalage = timedelta(0)
    for motif in ("+", "-"):
        # Le fuseau est toujours le dernier « ±HH:MM » de la chaîne.
        if motif not in texte[10:]:
            continue
        index = texte.rfind(motif, 10)
        suffixe = texte[index:]
        if len(suffixe) != 6 or suffixe[3] != ":":
            continue
        try:
            heures, minutes = int(suffixe[1:3]), int(suffixe[4:6])
        except ValueError:
            continue
        total = timedelta(hours=heures, minutes=minutes)
        decalage = total if motif == "+" else -total
        texte = texte[:index].strip()
        break

    for gabarit in _GABARITS:
        try:
            return datetime.strptime(texte, gabarit) - decalage
        except ValueError:
            continue
    return None


def _posterieur(valeur, reference) -> bool:
    """Le fichier a-t-il été modifié *nettement* après son dépôt ?

    L'écart minimal d'une journée est délibéré : une modification dans
    l'heure qui suit le dépôt relève de l'horloge de la machine ou d'une
    recopie, pas d'une substitution de pièce.
    """
    instant = _instant_utc(valeur)
    if instant is None or reference is None:
        return False
    reference = reference.replace(tzinfo=None)
    if instant.tzinfo is not None:
        instant = instant.replace(tzinfo=None)
    return (instant - reference) > timedelta(days=1)


def controle_notes(ctx: Contexte) -> list[Constat]:
    """Les notes déclarées sont-elles possibles, et cohérentes entre elles ?"""
    c = ctx.candidature
    notes = {
        "moyenne du baccalauréat": c.moyenne_bac,
        "note de mathématiques": c.note_math_bac,
        "note de physique-chimie": c.note_physique_bac,
        "note de français": c.note_francais_bac,
        "note d'anglais": c.note_anglais_bac,
    }
    saisies = {k: v for k, v in notes.items() if v is not None}
    if not saisies:
        return []

    constats: list[Constat] = []
    hors_bornes = {k: v for k, v in saisies.items() if not (0 <= float(v) <= 20)}
    if hors_bornes:
        constats.append(Constat(
            controle="coherence_notes", statut="signalement", gravite="majeur",
            message=(
                "Note hors de l'échelle 0-20 : "
                + ", ".join(f"{k} = {_nombre(v)}" for k, v in hors_bornes.items())
            ),
            details={"valeurs": hors_bornes, "signalement": "hors_bornes"},
        ))

    if c.moyenne_bac is not None and len(saisies) > 1:
        autres = [float(v) for k, v in saisies.items() if k != "moyenne du baccalauréat"]
        if autres:
            bas, haut = min(autres), max(autres)
            # Marge de 3 points : la moyenne porte sur une dizaine de
            # matières, pas sur les quatre saisies. Heuristique, pas preuve.
            if not (bas - 3 <= float(c.moyenne_bac) <= haut + 3):
                constats.append(Constat(
                    controle="coherence_notes", statut="signalement", gravite="mineur",
                    message=(
                        f"Moyenne annoncée à {_nombre(c.moyenne_bac)}, alors que les notes "
                        f"saisies vont de {_nombre(bas)} à {_nombre(haut)}. Écart inhabituel, à "
                        f"confirmer sur le relevé — la moyenne du bac porte sur "
                        f"toutes les matières, pas seulement sur ces quatre."
                    ),
                    details={"moyenne": c.moyenne_bac, "notes": autres,
                             "borne_basse": bas - 3, "borne_haute": haut + 3,
                             "signalement": "moyenne_hors_bande"},
                ))
    return constats


def controle_temps(ctx: Contexte) -> list[Constat]:
    """Le calendrier du dossier est-il possible ?"""
    c = ctx.candidature
    constats: list[Constat] = []
    aujourdhui = ctx.aujourdhui

    if c.date_naissance is not None:
        naissance = _date(c.date_naissance)
        if naissance and naissance > aujourdhui:
            constats.append(Constat(
                controle="coherence_temps", statut="signalement", gravite="majeur",
                message="La date de naissance est postérieure à aujourd'hui.",
                details={"date_naissance": str(naissance),
                         "signalement": "naissance_future"},
            ))

    if c.annee_bac is not None:
        annee = int(c.annee_bac)
        if annee > aujourdhui.year:
            constats.append(Constat(
                controle="coherence_temps", statut="signalement", gravite="majeur",
                message=f"Année du baccalauréat annoncée en {annee}, dans le futur.",
                details={"annee_bac": annee, "signalement": "annee_future"},
            ))
        elif c.date_naissance is not None:
            naissance = _date(c.date_naissance)
            if naissance:
                age = annee - naissance.year
                if age < 16 or age > 35:
                    constats.append(Constat(
                        controle="coherence_temps", statut="signalement", gravite="mineur",
                        message=(
                            f"Âge de {age} ans au bac ({annee} - "
                            f"{naissance.year}). Un âge inhabituel mérite d'être "
                            f"vérifié auprès du candidat."
                        ),
                        details={"age_au_bac": age, "annee_bac": annee,
                                 "signalement": "age_inhabituel"},
                    ))
    return constats


def _date(valeur) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        return datetime.fromisoformat(str(valeur)[:10]).date()
    except ValueError:
        return None


TOUS_LES_CONTROLES = (
    controle_doublons,
    controle_nature,
    controle_origine,
    controle_notes,
    controle_temps,
)


def analyser(ctx: Contexte) -> list[Constat]:
    """Lance tous les contrôles. Aucun n'échoue globalement.

    Un contrôle qui lève une exception ne doit pas empêcher les autres de
    rendre leur verdict : un dossier affiché sans contrôles vaut moins que
    mal affiché.
    """
    constats: list[Constat] = []
    for controle in TOUS_LES_CONTROLES:
        try:
            constats.extend(controle(ctx) or [])
        except Exception as exc:  # noqa: BLE001 — un contrôle ne doit rien casser
            constats.append(Constat(
                controle=controle.__name__.replace("controle_", ""),
                statut="indeterminate", gravite="info",
                message=f"Contrôle indisponible : {type(exc).__name__}.",
                details={"erreur": str(exc)[:200]},
            ))
    return constats
