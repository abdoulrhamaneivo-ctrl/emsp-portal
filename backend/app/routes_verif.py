"""Routes de vérification des dossiers — accès administrateur uniquement.

Ces routes **lisent et signalent**. Elles ne montrent aucun chemin vers une
modification de statut : le rapport alimente le jugement du jury, il ne le
remplace pas. C'est la raison pour laquelle ce routeur n'expose ni
`PATCH` ni `DELETE` sur un dossier.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Candidature, Controle, DocumentCandidature
from app.rate_limit import check_rate_limit
from app.routes_admin import journaliser, require_admin
from app.routes_documents import get_storage_service
from app.models import User
from app.verif import rapport
from app.verif.modele import analyser_documents, configuration_modele

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
    """Lance les contrôles locaux puis, si autorisé, la lecture IA des pièces."""
    if not check_rate_limit(f"admin-verif:{admin.id}:{numero_dossier}", limit=5, window_sec=60):
        raise HTTPException(status_code=429, detail="Trop d’analyses lancées. Réessayez dans une minute.")
    dossier = _dossier(db, numero_dossier)
    rapport.lancer_controles(db, dossier)

    # La vérification déterministe reste disponible sans partage externe.
    # Aucune pièce ne quitte le serveur sans accord explicite et horodaté.
    etat_configuration, message = configuration_modele()
    controles_ia = []
    if etat_configuration == "prete":
        if dossier.consentement_tiers and dossier.consentement_le:
            documents = (
                db.query(DocumentCandidature)
                .filter(DocumentCandidature.numero_dossier == dossier.numero_dossier)
                .order_by(DocumentCandidature.type_document)
                .all()
            )
            controles_ia, etat_configuration, message = analyser_documents(
                dossier, documents, get_storage_service()
            )
        else:
            etat_configuration = "consentement_requis"
            message = "Le candidat n’a pas donné son accord. Aucune pièce n’a été transmise au fournisseur IA."
    db.add_all(controles_ia)
    # Persiste aussi l’état quand aucun écart n’a été trouvé : « analyse:false »
    # ne doit plus laisser croire qu’un contrôle sans alerte n’a pas eu lieu.
    db.add(Controle(
        numero_dossier=dossier.numero_dossier,
        document_id=None,
        type_document=None,
        controle="etat_lecture_modele",
        statut="indeterminate",
        gravite="info",
        message=message[:500],
        details=json.dumps({"etat": etat_configuration, "message": message[:500]}, ensure_ascii=False),
        source="systeme",
    ))
    journaliser(
        db, admin, "VERIFICATION_LANCEE", dossier.numero_dossier,
        detail=f"contrôles déterministes · IA {etat_configuration}", request=request,
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
