"""Création et gestion des comptes administrateurs.

Usage :
    python -m app.admin_cli create --email admin@emsp.ci --password 'motdepasse' --nom "Scolarité"
    python -m app.admin_cli list

Sans argument, le script lit ADMIN_EMAIL / ADMIN_PASSWORD dans l'environnement
ou le fichier .env (voir app/config.py).
"""

from __future__ import annotations

import sys

from sqlalchemy import func

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import User


def creer_admin(email: str, password: str, nom: str) -> tuple[bool, str]:
    """Crée (ou réactive) un compte ADMIN. Ne peut pas être un compte candidat."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False, "Adresse e-mail invalide."
    if len(password or "") < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères."

    db = SessionLocal()
    try:
        existant = db.query(User).filter(User.email == email).first()
        if existant is not None:
            if (existant.role or "").upper() == "ADMIN":
                existant.actif = True
                existant.password_hash = hash_password(password)
                if nom:
                    existant.nom_affiche = nom
                db.commit()
                return True, f"Compte administrateur existant mis à jour : {email}"
            return False, (
                f"Un compte candidat existe déjà avec {email} : "
                "utilisez une autre adresse pour l'administration."
            )
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                role="ADMIN",
                nom_affiche=nom or "Administration EMSP",
                numero_dossier=None,  # un administrateur n'a pas de dossier candidat
            )
        )
        db.commit()
        return True, f"Compte administrateur créé : {email}"
    finally:
        db.close()


def lister() -> None:
    db = SessionLocal()
    try:
        for u in db.query(User).order_by(User.created_at.desc()).all():
            print(
                f"{u.id:>4}  {u.role:<9} {'actif' if u.actif else 'OFF  '}  "
                f"{u.email:<34} {u.numero_dossier or '— (admin)'}"
            )
        total = db.query(func.count(User.id)).scalar() or 0
        print(f"\n{total} compte{'s' if total > 1 else ''}.")
    finally:
        db.close()


def main(argv: list[str]) -> int:
    init_db()
    args = argv[1:]

    if args and args[0] == "list":
        lister()
        return 0

    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD
    nom = settings.ADMIN_NOM

    if args and args[0] == "create":
        reste = args[1:]
        for i, a in enumerate(reste):
            if a == "--email" and i + 1 < len(reste):
                email = reste[i + 1]
            if a == "--password" and i + 1 < len(reste):
                password = reste[i + 1]
            if a == "--nom" and i + 1 < len(reste):
                nom = reste[i + 1]

    if not email or not password:
        print(
            "Aucun identifiant fourni.\n"
            "  · ligne de commande : python -m app.admin_cli create "
            "--email admin@emsp.ci --password '…'\n"
            "  · ou variables      : ADMIN_EMAIL=… ADMIN_PASSWORD=…\n"
            "  · ou fichier .env   : ADMIN_EMAIL=… ADMIN_PASSWORD=…"
        )
        return 1

    ok, message = creer_admin(email, password, nom)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
