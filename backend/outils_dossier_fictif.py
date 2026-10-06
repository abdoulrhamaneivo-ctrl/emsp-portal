"""Fabrique un dossier volontairement douteux, pour éprouver le rapport.

Usage : python3 outils_dossier_fictif.py
Sans argument, restaure les valeurs d'origine (consignées en bas).
"""
import hashlib
import os

from app.config import settings
from app.db import SessionLocal
from app.models import Candidature, DocumentCandidature

# Valeurs d'origine du dossier de démonstration, pour pouvoir revenir en arrière.
ORIGINAL = {
    "CDT_0004": dict(
        moyenne_bac=12.75, note_math_bac=12.0, note_physique_bac=12.0,
        note_francais_bac=13.0, note_anglais_bac=14.0, annee_bac=2025,
    ),
}

def sha256_reel(chemin_relatif: str) -> str | None:
    """Empreinte du fichier tel qu'il est sur le disque.

    Restaurer l'empreinte en la recalculant est plus sûr que de la
    mémoriser dans le script : le fichier est la source de vérité, et
    l'outil fonctionne même après un redémarrage.
    """
    racine = settings.DOCUMENT_STORAGE_ROOT
    if not os.path.isabs(racine):
        racine = os.path.abspath(os.path.join(os.path.dirname(__file__), racine))
    chemin = os.path.join(racine, chemin_relatif)
    if not os.path.isfile(chemin):
        return None
    with open(chemin, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

SUSPECT = dict(
    moyenne_bac=18.9, note_math_bac=9.0, note_physique_bac=8.5,
    note_francais_bac=10.0, note_anglais_bac=9.5, annee_bac=2031,
)


def basculer(vers_suspect: bool) -> None:
    db = SessionLocal()
    try:
        for numero, valeurs in ORIGINAL.items():
            dossier = db.query(Candidature).filter(
                Candidature.numero_dossier == numero).one()
            for champ, valeur in valeurs.items():
                setattr(dossier, champ, SUSPECT[champ] if vers_suspect else valeur)

            autre = db.query(DocumentCandidature).filter(
                DocumentCandidature.numero_dossier == "CDT_0005",
                DocumentCandidature.type_document == "acte_naissance",
            ).one_or_none()
            mien = db.query(DocumentCandidature).filter(
                DocumentCandidature.numero_dossier == numero,
                DocumentCandidature.type_document == "acte_naissance",
            ).one_or_none()
            if mien is not None:
                if vers_suspect and autre is not None:
                    # Un acte de naissance identique au bit près à celui
                    # d'un autre dossier : le contrôle de doublon doit
                    # le voir.
                    mien.sha256 = autre.sha256
                else:
                    # On rend l'empreinte d'origine en relisant le fichier.
                    reverable = sha256_reel(mien.chemin_relatif)
                    if reverable:
                        mien.sha256 = reverable
        db.commit()
        etat = "SUSPECT" if vers_suspect else "restauré"
        print(f"dossier de démonstration : {etat}")
        for numero, valeurs in ORIGINAL.items():
            d = db.query(Candidature).filter(Candidature.numero_dossier == numero).one()
            print(f"  {numero}  moyenne {d.moyenne_bac}  notes "
                  f"{d.note_math_bac}/{d.note_physique_bac}/{d.note_francais_bac}"
                  f"/{d.note_anglais_bac}  bac {d.annee_bac}")
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    basculer(vers_suspect="restaurer" not in " ".join(sys.argv))
