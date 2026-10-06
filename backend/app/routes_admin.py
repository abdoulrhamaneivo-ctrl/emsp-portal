"""Administration : accès à l'ensemble des soumissions.

Sécurité — trois règles non négociables :
1. chaque route exige `require_admin` (rôle ADMIN vérifié côté serveur) ;
2. la lecture d'une pièce belonging à un candidat est journalisée
   (`ActionAdmin`) : l'administration rend des comptes ;
3. un compte candidat ne peut jamais atteindre ce module, quel que soit le
   numéro de dossier transmis.

Le frontend n'a aucun pouvoir : il ne fait que proposer des routes que le
serveur filtre.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password
from app.config import settings
from app.db import get_db
from app.models import (
    ActionAdmin,
    Candidature,
    DocumentCandidature,
    HistoriqueStatut,
    MessageContact,
    User,
)
from app.rate_limit import check_rate_limit
from app.schemas import SPECIALITES
from app.storage_service import DocumentStorageService

router = APIRouter(prefix="/api/admin", tags=["administration"])

# Statuts que l'administration peut poser, et transitions autorisées.
STATUTS_ADMIN = {
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "VALIDATED",
    "RETAINED",
    "REJECTED",
    "COMPOSITION_SCHEDULED",
    "ADMITTED",
}
STATUT_LABELS = {
    "DRAFT": "Brouillon",
    "SUBMITTED": "Dossier soumis",
    "UNDER_REVIEW": "Dossier en cours d'examen",
    "VALIDATED": "Dossier validé",
    "RETAINED": "Dossier retenu",
    "REJECTED": "Dossier non retenu",
    "COMPOSITION_SCHEDULED": "Composition programmée",
    "ADMITTED": "Admis",
}
TYPES_PIECES = [
    "attestation_bac",
    "releve_notes_bac",
    "piece_identite",
    "bulletins_seconde",
    "bulletins_premiere",
    "bulletins_terminale",
    "photo_identite",
    "lettre_motivation",
    "acte_naissance",
    "cv",
]
# Les cinq spécialités du FS MENUM. Cette liste alimente à la fois la
# validation du choix du candidat et l'attribution par le jury : si elle
# reste la liste d'une autre école, les deux sont bloqués.
FILIERES = SPECIALITES

INTERDIT = "Vous n'êtes pas autorisé à accéder à cette ressource."
INTROUVABLE = "Dossier introuvable."


# ───────────────────────────── garde-fous ─────────────────────────────
def _service() -> DocumentStorageService:
    root = settings.DOCUMENT_STORAGE_ROOT
    if not os.path.isabs(root):
        root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, root)
        )
    return DocumentStorageService(root)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Exige le rôle ADMIN. 403 sinon — jamais 404, on assume le refus."""
    role = (getattr(current_user, "role", "CANDIDAT") or "CANDIDAT").upper()
    if role != "ADMIN" or not getattr(current_user, "actif", True):
        raise HTTPException(status_code=403, detail=INTERDIT)
    return current_user


def journaliser(
    db: Session,
    admin: User,
    action: str,
    numero_dossier: str | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    """Écrit une ligne d'audit. Ne doit jamais faire échouer l'action métier."""
    ip = None
    if request is not None and request.client is not None:
        ip = request.client.host
    db.add(
        ActionAdmin(
            admin_id=admin.id,
            admin_email=admin.email,
            action=action,
            numero_dossier=numero_dossier,
            detail=(detail or "")[:500] or None,
            ip=ip,
        )
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dossier(db: Session, numero: str) -> Candidature:
    if not numero or not isinstance(numero, str) or len(numero) > 16:
        raise HTTPException(status_code=404, detail=INTROUVABLE)
    c = (
        db.query(Candidature)
        .filter(Candidature.numero_dossier == numero.strip().upper())
        .first()
    )
    if c is None:
        raise HTTPException(status_code=404, detail=INTROUVABLE)
    return c


# ───────────────────────────── schémas ─────────────────────────────
class StatutChange(BaseModel):
    statut: str = Field(..., description=" nouveau statut du dossier")
    commentaire: Optional[str] = Field(None, max_length=1000)
    motif_refus: Optional[str] = Field(None, max_length=1000)


class DossierPatch(BaseModel):
    filiere_formation: Optional[str] = None
    date_compo: Optional[date] = None
    heure_compo: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    centre_compo: Optional[str] = Field(None, max_length=255)
    note_interne: Optional[str] = Field(None, max_length=4000)
    note_francais_compo: Optional[float] = None
    note_math_compo: Optional[float] = None
    note_anglais_compo: Optional[float] = None
    note_psycho_compo: Optional[float] = None
    # L'admission se décide par la route de statut, jamais par un champ
    # libre : elle est acceptée ici pour rester explicite, mais
    # l'arrière refuse toute valeur et dit où agir.
    admis_concours: Optional[bool] = None


class MessageStatut(BaseModel):
    statut: str = Field(..., pattern="^(NOUVEAU|EN_COURS|TRAITE|ARCHIVE)$")


# ───────────────────────────── tableau de bord ─────────────────────────────
@router.get("/overview")
def overview(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    """Compteurs pour la page d'administration."""
    par_statut: dict[str, int] = {}
    for statut, nb in (
        db.query(Candidature.statut, func.count(Candidature.numero_dossier))
        .group_by(Candidature.statut)
        .all()
    ):
        par_statut[statut] = nb
        par_statut.setdefault(STATUT_LABELS.get(statut, statut), 0)

    total_docs = db.query(func.count(DocumentCandidature.id)).scalar() or 0
    messages_non_lus = (
        db.query(func.count(MessageContact.id))
        .filter(MessageContact.statut == "NOUVEAU")
        .scalar()
        or 0
    )
    dossiers_soumis = (
        db.query(func.count(Candidature.numero_dossier))
        .filter(Candidature.statut != "DRAFT")
        .scalar()
        or 0
    )
    return {
        "dossiers_total": db.query(func.count(Candidature.numero_dossier)).scalar() or 0,
        "dossiers_soumis": dossiers_soumis,
        "par_statut": par_statut,
        "documents": total_docs,
        "messages_non_lus": messages_non_lus,
        "dernieres_actions": [
            {
                "horodatage": a.created_at.isoformat() if a.created_at else None,
                "admin": a.admin_email,
                "action": a.action,
                "numero_dossier": a.numero_dossier,
            }
            for a in db.query(ActionAdmin)
            .order_by(ActionAdmin.created_at.desc())
            .limit(12)
            .all()
        ],
    }


# ───────────────────────────── liste des dossiers ─────────────────────────────
@router.get("/candidatures")
def lister_candidatures(
    statut: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=120),
    limite: int = Query(50, ge=1, le=200),
    decalage: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Liste filtrable de toutes les soumissions."""
    query = db.query(Candidature)
    if statut:
        query = query.filter(Candidature.statut == statut)
    if q:
        motif = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Candidature.numero_dossier.ilike(motif),
                Candidature.nom.ilike(motif),
                Candidature.prenoms.ilike(motif),
                Candidature.email.ilike(motif),
            )
        )
    total = query.count()
    rows = (
        query.order_by(Candidature.updated_at.desc())
        .limit(limite)
        .offset(decalage)
        .all()
    )

    resultats = []
    for c in rows:
        pieces = [
            d.type_document
            for d in db.query(DocumentCandidature)
            .filter(DocumentCandidature.numero_dossier == c.numero_dossier)
            .all()
        ]
        manquantes = [t for t in TYPES_PIECES if t not in pieces]
        resultats.append(
            {
                "numero_dossier": c.numero_dossier,
                "nom": c.nom,
                "prenoms": c.prenoms,
                "email": c.email,
                "telephone": c.telephone,
                "statut": c.statut,
                "statut_label": STATUT_LABELS.get(c.statut, c.statut),
                "choix_1_filiere": c.choix_1_filiere,
                "choix_2_filiere": c.choix_2_filiere,
                "moyenne_bac": c.moyenne_bac,
                "annee_bac": c.annee_bac,
                "pieces_deposees": len(TYPES_PIECES) - len(manquantes),
                "pieces_total": len(TYPES_PIECES),
                "pieces_manquantes": manquantes,
                "soumis_le": c.submitted_at.isoformat() if c.submitted_at else None,
                "mis_a_jour_le": c.updated_at.isoformat() if c.updated_at else None,
            }
        )
    return {
        "total": total,
        "limite": limite,
        "decalage": decalage,
        "resultats": resultats,
        "filieres": FILIERES,
        "statuts": [{"code": k, "label": v} for k, v in STATUT_LABELS.items()],
    }


# ───────────────────────────── détail d'un dossier ─────────────────────────────
@router.get("/candidatures/{numero_dossier}")
def detail_candidature(
    numero_dossier: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    c = _dossier(db, numero_dossier)
    journaliser(db, admin, "CONSULTE_DOSSIER", c.numero_dossier, request=request)
    db.commit()

    documents = [
        {
            "id": d.id,
            "type_document": d.type_document,
            "nom_original": d.nom_original,
            "mime_type": d.mime_type,
            "taille": d.taille,
            "statut": d.statut,
            "depose_le": d.created_at.isoformat() if d.created_at else None,
            "url": f"/api/admin/documents/{d.id}/download",
        }
        for d in db.query(DocumentCandidature)
        .filter(DocumentCandidature.numero_dossier == c.numero_dossier)
        .order_by(DocumentCandidature.type_document)
        .all()
    ]
    types_deposes = {d["type_document"] for d in documents}
    historique = [
        {
            "ancien_statut": h.ancien_statut,
            "nouveau_statut": h.nouveau_statut,
            "libelle": STATUT_LABELS.get(h.nouveau_statut, h.nouveau_statut),
            "commentaire": h.commentaire,
            "par": h.par_admin,
            "le": h.created_at.isoformat() if h.created_at else None,
        }
        for h in db.query(HistoriqueStatut)
        .filter(HistoriqueStatut.numero_dossier == c.numero_dossier)
        .order_by(HistoriqueStatut.created_at.desc())
        .all()
    ]
    from app.verif import rapport as rapport_verif

    return {
        "dossier": {
            "numero_dossier": c.numero_dossier,
            "nom": c.nom,
            "prenoms": c.prenoms,
            "email": c.email,
            "statut": c.statut,
            "statut_label": STATUT_LABELS.get(c.statut, c.statut),
            "note_interne": c.note_interne,
            "motif_refus": c.motif_refus,
            "date_naissance": c.date_naissance.isoformat() if c.date_naissance else None,
            "lieu_naissance": c.lieu_naissance,
            "sexe": c.sexe,
            "nationalite": c.nationalite,
            "nature_piece": c.nature_piece,
            "numero_piece": c.numero_piece,
            "code_tresor_pay": c.code_tresor_pay,
            "telephone": c.telephone,
            "commune": c.commune,
            "ville": c.ville,
            "adresse": c.adresse,
            "annee_bac": c.annee_bac,
            "serie_bac": c.serie_bac,
            "numero_bac": c.numero_bac,
            "numero_table": c.numero_table,
            "mention": c.mention,
            "moyenne_bac": c.moyenne_bac,
            "notes": {
                "math": c.note_math_bac,
                "physique": c.note_physique_bac,
                "francais": c.note_francais_bac,
                "anglais": c.note_anglais_bac,
            },
            "choix_1_filiere": c.choix_1_filiere,
            "choix_2_filiere": c.choix_2_filiere,
            "tuteur1": {
                "nom": c.tuteur1_nom,
                "contact": c.tuteur1_contact,
                "lien": c.tuteur1_lien,
                "residence": c.tuteur1_residence,
            },
            "tuteur2": {
                "nom": c.tuteur2_nom,
                "contact": c.tuteur2_contact,
                "lien": c.tuteur2_lien,
                "residence": c.tuteur2_residence,
            },
            "date_compo": c.date_compo.isoformat() if c.date_compo else None,
            "heure_compo": c.heure_compo,
            "centre_compo": c.centre_compo,
            "notes_compo": {
                "francais": c.note_francais_compo,
                "math": c.note_math_compo,
                "anglais": c.note_anglais_compo,
                "psycho": c.note_psycho_compo,
            },
            "admis_concours": c.admis_concours,
            "filiere_formation": c.filiere_formation,
            "soumis_le": c.submitted_at.isoformat() if c.submitted_at else None,
        },
        "documents": documents,
        "pieces_manquantes": [t for t in TYPES_PIECES if t not in types_deposes],
        "verification": rapport_verif.resume(db, c),
        "historique": historique,
        "filieres": FILIERES,
        "statuts": [{"code": k, "label": v} for k, v in STATUT_LABELS.items()],
    }


@router.patch("/candidatures/{numero_dossier}")
def modifier_candidature(
    numero_dossier: str,
    payload: DossierPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Décision du jury : convocation, filière, notes, note interne."""
    c = _dossier(db, numero_dossier)
    data = payload.model_dump(exclude_unset=True)

    # L'admission passe par la route de statut, qui journalise et verrouille.
    # Le champ est déclaré pour que le client sache qu'il existe, mais on
    # refuse explicitement : sans cela, une valeur envoyée serait ignorée
    # en silence et l'écran afficherait « enregistré » à tort.
    if "admis_concours" in data:
        raise HTTPException(
            status_code=422,
            detail=(
                "L'admission se décide par l'action de statut, qui est "
                "journalisée. Utilisez le bouton « Admis » ou « Non retenu »."
            ),
        )

    if "filiere_formation" in data and data["filiere_formation"] not in (None, *FILIERES):
        raise HTTPException(status_code=422, detail="Filière inconnue.")
    if "date_compo" in data and data["date_compo"] is None:
        c.date_compo = None
    elif data.get("date_compo") is not None:
        c.date_compo = data["date_compo"]

    if "heure_compo" in data:
        c.heure_compo = data["heure_compo"]

    for champ in (
        "filiere_formation",
        "centre_compo",
        "note_interne",
        "note_francais_compo",
        "note_math_compo",
        "note_anglais_compo",
        "note_psycho_compo",
    ):
        if champ in data:
            setattr(c, champ, data[champ])

    # Une convocation porte le dossier en « composition programmée ».
    if c.date_compo and c.centre_compo and c.statut in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "VALIDATED",
        "RETAINED",
    ):
        ancien = c.statut
        c.statut = "COMPOSITION_SCHEDULED"
        c.reviewed_at = _utcnow()
        db.add(
            HistoriqueStatut(
                numero_dossier=c.numero_dossier,
                ancien_statut=ancien,
                nouveau_statut=c.statut,
                commentaire="Convocation programmée",
                par_admin=admin.email,
            )
        )

    journaliser(
        db,
        admin,
        "MODIFIE_DOSSIER",
        c.numero_dossier,
        ",".join(sorted(data.keys())) or "—",
        request,
    )
    db.commit()
    return {"message": "Dossier mis à jour.", "numero_dossier": c.numero_dossier,
            "statut": c.statut, "statut_label": STATUT_LABELS.get(c.statut, c.statut)}


@router.post("/candidatures/{numero_dossier}/statut")
def changer_statut(
    numero_dossier: str,
    payload: StatutChange,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Change le statut du dossier (décision du jury) et journalise."""
    c = _dossier(db, numero_dossier)
    nouveau = payload.statut.strip().upper()
    if nouveau not in STATUTS_ADMIN:
        raise HTTPException(status_code=422, detail="Statut inconnu.")
    if c.statut == nouveau:
        return {"message": "Statut inchangé.", "statut": c.statut,
                "statut_label": STATUT_LABELS[nouveau]}

    ancien = c.statut
    c.statut = nouveau
    c.reviewed_at = _utcnow()
    if nouveau == "REJECTED":
        c.motif_refus = payload.motif_refus or payload.commentaire
    if nouveau == "ADMITTED":
        c.admis_concours = True
    elif nouveau in ("REJECTED",):
        c.admis_concours = False

    db.add(
        HistoriqueStatut(
            numero_dossier=c.numero_dossier,
            ancien_statut=ancien,
            nouveau_statut=nouveau,
            commentaire=payload.commentaire,
            par_admin=admin.email,
        )
    )
    journaliser(
        db, admin, "CHANGE_STATUT", c.numero_dossier, f"{ancien} -> {nouveau}", request
    )
    db.commit()
    return {
        "message": "Statut mis à jour.",
        "numero_dossier": c.numero_dossier,
        "statut": nouveau,
        "statut_label": STATUT_LABELS[nouveau],
    }


# ───────────────────────────── pièces justificatives ─────────────────────────────
@router.get("/documents/{document_id}/download")
def telecharger_document_admin(
    document_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> FileResponse:
    """Téléchargement d'une pièce par l'administration — toujours journalisé."""
    doc = db.get(DocumentCandidature, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    service = _service()
    try:
        chemin = service._absolute_path(doc.chemin_relatif)
    except ValueError:
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur.")
    if not os.path.isfile(chemin):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le serveur.")

    journaliser(
        db,
        admin,
        "TELECHARGE_PIECE",
        doc.numero_dossier,
        f"{doc.type_document} / {doc.nom_original}",
        request,
    )
    db.commit()
    return FileResponse(
        chemin,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.nom_original,
    )


@router.get("/candidatures/{numero_dossier}/document/{type_document}")
def piece_par_type(
    numero_dossier: str,
    type_document: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
):
    """Téléchargement direct par type (pratique pour l'affichage en liste)."""
    if not check_rate_limit(f"admin-doc:{admin.id}", limit=120, window_sec=60):
        raise HTTPException(status_code=429, detail="Trop de téléchargements. Patientez une minute.")
    doc = (
        db.query(DocumentCandidature)
        .filter(
            DocumentCandidature.numero_dossier == _dossier(db, numero_dossier).numero_dossier,
            DocumentCandidature.type_document == type_document,
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Pièce non déposée.")
    return telecharger_document_admin(doc.id, db=db, admin=admin, request=request)


# ───────────────────────────── convocation ─────────────────────────────
@router.post("/candidatures/{numero_dossier}/convocation")
async def deposer_convocation(
    numero_dossier: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    """Dépose le PDF officiel de convocation dans le dossier du candidat."""
    c = _dossier(db, numero_dossier)
    service = _service()
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Le fichier n'a pas pu être lu.")

    nom_original = os.path.basename((file.filename or "convocation.pdf").replace("\\", "/"))
    try:
        # store() valide (PDF uniquement) et renvoie (nom_stockage, chemin_relatif)
        nom_stockage, chemin_relatif = service.store(
            c.numero_dossier, "convocation", nom_original, bytes(content)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ancien = db.query(DocumentCandidature).filter(
        DocumentCandidature.numero_dossier == c.numero_dossier,
        DocumentCandidature.type_document == "convocation",
    ).first()
    if ancien is not None and ancien.chemin_relatif != chemin_relatif:
        # On ne supprime l'ancien fichier qu'APRÈS le dépôt du nouveau.
        try:
            service.delete_file(ancien.chemin_relatif)
        except ValueError:
            pass
    if ancien is not None:
        ancien.nom_original = nom_original
        ancien.nom_stockage = nom_stockage
        ancien.chemin_relatif = chemin_relatif
        ancien.mime_type = "application/pdf"
        ancien.taille = len(content)
        ancien.sha256 = hashlib.sha256(bytes(content)).hexdigest()
        ancien.statut = "UPLOADED"
        ancien.updated_at = _utcnow()
        db.add(ancien)
    else:
        db.add(
            DocumentCandidature(
                numero_dossier=c.numero_dossier,
                type_document="convocation",
                nom_original=nom_original,
                nom_stockage=nom_stockage,
                chemin_relatif=chemin_relatif,
                mime_type="application/pdf",
                taille=len(content),
                sha256=hashlib.sha256(bytes(content)).hexdigest(),
                statut="UPLOADED",
            )
        )
    journaliser(db, admin, "DEPOSE_CONVOCATION", c.numero_dossier, nom_original, request)
    db.commit()
    return {"message": "Convocation déposée.", "numero_dossier": c.numero_dossier}


# ───────────────────────────── messages de contact ─────────────────────────────
@router.get("/messages")
def lister_messages(
    statut: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    query = db.query(MessageContact)
    if statut:
        query = query.filter(MessageContact.statut == statut)
    rows = query.order_by(MessageContact.created_at.desc()).limit(200).all()
    return {
        "messages": [
            {
                "id": m.id,
                "nom": m.nom,
                "email": m.email,
                "telephone": m.telephone,
                "objet": m.objet,
                "message": m.message,
                "statut": m.statut,
                "cree_le": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    }


@router.patch("/messages/{message_id}")
def maj_message(
    message_id: int,
    payload: MessageStatut,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    request: Request = None,
) -> dict:
    m = db.get(MessageContact, message_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Message introuvable.")
    m.statut = payload.statut
    journaliser(db, admin, "MESSAGE", None, f"#{m.id} -> {payload.statut}", request)
    db.commit()
    return {"message": "Message mis à jour."}


# ───────────────────────────── gestion des comptes ─────────────────────────────
@router.get("/comptes")
def lister_comptes(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> dict:
    rows = db.query(User).order_by(User.created_at.desc()).limit(500).all()
    return {
        "comptes": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "actif": u.actif,
                "numero_dossier": u.numero_dossier,
                "nom_affiche": u.nom_affiche,
                "cree_le": u.created_at.isoformat() if u.created_at else None,
            }
            for u in rows
        ]
    }


@router.post("/comptes/admin")
def creer_admin(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Crée un compte administrateur (usage interne, protégé par le rôle)."""
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    nom = str(payload.get("nom_affiche") or "Administration").strip()[:255]
    if "@" not in email or len(password) < 8:
        raise HTTPException(status_code=422, detail="E-mail valide et mot de passe de 8 caractères minimum.")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet e-mail.")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role="ADMIN",
        nom_affiche=nom,
        numero_dossier=None,
    )
    db.add(user)
    db.commit()
    return {"message": "Compte administrateur créé.", "email": email}
