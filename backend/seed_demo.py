"""Jeu de démonstration : crée des dossiers à tous les stades du parcours.

Usage (depuis `backend/`) :
    python3 seed_demo.py            # crée ce qui manque
    python3 seed_demo.py --reset    # supprime les comptes de démo puis recrée
    python3 seed_demo.py --mot-de-passe secret   # mot de passe commun

Pourquoi : pour tester l'administration et les états (brouillon, soumis,
convocation, admis, non retenu) sans devoir remplir le formulaire 7 fois.
Les comptes créés sont reconnaissables à leur adresse `@demo.emsp.ci`.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta  # noqa: F401  (timedelta conservé pour le reset)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import hash_password
from app.db import SessionLocal, init_db
from app.models import (
    ActionAdmin,
    Candidature,
    DocumentCandidature,
    HistoriqueStatut,
    MessageContact,
    Session,
    User,
)
from app.pdf_documents import build_convocation_pdf
from app.routes_documents import get_storage_service

DOMAINE_DEMO = "@demo.emsp.ci"
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
TITRES = {
    "attestation_bac": "Attestation de réussite au baccalauréat",
    "releve_notes_bac": "Relevé de notes du baccalauréat",
    "piece_identite": "Carte nationale d'identité",
    "bulletins_seconde": "Bulletins de seconde",
    "bulletins_premiere": "Bulletins de première",
    "bulletins_terminale": "Bulletins de terminale",
    "photo_identite": "Photo d'identité",
    "lettre_motivation": "Lettre de motivation",
    "acte_naissance": "Acte de naissance",
    "cv": "Curriculum vitæ",
}


# ─────────────────────────── fabrication des PDF ───────────────────────────
def _pdf(titre: str, lignes: list[str]) -> bytes:
    """PDF minimal mais valide (l'en-tête %PDF est vérifié par le serveur)."""
    contenu = [titre, ""] + list(lignes)
    lignes_pdf = []
    for i, ligne in enumerate(contenu):
        echappe = ligne.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        lignes_pdf.append(f"({echappe}) Tj 0 -18 Td")
    flux = "\n".join(lignes_pdf).encode("latin-1", "replace")
    objets = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(flux)).encode() + b" >>\nstream\n" + flux + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    sortie = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, corps in enumerate(objets, start=1):
        offsets.append(len(sortie))
        sortie += f"{i} 0 obj\n".encode() + corps + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n".encode()
    sortie += b"0000000000 65535 f \n"
    for off in offsets:
        sortie += f"{off:010d} 00000 n \n".encode()
    sortie += (
        f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n"
    ).encode()
    return bytes(sortie)


def _deposer(service, db, numero: str, type_doc: str, data: bytes) -> None:
    """Dépose un fichier via le service officiel et enregistre ses métadonnées."""
    import hashlib
    import mimetypes

    nom_stockage, chemin_relatif = service.store(
        numero, type_doc, TITRES.get(type_doc, type_doc) + ".pdf", data
    )
    ancien = (
        db.query(DocumentCandidature)
        .filter(
            DocumentCandidature.numero_dossier == numero,
            DocumentCandidature.type_document == type_doc,
        )
        .first()
    )
    if ancien is not None:
        ancien.nom_stockage = nom_stockage
        ancien.chemin_relatif = chemin_relatif
        ancien.taille = len(data)
        ancien.sha256 = hashlib.sha256(data).hexdigest()
        ancien.statut = "UPLOADED"
        db.add(ancien)
        return
    db.add(
        DocumentCandidature(
            numero_dossier=numero,
            type_document=type_doc,
            nom_original=TITRES.get(type_doc, type_doc) + ".pdf",
            nom_stockage=nom_stockage,
            chemin_relatif=chemin_relatif,
            mime_type=mimetypes.guess_type("x.pdf")[0] or "application/pdf",
            taille=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            statut="UPLOADED",
        )
    )


# ─────────────────────────── les dossiers de démonstration ───────────────────────────
def _base(nom: str, prenoms: str, email: str, **extra):
    d = {
        "nom": nom,
        "prenoms": prenoms,
        "sexe": extra.pop("sexe", "Féminin"),
        "date_naissance": date(2004, 3, 17),
        "lieu_naissance": extra.pop("lieu_naissance", "Abidjan"),
        "nationalite": "Ivoirienne",
        "nature_piece": "CNI",
        "numero_piece": "CI" + str(abs(hash(nom + prenoms)) % 10_000_000),
        "telephone": "+225" + str(7_00000000 + abs(hash(email)) % 99999999),
        "commune": extra.pop("commune", "Cocody"),
        "ville": extra.pop("ville", "Abidjan"),
        "adresse": extra.pop("adresse", "Riviera 3, Rue L88"),
        "code_tresor_pay": extra.pop("code_tresor_pay", None),
    }
    d.update(extra)
    return d


def _scolaire(nom: str, prenoms: str, email: str, serie="C", moyenne=15.5, **extra):
    d = _base(nom, prenoms, email, **extra)
    d.update(
        {
            "annee_bac": 2024,
            "serie_bac": serie,
            "numero_bac": f"BAC2024{abs(hash(email)) % 9000 + 1000}",
            "numero_table": f"T{abs(hash(email)) % 90 + 10}",
            "mention": "Bien",
            "moyenne_bac": moyenne,
            "note_math_bac": min(20, round(moyenne + 1, 1)),
            "note_physique_bac": max(0, round(moyenne - 1.5, 1)),
            "note_francais_bac": moyenne,
            "note_anglais_bac": max(0, round(moyenne - 0.5, 1)),
        }
    )
    return d


def _tuteurs(prefixe: str):
    return {
        "tuteur1_nom": f"{prefixe} Jean-Baptiste",
        "tuteur1_contact": "+2250102030405",
        "tuteur1_lien": "Père",
        "tuteur1_residence": "Yopougon, Abidjan",
        "tuteur2_nom": f"Aya {prefixe}",
        "tuteur2_contact": "+2250505060708",
        "tuteur2_lien": "Mère",
        "tuteur2_residence": "Cocody Riviera, Abidjan",
    }


def dossiers_demo() -> list[dict]:
    """Chaque entrée décrit un compte, son remplissage et son état final."""
    return [
        {
            "email": "brouillon@demo.emsp.ci",
            "etat": "DRAFT",
            "etape": 1,
            "note": "Candidat qui vient d'ouvrir sa candidature : l'étape 1 est à moitié remplie.",
            "champs": {**_base("N'Guessan", "Aya", "brouillon@demo.emsp.ci"), "email": "brouillon@demo.emsp.ci"},
        },
        {
            "email": "presque@demo.emsp.ci",
            "etat": "DRAFT",
            "etape": 5,
            "note": "Dossier complet SAUF les pièces : la soumission doit être refusée (il manque 10 pièces).",
            "champs": {
                **_scolaire("Konan", "Kouadio Serge", "presque@demo.emsp.ci", moyenne=16.0),
                **_tuteurs("Konan"),
                "choix_1_filiere": "LNUM — Logistique et Numérique",
                "choix_2_filiere": "FDIG — Finance Digitale",
                "email": "presque@demo.emsp.ci",
            },
        },
        {
            "email": "soumis@demo.emsp.ci",
            "etat": "SUBMITTED",
            "etape": 7,
            "pieces": True,
            "note": "Dossier soumis et complet : visible dans la liste d'administration, prêt à être examiné.",
            "champs": {
                **_scolaire("Bakary", "Adama", "soumis@demo.emsp.ci", serie="D", moyenne=14.2),
                **_tuteurs("Bakary"),
                "choix_1_filiere": "MDIG — Marketing Digital",
                "choix_2_filiere": "DSER — Digitalisation des Services",
                "email": "soumis@demo.emsp.ci",
                "dossier_valide": True,
            },
        },
        {
            "email": "convoque@demo.emsp.ci",
            "etat": "COMPOSITION_SCHEDULED",
            "etape": 7,
            "pieces": True,
            "convocation": True,
            "note": "Convocation programmée : le candidat voit la date, le centre et télécharge le PDF officiel.",
            "champs": {
                **_scolaire("Traoré", "Awa", "convoque@demo.emsp.ci", moyenne=16.8),
                **_tuteurs("Traoré"),
                "choix_1_filiere": "GARE — Gestion des Activités Régulées de l'Économie",
                "choix_2_filiere": "LNUM — Logistique et Numérique",
                "email": "convoque@demo.emsp.ci",
                "dossier_valide": True,
                # Date réelle de la session 2026 : les oraux eurent lieu le
                # 4 septembre 2026. Une date calculée sur le jour donnerait
                # une épreuve à passer après la proclamation des résultats.
                "date_compo": date(2026, 9, 4),
                "heure_compo": "08:30",
                "centre_compo": "Campus 1 — Abidjan, salle B",
            },
        },
        {
            "email": "admis@demo.emsp.ci",
            "etat": "ADMITTED",
            "etape": 7,
            "pieces": True,
            "convocation": True,
            "note": "Admis : la page Résultat affiche la félicitation et la filière retenue.",
            "champs": {
                **_scolaire("Yao", "Kra Amidou", "admis@demo.emsp.ci", moyenne=17.4),
                **_tuteurs("Yao"),
                "choix_1_filiere": "LNUM — Logistique et Numérique",
                "email": "admis@demo.emsp.ci",
                "dossier_valide": True,
                "admis_concours": True,
                "filiere_formation": "LNUM — Logistique et Numérique",
                "heure_compo": "08:30",
                "date_compo": date(2026, 9, 4),
                "centre_compo": "Campus 1 — Abidjan, salle A",
                "note_math_compo": 15.5,
                "note_francais_compo": 14.0,
                "note_anglais_compo": 13.5,
                "note_psycho_compo": 14.5,
            },
        },
        {
            "email": "refuse@demo.emsp.ci",
            "etat": "REJECTED",
            "etape": 7,
            "pieces": True,
            "note": "Non retenu : le motif est consultable par l'administration, jamais par le candidat.",
            "champs": {
                **_scolaire("Diarra", "Salimata", "refuse@demo.emsp.ci", moyenne=11.4),
                **_tuteurs("Diarra"),
                "choix_1_filiere": "DSER — Digitalisation des Services",
                "email": "refuse@demo.emsp.ci",
                "dossier_valide": True,
                "admis_concours": False,
                "motif_refus": "Moyenne générale insuffisante au regard des exigences de la filière.",
                "note_interne": "Dossier complet et sérieux, mais profil trop éloigné des prérequis. "
                "À reconsidérer pour une rentrée tardive si la|Note moyenne remonte.",
            },
        },
    ]


ADMIN_DEMO = {
    "email": "admin@emsp.ci",
    "password": "AdminEmsp2026",
    "nom": "Scolarité EMSP",
    "second": "directeur@emsp.ci",
}

# Les messages de démonstration portent le domaine de démonstration, et
# non un `@exemple.ci` : ce domaine réservé par la RFC 2606 est
# indifférenciable d'une adresse réelle, donc un nettoyage ne pouvait pas
# les viser sans risquer de supprimer les messages d'un vrai contact.
MESSAGES_DEMO = [
    ("Aya N'Guessan", "aya.nguessan@demo.emsp.ci", "+2250701020304", "Candidature",
     "Bonjour, quel est le délai pour déposer les bulletins de terminale ? Merci d'avance."),
    ("Mamadou Touré", "m.toure@demo.emsp.ci", None, "Documents",
     "Ma photo d'identité est refusée par le site, alors qu'elle fait 2 Mo en JPG. Que faire ?"),
    ("Fatou Bamba", "fatou.bamba@demo.emsp.ci", "+2250505060607", "Admission",
     "À quelle date les résultats de la session précédente ont-ils été publiés ?"),
]

# (ancien_statut, nouveau_statut, commentaire) — l'ordre est celui du jury.
HISTORIQUE: dict[str, list[tuple[str | None, str, str]]] = {
    "COMPOSITION_SCHEDULED": [
        (None, "SUBMITTED", "Dossier transmis au jury"),
        ("SUBMITTED", "UNDER_REVIEW", "Examen du dossier"),
        ("UNDER_REVIEW", "VALIDATED", "Dossier jugé recevable"),
    ],
    "ADMITTED": [
        (None, "SUBMITTED", "Dossier transmis au jury"),
        ("SUBMITTED", "UNDER_REVIEW", "Examen du dossier"),
        ("UNDER_REVIEW", "VALIDATED", "Dossier jugé recevable"),
        ("VALIDATED", "COMPOSITION_SCHEDULED", "Convocation programmée"),
        ("COMPOSITION_SCHEDULED", "ADMITTED", "Résultat : admis en Logistique et Numérique"),
    ],
    "REJECTED": [
        (None, "SUBMITTED", "Dossier transmis au jury"),
        ("SUBMITTED", "UNDER_REVIEW", "Examen du dossier"),
        ("UNDER_REVIEW", "REJECTED", "Profil ne répond pas aux prérequis"),
    ],
}


# ─────────────────────────── exécution ───────────────────────────
def executer(mot_de_passe: str, reset: bool) -> int:
    init_db()
    # On appelle la fabrique officielle : la racine du stockage est ainsi
    # définie en un seul endroit, jamais recalculée ici (sinon on dépose les
    # fichiers ailleurs que l'API ne les cherche).
    service = get_storage_service()

    db = SessionLocal()
    crees, ignores = [], []
    try:
        if reset:
            comptes = db.query(User).filter(User.email.like(f"%{DOMAINE_DEMO}")).all()
            # Les fichiers physique d'abord : une ligne supprimée en base ne
            # sait pas se nettoyer elle-même, et un dossier de démonstration
            # recree par-dessus laisse ses doublons sur le disque pour
            # toujours — invisible, et growing à chaque campagne de test.
            orphans: list[str] = []
            for u in comptes:
                if u.numero_dossier:
                    for doc in db.query(DocumentCandidature).filter(
                        DocumentCandidature.numero_dossier == u.numero_dossier
                    ).all():
                        orphans.append(doc.chemin_relatif)
                    db.query(HistoriqueStatut).filter(
                        HistoriqueStatut.numero_dossier == u.numero_dossier
                    ).delete()
                    db.query(Candidature).filter(
                        Candidature.numero_dossier == u.numero_dossier
                    ).delete()
                db.delete(u)
            # Les sessions des comptes supprimés : sans cela, `--reset`
                # empilait les sessions de toutes les campagnes de test, et
                # leurs cookies restaient valables. On a vu 313 lignes.
            if comptes:
                db.query(Session).filter(
                    Session.user_id.in_([u.id for u in comptes])
                ).delete(synchronize_session=False)

            # Les messages ne sont PAS tous supprimés : la page de contact
            # est ouverte à tous, et un message réel d'un candidat n'a rien
            # à faire dans un nettoyage de démonstration. Seuls ceux écrits
            # depuis l'adresse de démonstration partent.
            db.query(MessageContact).filter(
                MessageContact.email.like(f"%{DOMAINE_DEMO}")
            ).delete(synchronize_session=False)
            db.commit()

            supprimes = 0
            for chemin in orphans:
                if service.delete_file(chemin):
                    supprimes += 1
            print("· Démonstration précédente supprimée.")
            if orphans:
                print(f"  {supprimes}/{len(orphans)} pièce(s) retirée(s) du disque.")
            if supprimes != len(orphans):
                print(f"  ⚠ {len(orphans) - supprimes} pièce(s)announcede(s) "
                      f"ont résisté : à vérifier sur le disque.")

        # Numéro suivant
        maxi = 0
        for (num,) in db.query(Candidature.numero_dossier).all():
            if num and num.startswith("CDT_"):
                try:
                    maxi = max(maxi, int(num.split("_")[1]))
                except ValueError:
                    pass

        for item in dossiers_demo():
            email = item["email"]
            if db.query(User).filter(User.email == email).first() is not None:
                ignores.append(email)
                continue
            maxi += 1
            numero = f"CDT_{maxi:04d}"
            champs = dict(item["champs"])
            etat = item["etat"]
            nb_pieces = 0

            champs.setdefault("nationalite", "Ivoirienne")
            candidature = Candidature(
                numero_dossier=numero,
                statut=etat,
                etape_courante=item["etape"],
                **champs,
            )
            if etat != "DRAFT":
                from datetime import datetime, timezone

                candidature.submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)
                candidature.reviewed_at = candidature.submitted_at
            db.add(candidature)
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(mot_de_passe),
                    numero_dossier=numero,
                    role="CANDIDAT",
                )
            )
            db.flush()

            if item.get("pieces"):
                for type_doc in TYPES_PIECES:
                    data = _pdf(
                        f"EMSP — {TITRES[type_doc]}",
                        [
                            f"Dossier : {numero}",
                            f"Candidat : {champs['prenoms']} {champs['nom']}",
                            "Document de démonstration généré automatiquement.",
                        ],
                    )
                    _deposer(service, db, numero, type_doc, data)
                    nb_pieces += 1
            if item.get("convocation"):
                data = build_convocation_pdf(candidature)
                _deposer(service, db, numero, "convocation", data)

            for ancien, nouveau, commentaire in HISTORIQUE.get(etat, []):
                db.add(
                    HistoriqueStatut(
                        numero_dossier=numero,
                        ancien_statut=ancien,
                        nouveau_statut=nouveau,
                        commentaire=commentaire,
                        par_admin="scolarite@emsp.ci",
                    )
                )
            if etat == "SUBMITTED":
                db.add(
                    HistoriqueStatut(
                        numero_dossier=numero,
                        ancien_statut="DRAFT",
                        nouveau_statut="SUBMITTED",
                        commentaire="Dossier transmis au jury",
                        par_admin="scolarite@emsp.ci",
                    )
                )
            db.add(
                ActionAdmin(
                    admin_id=None,
                    admin_email="scolarite@emsp.ci",
                    action="IMPORT_DEMO",
                    numero_dossier=numero,
                    detail=item["note"][:200],
                )
            )
            crees.append((numero, email, etat, nb_pieces))

        db.commit()  # libère le verrou d'écriture avant l'appel suivant

        # ─── Comptes d'administration de démonstration ───
        # (outil dédié : même code que la ligne de commande)
        from app.admin_cli import creer_admin

        for cle in ("email", "second"):
            # Ne jamais écraser un compte admin existant ni son mot de passe
            # lorsque le jeu de démo est lancé sur une base déjà utilisée.
            if db.query(User).filter(User.email == ADMIN_DEMO[cle]).first() is not None:
                print(f"  · Compte existant laissé intact : {ADMIN_DEMO[cle]}")
                continue
            ok, message = creer_admin(
                ADMIN_DEMO[cle], ADMIN_DEMO["password"], ADMIN_DEMO["nom"]
            )
            print(f"  · {message}")

        for nom, email, tel, objet, message in MESSAGES_DEMO:
            exists = db.query(MessageContact).filter(
                MessageContact.email == email,
                MessageContact.objet == objet,
                MessageContact.message == message,
            ).first()
            if exists is None:
                db.add(MessageContact(nom=nom, email=email, telephone=tel, objet=objet, message=message))

        db.commit()
    finally:
        db.close()

    print(f"\n{len(crees)} dossier(s) de démonstration créé(s) :\n")
    for numero, email, etat, nb in crees:
        print(f"  {numero}  {etat:<22} {nb:>2} pièce(s)  {email}")
    if ignores:
        print(f"\nDéjà présents, laissés intacts : {', '.join(ignores)}")
    print("\n" + "─" * 68)
    print(f"  Candidats   : mot de passe « {mot_de_passe} »")
    for item in dossiers_demo():
        print(f"    {item['email']:<26} {item['note'][:60]}")
    print(f"\n  Admin       : {ADMIN_DEMO['email']} / {ADMIN_DEMO['password']}")
    print(f"               {ADMIN_DEMO['second']} / {ADMIN_DEMO['password']}")
    print("─" * 68)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reset", action="store_true", help="supprime puis recrée la démo")
    p.add_argument("--mot-de-passe", default="DemoEmsp2026", help="mot de passe commun")
    args = p.parse_args()
    return executer(args.mot_de_passe, args.reset)


if __name__ == "__main__":
    sys.exit(main())
