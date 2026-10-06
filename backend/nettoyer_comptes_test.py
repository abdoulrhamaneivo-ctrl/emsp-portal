"""Nettoie les comptes de test laissés par les agents de vérification.

Ne supprime QUE les comptes dont l'adresse commence par `test-` : les
comptes de démonstration (`brouillon@`, `presque@`, `soumis@`,
`convoque@`, `admis@`, `refuse@`, `admin@`, `directeur@`) et le dossier
de démonstration d'origine sont intacts.

Usage :  python3 nettoyer_comptes_test.py [--apercu]
"""
from __future__ import annotations

import os
import shutil
import sys

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.db import engine
from app.models import (
    ActionAdmin,
    Candidature,
    Controle,
    DocumentCandidature,
    Session as SessionConnexion,
    User,
)

PREFIXE = "test-"


def dossiers_associes(db) -> list[str]:
    return [
        numero
        for (numero,) in db.query(Candidature.numero_dossier)
        .join(User, User.numero_dossier == Candidature.numero_dossier)
        .filter(User.email.like(f"{PREFIXE}%"))
        .all()
    ]


def main() -> None:
    apercu = "--apercu" in sys.argv
    fabrique = sessionmaker(bind=engine)
    db = fabrique()
    try:
        comptes = db.query(User).filter(User.email.like(f"{PREFIXE}%")).all()
        numeros = dossiers_associes(db)
        if not comptes:
            print("aucun compte de test : rien à nettoyer")
            return

        print(f"{len(comptes)} compte(s) de test, {len(numeros)} dossier(s) associé(s)")
        for u in comptes:
            print(f"  - {u.email}  (dossier {u.numero_dossier})")
        if apercu:
            print("\naperçu : rien n'a été supprimé")
            return

        # L'ordre compte : les enfants avant les parents, sinon les clés
        # étrangères bloquent la suppression.
        db.query(Controle).filter(Controle.numero_dossier.in_(numeros)).delete(
            synchronize_session=False
        )
        db.query(DocumentCandidature).filter(
            DocumentCandidature.numero_dossier.in_(numeros)
        ).delete(synchronize_session=False)
        db.query(Candidature).filter(Candidature.numero_dossier.in_(numeros)).delete(
            synchronize_session=False
        )
        db.query(SessionConnexion).filter(
            SessionConnexion.user_id.in_([u.id for u in comptes])
        ).delete(synchronize_session=False)
        db.query(ActionAdmin).filter(
            ActionAdmin.admin_id.in_([u.id for u in comptes])
        ).delete(synchronize_session=False)
        db.query(User).filter(User.email.like(f"{PREFIXE}%")).delete(
            synchronize_session=False
        )
        db.commit()

        # Les fichiers sur disque ne sont pas dans la base : un dossier
        # laissé derrière garderait des pièces orphelines.
        racine = settings.DOCUMENT_STORAGE_ROOT
        if not os.path.isabs(racine):
            racine = os.path.abspath(os.path.join(os.path.dirname(__file__), racine))
        supprimes = 0
        for numero in numeros:
            chemin = os.path.join(racine, "candidats", numero)
            if os.path.isdir(chemin):
                shutil.rmtree(chemin)
                supprimes += 1
        print(f"\nsupprimé : {len(comptes)} compte(s), {len(numeros)} dossier(s) "
              f"en base, {supprimes} dossier(s) de fichiers")

        restants = db.query(User).filter(User.email.like(f"{PREFIXE}%")).count()
        print(f"comptes de test restants : {restants}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
