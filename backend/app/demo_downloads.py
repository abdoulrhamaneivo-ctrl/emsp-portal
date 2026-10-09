"""Réparation à la demande des fichiers manquants des comptes de démonstration."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy.orm import Session

from app.models import Candidature, DocumentCandidature
from app.pdf_documents import build_convocation_pdf, build_demo_document_pdf
from app.storage_service import TYPES_AUTORISES

logger = logging.getLogger(__name__)


def read_or_rebuild_demo_document(db: Session, doc: DocumentCandidature, service) -> bytes:
    """Lit un objet puis répare une pièce absente si elle appartient à une démo.

    Les fichiers remis au candidat restent fictifs et portent un marquage
    visible. Les pièces des vrais dossiers ne sont jamais reconstruites.
    """
    try:
        return service.read_file(doc.chemin_relatif)
    except FileNotFoundError:
        candidature = (
            db.query(Candidature)
            .filter(Candidature.numero_dossier == doc.numero_dossier)
            .first()
        )
        if not candidature or not str(candidature.email or "").lower().endswith("@demo.emsp.ci"):
            raise

        if doc.type_document == "convocation":
            content = build_convocation_pdf(candidature)
        elif doc.type_document in TYPES_AUTORISES:
            content = build_demo_document_pdf(candidature, doc.type_document)
        else:
            raise

        # Restaure le fichier manquant de façon opportuniste. Le PDF est
        # renvoyé même si le stockage distant est temporairement indisponible.
        try:
            filename = doc.nom_original or f"{doc.type_document}.pdf"
            stored_name, relative_path = service.store(
                candidature.numero_dossier, doc.type_document, filename, content
            )
            doc.nom_stockage = stored_name
            doc.chemin_relatif = relative_path
            doc.mime_type = "application/pdf"
            doc.taille = len(content)
            doc.sha256 = hashlib.sha256(content).hexdigest()
            doc.statut = "UPLOADED"
            db.add(doc)
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("La réparation d'une pièce de démonstration a échoué.")
        return content
