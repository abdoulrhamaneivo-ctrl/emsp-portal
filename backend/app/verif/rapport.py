"""Assemblage, persistance et lecture des constats de vérification.

Le point important de ce module est son import : il ne contient aucun
`db.commit()` sur `candidatures` et n'importe aucune fonction capable de
changer un statut. Un contrôle **signale** ; le jury **décide**.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ActionAdmin, Candidature, Controle, DocumentCandidature
from app.verif.forensics import Contexte, Constat, analyser

# Gravité retenue pour l'affichage en tête de rapport.
_ORDRE = {"majeur": 0, "mineur": 1, "info": 2}

LIBELLES_CONTROLE = {
    "doublon_piece": "Pièce en double",
    "nature_fichier": "Nature du fichier",
    "origine_fichier": "Origine du fichier",
    "coherence_notes": "Cohérence des notes",
    "coherence_temps": "Cohérence des dates",
}


def racine_stockage() -> str:
    """Racine de stockage absolue, résolue comme dans les routes admin.

    Dupliquer cette résolution serait reproduire le bug qui a déjà fait
    écrire des pièces dans deux répertoires différents.
    """
    racine = settings.DOCUMENT_STORAGE_ROOT
    if not os.path.isabs(racine):
        racine = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, racine))
    return racine


def _doublons(db: Session, sha256s: list[str]) -> dict[str, list[str]]:
    """Dossiers, tous confondus, portant un fichier identique.

    Une seule requête pour l'ensemble des pièces du dossier : c'est le
    contrôle le moins cher du dispositif.
    """
    if not sha256s:
        return {}
    lignes = db.execute(
        select(DocumentCandidature.sha256, DocumentCandidature.numero_dossier)
        .where(DocumentCandidature.sha256.in_(sha256s))
        .distinct()
    ).all()
    regroupes: dict[str, set[str]] = {}
    for sha, numero in lignes:
        regroupes.setdefault(sha, set()).add(numero)
    return {sha: sorted(numeros) for sha, numeros in regroupes.items()}


def constats_de(db: Session, candidature: Candidature) -> list[Controle]:
    """Constats du dossier, les plus graves d'abord."""
    return list(
        db.query(Controle)
        .filter(Controle.numero_dossier == candidature.numero_dossier)
        .order_by(Controle.id.desc())
        .all()
    )


def purger(db: Session, candidature: Candidature) -> int:
    """Supprime les constats d'un dossier avant une nouvelle analyse.

    Un dossier n'a jamais deux analyses : la seconde remplace la première,
    faute de quoi le rapport afficherait des constats périmés.
    """
    supprimes = (
        db.query(Controle)
        .filter(Controle.numero_dossier == candidature.numero_dossier)
        .delete(synchronize_session=False)
    )
    return supprimes


def lancer_controles(db: Session, candidature: Candidature) -> list[Controle]:
    """Analyse le dossier et enregistre les constats. Ne modifie pas le dossier."""
    documents = list(
        db.query(DocumentCandidature)
        .filter(DocumentCandidature.numero_dossier == candidature.numero_dossier)
        .order_by(DocumentCandidature.type_document)
        .all()
    )
    purger(db, candidature)

    contexte = Contexte(
        candidature=candidature,
        documents=documents,
        doublons=_doublons(db, [d.sha256 for d in documents if d.sha256]),
        racine=racine_stockage(),
        aujourdhui=date.today(),
    )
    constats = analyser(contexte)
    enregistres: list[Controle] = []
    for constat in constats:
        ligne = Controle(
            numero_dossier=candidature.numero_dossier,
            document_id=constat.document_id,
            type_document=constat.type_document,
            controle=constat.controle,
            statut=constat.statut,
            gravite=constat.gravite,
            message=constat.message,
            details=json.dumps(constat.details, ensure_ascii=False)[:4000] or None,
            source="deterministe",
        )
        db.add(ligne)
        enregistres.append(ligne)
    db.flush()
    return enregistres


def resume(db: Session, candidature: Candidature) -> dict:
    """Rapport de vérification, prêt pour l'affichage dans la fiche dossier."""
    constats = constats_de(db, candidature)
    signalements = [c for c in constats if c.statut == "signalement"]
    par_gravite: dict[str, int] = {}
    for c in signalements:
        par_gravite[c.gravite] = par_gravite.get(c.gravite, 0) + 1

    return {
        "analyse": bool(constats),
        "source": "deterministe",
        # La lecture par modèle n'existe pas encore : le rapport doit le
        # dire plutôt que laisser croire que le dossier a été analysé.
        "lecture_modele": "non_configuree" if not settings.VERIF_ACTIF else "non_lancee",
        "consentement": {
            "accorde": bool(candidature.consentement_tiers),
            "le": candidature.consentement_le.isoformat() if candidature.consentement_le else None,
            "exige": settings.CONSENTEMENT_TIERS_REQUIS,
        },
        "resume": {
            "signalements": len(signalements),
            "majeur": par_gravite.get("majeur", 0),
            "mineur": par_gravite.get("mineur", 0),
            "info": par_gravite.get("info", 0),
            "indetermines": sum(1 for c in constats if c.statut == "indeterminate"),
        },
        "constats": [
            {
                "id": c.id,
                "controle": c.controle,
                "libelle": LIBELLES_CONTROLE.get(c.controle, c.controle),
                "type_document": c.type_document,
                "statut": c.statut,
                "gravite": c.gravite,
                "message": c.message,
                "details": _details(c.details),
                "source": c.source,
                "le": c.created_at.isoformat() if c.created_at else None,
            }
            for c in sorted(
                constats,
                key=lambda x: (_ORDRE.get(x.gravite, 3), -(x.id or 0)),
            )
        ],
        # Champ laissé au jury : une machine ne peut pas établir qu'un
        # document a été réellement délivré par un établissement. Seule
        # l'administration peut l'affirmer, en le consignant ici.
        "verification_externe": {
            "realisee": bool(candidature.reviewed_at),
            "par": None,
            "reference": None,
        },
    }


def _details(brut: str | None) -> dict:
    if not brut:
        return {}
    try:
        valeur = json.loads(brut)
        return valeur if isinstance(valeur, dict) else {"valeur": valeur}
    except ValueError:
        return {}
