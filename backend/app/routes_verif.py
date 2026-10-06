"""Routes de vérification des dossiers — accès administrateur uniquement.

Ces routes **lisent et signalent**. Elles ne montrent aucun chemin vers une
modification de statut : le rapport alimente le jugement du jury, il ne le
remplace pas. C'est la raison pour laquelle ce routeur n'expose ni
`PATCH` ni `DELETE` sur un dossier.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Candidature
from app.routes_admin import journaliser, require_admin
from app.models import User
from app.verif import rapport

router = APIRouter(prefix="/api/admin", tags=["verification"])


def _dossier(db: Session, numero: str) -> Candidature:
    dossier = (
        db.query(Candidature)
        .filter(Candidature.numero_dossier == numero)
        .one_or_none()
    )
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    return dossier


@router.post("/candidatures/{numero_dossier}/controles")
def lancer_verification(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Lance les contrôles déterministes sur un dossier et rend le rapport."""
    dossier = _dossier(db, numero_dossier)
    rapport.lancer_controles(db, dossier)
    journaliser(
        db, admin, "VERIFICATION_LANCEE", dossier.numero_dossier,
        detail="contrôles déterministes", request=request,
    )
    db.commit()
    return rapport.resume(db, dossier)


@router.get("/candidatures/{numero_dossier}/controles")
def lire_verification(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Rapport de vérification déjà calculé, sans relancer l'analyse.

    Consulter un dossier n'écrit rien : ouvrir la fiche ne doit pas être
    un acte d'administration.
    """
    dossier = _dossier(db, numero_dossier)
    return rapport.resume(db, dossier)
