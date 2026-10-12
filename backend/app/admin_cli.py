"""Promotion d'un administrateur existant et inventaire des comptes.

Usage (depuis ``backend/``) :
    python -m app.admin_cli promote --email admin@demo.emsp.ci
    python -m app.admin_cli list

La promotion conserve l'identifiant, le mot de passe et l'état du compte. Ce
module ne crée aucun compte et ne modifie aucun mot de passe.
"""

from __future__ import annotations

import sys

from sqlalchemy import func

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import User


def promouvoir_admin_existant(email: str | None = None) -> tuple[bool, str]:
    """Promouvoir un compte ADMIN existant sans toucher à ses identifiants.

    Si aucun e-mail n'est fourni, la promotion automatique n'est permise que
    lorsqu'il existe exactement un compte administrateur actif.
    """
    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        if email:
            utilisateur = db.query(User).filter(User.email == email).first()
            if utilisateur is None:
                return False, (
                    f"Aucun compte existant ne correspond à {email}. Aucun compte créé."
                )
            if (utilisateur.role or "").upper() not in {"ADMIN", "SUPER_ADMIN"}:
                return False, (
                    f"Le compte {email} n'est pas un compte administrateur. "
                    "Aucun changement effectué."
                )
            if utilisateur.numero_dossier is not None:
                return False, f"Le compte {email} est lié à un dossier candidat. Aucun changement effectué."
            if not utilisateur.actif:
                return False, f"Le compte administrateur {email} est désactivé. Il reste inchangé."
        else:
            administrateurs = (
                db.query(User)
                .filter(
                    User.role.in_(("ADMIN", "SUPER_ADMIN")),
                    User.actif.is_(True),
                    User.numero_dossier.is_(None),
                )
                .order_by(User.created_at.asc())
                .all()
            )
            if not administrateurs:
                return False, "Aucun compte administrateur actif à promouvoir. Aucun compte créé."
            if len(administrateurs) > 1:
                return False, (
                    f"{len(administrateurs)} comptes administrateurs actifs existent. "
                    "Définissez ADMIN_EMAIL avec l'adresse du compte existant à promouvoir."
                )
            utilisateur = administrateurs[0]

        if (utilisateur.role or "").upper() == "SUPER_ADMIN":
            return True, (
                "Le compte super-administrateur existant est déjà configuré : "
                f"{utilisateur.email}"
            )

        utilisateur.role = "SUPER_ADMIN"
        db.commit()
        return True, (
            f"Compte administrateur existant promu super-administrateur : {utilisateur.email}. "
            "Mot de passe et compte conservés."
        )
    finally:
        db.close()


def lister() -> None:
    db = SessionLocal()
    try:
        for u in db.query(User).order_by(User.created_at.desc()).all():
            print(
                f"{u.id:>4}  {u.role:<12} {'actif' if u.actif else 'OFF  '}  "
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

    if args and args[0] == "create":
        print(
            "La création d'un super-administrateur est désactivée. "
            "Utilisez le compte ADMIN existant via `promote`."
        )
        return 2

    if args and args[0] not in {"promote"}:
        print(
            "Usage : python -m app.admin_cli promote "
            "[--email compte-admin-existant@emsp.ci] | list"
        )
        return 2

    email = settings.ADMIN_EMAIL or None
    if args and args[0] == "promote":
        reste = args[1:]
        for index, argument in enumerate(reste):
            if argument == "--email" and index + 1 < len(reste):
                email = reste[index + 1]

    ok, message = promouvoir_admin_existant(email)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
