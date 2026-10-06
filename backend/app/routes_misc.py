"""Routes convocation / admission / contact / admis public.

Monte avec : app.include_router(router) (chemins complets /api/... inclus ici).
Ne jamais inventer de resultat : tout vient de la DB.
Ownership strict via current_user (User.numero_dossier -> Candidature).
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Candidature, DocumentCandidature, MessageContact, User
from app.pdf_documents import build_convocation_pdf, build_result_certificate_pdf
from app.rate_limit import check_rate_limit

router = APIRouter(tags=["convocation-admission-contact"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TELEPHONE_RE = re.compile(r"^\+?[0-9\s\-]{8,15}$")
OBJETS_AUTORISES = ("Candidature", "Inscription", "Documents", "Admission")

CONVOCATION_INDISPONIBLE = "Votre convocation n'est pas encore disponible."
ADMISSION_INDISPONIBLE = "Résultat non disponible pour le moment."
TROP_DE_TENTATIVES = "Trop de requêtes. Réessayez dans une minute."


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "inconnu"


def _get_candidature(db: Session, user: User) -> Candidature | None:
    """Charge la candidature du user via son numero_dossier (ownership strict)."""
    if not getattr(user, "numero_dossier", None):
        return None
    return (
        db.query(Candidature)
        .filter(Candidature.numero_dossier == user.numero_dossier)
        .first()
    )


def _get_convocation_doc(db: Session, numero_dossier: str) -> DocumentCandidature | None:
    """Document convocation du dossier, ou None (metadata type == convocation)."""
    return (
        db.query(DocumentCandidature)
        .filter(
            DocumentCandidature.numero_dossier == numero_dossier,
            DocumentCandidature.type_document == "convocation",
        )
        .first()
    )


def _resolve_storage_path(chemin_relatif: str) -> str:
    """Resout chemin_relatif contre DOCUMENT_STORAGE_ROOT, anti path-traversal."""
    root = os.path.abspath(settings.DOCUMENT_STORAGE_ROOT)
    # chemin_relatif reste relatif en BDD ; abspath(join) + garde-fou.
    candidat = os.path.abspath(os.path.join(root, chemin_relatif))
    if candidat != root and not candidat.startswith(root + os.sep):
        raise HTTPException(status_code=404, detail=CONVOCATION_INDISPONIBLE)
    return candidat


def _masquer_numero_dossier(numero: str | None) -> str:
    s = str(numero or "")
    if len(s) <= 4:
        return "***"
    return f"{s[:2]}***{s[-2:]}"


# ---------------------------------------------------------------------------
# GET /api/candidature/convocation
# ---------------------------------------------------------------------------
@router.get("/api/candidature/convocation")
def get_convocation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    candidature = _get_candidature(db, current_user)
    if (
        candidature is None
        or not candidature.date_compo
        or not candidature.centre_compo
    ):
        return {"disponible": False, "message": CONVOCATION_INDISPONIBLE}

    payload: dict = {
        "disponible": True,
        "numero_dossier": candidature.numero_dossier,
        "date_compo": candidature.date_compo.isoformat(),
        "heure_compo": candidature.heure_compo,
        "centre_compo": candidature.centre_compo,
        "convocation_url": "/api/candidature/convocation/download",
    }
    return payload


# ---------------------------------------------------------------------------
# GET /api/candidature/convocation/download
# ---------------------------------------------------------------------------
@router.get("/api/candidature/convocation/download")
def download_convocation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    candidature = _get_candidature(db, current_user)
    if (
        candidature is None
        or not candidature.date_compo
        or not candidature.centre_compo
    ):
        raise HTTPException(status_code=404, detail=CONVOCATION_INDISPONIBLE)

    # Ownership strict : on ne cherche que parmi les documents du dossier du user.
    doc = _get_convocation_doc(db, candidature.numero_dossier)
    if doc is not None:
        path = _resolve_storage_path(doc.chemin_relatif)
        if os.path.isfile(path):
            return FileResponse(
                path=path,
                media_type=doc.mime_type or "application/octet-stream",
                filename=doc.nom_original or "convocation.pdf",
            )

    pdf = build_convocation_pdf(candidature)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="convocation-{candidature.numero_dossier}.pdf"'
        },
    )


# ---------------------------------------------------------------------------
# GET /api/candidature/admission
# ---------------------------------------------------------------------------
@router.get("/api/candidature/admission")
def get_admission(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    candidature = _get_candidature(db, current_user)
    if candidature is None or candidature.admis_concours is None:
        return {"disponible": False, "message": ADMISSION_INDISPONIBLE}
    if candidature.admis_concours is True:
        return {
            "disponible": True,
            "admis": True,
            "message": "Félicitations, vous êtes admis.",
            "numero_dossier": candidature.numero_dossier,
            "filiere_formation": candidature.filiere_formation,
            "date_decision": candidature.reviewed_at.isoformat() if candidature.reviewed_at else None,
            "notes": _notes_resultat(candidature),
            "certificat_url": "/api/candidature/admission/certificat.pdf",
        }
    return {
        "disponible": True,
        "admis": False,
        "message": "Dossier non retenu.",
        "numero_dossier": candidature.numero_dossier,
        "date_decision": candidature.reviewed_at.isoformat() if candidature.reviewed_at else None,
        "notes": _notes_resultat(candidature),
        "certificat_url": "/api/candidature/admission/certificat.pdf",
    }


def _notes_resultat(candidature: Candidature) -> dict[str, float]:
    valeurs = {
        "Français": candidature.note_francais_compo,
        "Mathématiques": candidature.note_math_compo,
        "Anglais": candidature.note_anglais_compo,
        "Psychotechnique": candidature.note_psycho_compo,
    }
    return {label: valeur for label, valeur in valeurs.items() if valeur is not None}


@router.get("/api/candidature/admission/certificat.pdf")
def download_result_certificate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    candidature = _get_candidature(db, current_user)
    if candidature is None or candidature.admis_concours is None:
        raise HTTPException(status_code=404, detail=ADMISSION_INDISPONIBLE)

    pdf = build_result_certificate_pdf(candidature)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="attestation-resultat-{candidature.numero_dossier}.pdf"'
        },
    )


# ---------------------------------------------------------------------------
# POST /api/contact (public, rate-limit 5/min)
# ---------------------------------------------------------------------------
@router.post("/api/contact", status_code=status.HTTP_201_CREATED)
def post_contact(payload: dict, request: Request, db: Session = Depends(get_db)):
    if not check_rate_limit(f"contact:{_client_ip(request)}", limit=5, window_sec=60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TROP_DE_TENTATIVES
        )

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Corps de requête invalide.")

    nom = payload.get("nom")
    email = payload.get("email")
    telephone = payload.get("telephone")
    objet = payload.get("objet")
    message = payload.get("message")

    errors: dict[str, str] = {}
    if not isinstance(nom, str) or not nom.strip():
        errors["nom"] = "Le nom est requis."
    if not isinstance(email, str) or not email.strip():
        errors["email"] = "L'email est requis."
    elif not _EMAIL_RE.match(email.strip()):
        errors["email"] = "L'email est invalide."
    if not isinstance(objet, str) or objet not in OBJETS_AUTORISES:
        errors["objet"] = (
            "L'objet doit être l'un des suivants : "
            "Candidature, Inscription, Documents, Admission."
        )
    if not isinstance(message, str) or len(message.strip()) < 10:
        errors["message"] = "Le message doit contenir au moins 10 caractères."
    if telephone is not None and telephone != "":
        if not isinstance(telephone, str) or not _TELEPHONE_RE.match(telephone.strip()):
            errors["telephone"] = "Le numéro de téléphone est invalide."
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    contact = MessageContact(
        nom=nom.strip(),
        email=email.strip(),
        telephone=telephone.strip()
        if isinstance(telephone, str) and telephone.strip()
        else None,
        objet=objet,
        message=message.strip(),
        statut="NOUVEAU",
    )
    db.add(contact)
    db.commit()

    return {"message": "Votre message a été envoyé. Nous vous répondrons rapidement."}


# ---------------------------------------------------------------------------
# GET /api/admis/public — liste anonymisee des seuls ADMIS
# ---------------------------------------------------------------------------
@router.get("/api/admis/public")
def get_admis_public(
    db: Session = Depends(get_db),
    filiere: str | None = Query(
        default=None, description="Filtre optionnel par filière"
    ),
    limit: int = Query(default=100, ge=1, le=500),
):
    q = db.query(Candidature).filter(Candidature.admis_concours.is_(True))
    if filiere:
        q = q.filter(Candidature.filiere_formation == filiere)
    rows = q.limit(limit).all()

    # Anonymise : uniquement numero masque + filiere. Jamais email / nom.
    admis = [
        {
            "numero_dossier_masque": _masquer_numero_dossier(r.numero_dossier),
            "filiere_formation": r.filiere_formation,
        }
        for r in rows
    ]
    return {"admis": admis, "total": len(admis)}
