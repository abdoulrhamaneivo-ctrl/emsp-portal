"""Routes documentaires : téléversement / liste / téléchargement / suppression.

Endpoints (préfixe ``/api/candidature/documents``) :
- ``POST /``    : téléverse (ou remplace) une pièce (multipart : ``file`` + ``type_document``).
- ``GET /``     : liste les métadonnées du candidat connecté (jamais de chemin absolu).
- ``GET /{id}/download`` : télécharge une pièce (ownership stricte, ``attachment``).
- ``DELETE /{id}`` : supprime pièce (FS + ligne BDD).

Sécurité :
- auth obligatoire (``get_current_user`` -> 401 sinon),
- ownership ``row.numero_dossier == user.numero_dossier`` sinon 403
  ``"Vous n'êtes pas autorisé à accéder à ce document."``,
- validation via ``DocumentStorageService`` (extension / taille / magic bytes),
- upsert par ``(numero_dossier, type_document)`` avec remplacement atomique,
- rate-limit upload 20/min via ``app.rate_limit.check_rate_limit``
  (appliqué ici ; ``main.py`` n'a qu'à inclure ce router — voir docstring
  de ``get_storage_service``).

Formats : multipart/form-data en entrée, JSON FR en sortie.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import DocumentCandidature
from app.rate_limit import check_rate_limit
from app.storage_service import DocumentStorageService

router = APIRouter(prefix="/api/candidature/documents", tags=["documents"])

UPLOAD_LIMIT_PER_MINUTE = 20
UPLOAD_WINDOW_SEC = 60

MESSAGE_ENVOI_ECHEC = "Le document n'a pas pu être envoyé."
MESSAGE_INTERDIT = "Vous n'êtes pas autorisé à accéder à ce document."


def get_storage_service() -> DocumentStorageService:
    """Fabrique le service de stockage.

    Racine lue depuis ``settings.DOCUMENT_STORAGE_ROOT`` (``./storage`` par
    défaut, soit ``<backend>/storage`` -> ``<root>/candidats/...``).

    Câblage dans ``main.py`` (indicatif) :
        from app.routes_documents import router as documents_router
        app.include_router(documents_router)
    Le rate-limit 20/min est déjà appliqué dans ``POST /`` via
    ``app.rate_limit.check_rate_limit`` ; aucun middleware supplémentaire
    n'est requis dans ``main.py``.
    """
    root = settings.DOCUMENT_STORAGE_ROOT
    if not os.path.isabs(root):
        # Résout par rapport au dossier ``backend/`` (parent de ``app/``),
        # avec repli sur le cwd si la disposition diffère.
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        candidat = os.path.abspath(os.path.join(backend_dir, root))
        # ``./storage`` depuis backend -> ``<backend>/storage`` (existe déjà).
        root = candidat
    return DocumentStorageService(root)


def _metadata_to_dict(doc: DocumentCandidature) -> dict:
    """Sérialise une pièce SANS jamais exposer de chemin absolu."""
    return {
        "id": doc.id,
        "numero_dossier": doc.numero_dossier,
        "type_document": doc.type_document,
        "nom_original": doc.nom_original,
        "mime_type": doc.mime_type,
        "taille": doc.taille,
        "sha256": doc.sha256,
        "statut": doc.statut,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _require_owned(doc: DocumentCandidature | None, numero_dossier: str) -> DocumentCandidature:
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document introuvable.")
    if doc.numero_dossier != numero_dossier:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MESSAGE_INTERDIT)
    return doc


# ---------------------------------------------------------------------------
# POST / — téléversement / remplacement
# ---------------------------------------------------------------------------
@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def upload_document(
    request: Request,
    type_document: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: DocumentStorageService = Depends(get_storage_service),
):
    """Téléverse une pièce justificative (upsert par ``(dossier, type)``)."""
    # --- Rate-limit : 20 uploads / minute / (IP + dossier) ---
    client_ip = request.client.host if request.client else "unknown"
    cle = f"upload:{client_ip}:{getattr(current_user, 'numero_dossier', 'unknown')}"
    if not check_rate_limit(cle, limit=UPLOAD_LIMIT_PER_MINUTE, window_sec=UPLOAD_WINDOW_SEC):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requêtes. Veuillez réessayer dans une minute.",
        )

    # --- Type allowlist (400 si inconnu) ---
    try:
        service._safe_type(type_document)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Le type ``convocation`` est interne : un candidat ne peut pas le déposer.
    if type_document == "convocation":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Type de document invalide."
        )

    numero = getattr(current_user, "numero_dossier", None)
    if not numero:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=MESSAGE_ENVOI_ECHEC
        )
    try:
        service._safe_numero(numero)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=MESSAGE_ENVOI_ECHEC
        )

    raw_name = file.filename or ""
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=MESSAGE_ENVOI_ECHEC
        )
    finally:
        try:
            await file.close()
        except Exception:
            pass

    # --- Validation contenu (extension / taille / magic bytes) ---
    try:
        _ext, mime = service.validate_file(raw_name, bytes(content or b""))
    except ValueError as exc:
        # Préserve le message précis (dont "Type de fichier invalide.").
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Nom original sanitizé pour la BDD (basename, sans traversal).
    nom_original = os.path.basename(raw_name.replace("\\", "/")).strip() or raw_name
    taille = len(content)
    empreinte = hashlib.sha256(bytes(content)).hexdigest()
    # ``mimetypes`` en cohérence (le magic bytes fait foi, déjà validé).
    devine, _ = mimetypes.guess_type(nom_original)
    if devine in ("application/pdf", "image/jpeg", "image/png"):
        mime = mime  # conserve le mime issu des magic bytes

    # --- Upsert par (numero_dossier, type_document) ---
    try:
        existant = (
            db.query(DocumentCandidature)
            .filter(
                DocumentCandidature.numero_dossier == numero,
                DocumentCandidature.type_document == type_document,
            )
            .first()
        )
        if existant is not None:
            ancien_relatif = existant.chemin_relatif
            nom_stockage, chemin_relatif = service.store(
                numero, type_document, raw_name, bytes(content)
            )
            # Supprime l'ancien SEULEMENT après succès du nouveau store.
            try:
                if ancien_relatif and ancien_relatif != chemin_relatif:
                    service.delete_file(ancien_relatif)
            except ValueError:
                pass  # ancien chemin suspect : on conserve le nouveau, pas d'échec
            except FileNotFoundError:
                pass
            existant.nom_original = nom_original
            existant.nom_stockage = nom_stockage
            existant.chemin_relatif = chemin_relatif
            existant.mime_type = mime
            existant.taille = taille
            existant.sha256 = empreinte
            existant.statut = "UPLOADED"
            db.add(existant)
            db.commit()
            db.refresh(existant)
            return _metadata_to_dict(existant)

        nom_stockage, chemin_relatif = service.store(
            numero, type_document, raw_name, bytes(content)
        )
        doc = DocumentCandidature(
            numero_dossier=numero,
            type_document=type_document,
            nom_original=nom_original,
            nom_stockage=nom_stockage,
            chemin_relatif=chemin_relatif,
            mime_type=mime,
            taille=taille,
            sha256=empreinte,
            statut="UPLOADED",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return _metadata_to_dict(doc)
    except HTTPException:
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=MESSAGE_ENVOI_ECHEC
        )


# ---------------------------------------------------------------------------
# GET / — liste du candidat
# ---------------------------------------------------------------------------
@router.get("")
@router.get("/", include_in_schema=False)
def list_documents(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Liste les métadonnées du candidat connecté (jamais de chemin absolu)."""
    rows = (
        db.query(DocumentCandidature)
        .filter(DocumentCandidature.numero_dossier == current_user.numero_dossier)
        .order_by(DocumentCandidature.type_document.asc())
        .all()
    )
    return [_metadata_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /{id}/download — téléchargement
# ---------------------------------------------------------------------------
@router.get("/{doc_id}/download")
def download_document(
    doc_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: DocumentStorageService = Depends(get_storage_service),
):
    """Télécharge une pièce (ownership stricte, ``Content-Disposition: attachment``)."""
    doc = db.get(DocumentCandidature, doc_id)
    _require_owned(doc, current_user.numero_dossier)

    try:
        chemin_abs = service._absolute_path(doc.chemin_relatif)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable sur le serveur."
        )
    if not os.path.isfile(chemin_abs):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable sur le serveur."
        )

    media_type = doc.mime_type or mimetypes.guess_type(doc.nom_original)[0] or "application/octet-stream"
    # ``filename`` fait positionner à Starlette :
    # ``Content-Disposition: attachment; filename="..."``.
    return FileResponse(
        chemin_abs,
        media_type=media_type,
        filename=doc.nom_original,
    )


# ---------------------------------------------------------------------------
# DELETE /{id} — suppression FS + BDD
# ---------------------------------------------------------------------------
@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: DocumentStorageService = Depends(get_storage_service),
):
    """Supprime une pièce (fichier FS + ligne BDD)."""
    doc = db.get(DocumentCandidature, doc_id)
    _require_owned(doc, current_user.numero_dossier)

    try:
        service.delete_file(doc.chemin_relatif)
    except ValueError:
        # Chemin suspect : on supprime quand même la métadonnée pour
        # ne pas laisser de ligne orpheline pointant hors racine.
        pass
    except FileNotFoundError:
        pass
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La suppression du document a échoué.",
        )

    db.delete(doc)
    db.commit()
    return {"message": "Document supprimé avec succès.", "id": doc_id}
