"""Tests de la vérification des dossiers.

Ce que ces tests ont à prouver, dans l'ordre d'importance :

1. les contrôles **détectent** vraiment ce qu'ils cherchent — un jeu de
   contrôles qui ne se déclenche jamais ne prouve rien ;
2. aucun chemin de vérification ne **modifie un dossier**. L'agent
   signale, le jury décide : c'est une promesse, donc elle se teste ;
3. rien ne part vers un fournisseur tant que le consentement n'est pas
   accordé ;
4. les bornes temporelles résistent au décalage horaire, source de
   faux positifs discrète.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.auth import create_session, hash_password
from app.models import Candidature, Controle, DocumentCandidature, User
from app.verif import rapport
from app.verif.forensics import Contexte, _posterieur, analyser

# ── fabrication de dossiers de test ──────────────────────────────────────


def _creer_user(db, email, role="CANDIDAT", actif=True):
    u = User(
        email=email,
        password_hash=hash_password("motdepasse-de-test"),
        role=role,
        nom_affiche=email.split("@")[0],
        actif=actif,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(u)
    db.commit()
    return u


def _creer_dossier(db, numero, **champs):
    defauts = {
        "email": f"{numero.lower()}@test.ci",
        "statut": "SUBMIS",
        "etape_courante": 7,
        "dossier_valide": True,
        "nom": "Kouassi",
        "prenoms": "Aya Marie",
        "sexe": "Féminin",
        "date_naissance": date(2004, 5, 12),
        "lieu_naissance": "Abidjan",
        "nationalite": "Ivoirienne",
        "annee_bac": 2024,
        "moyenne_bac": 14.5,
        "note_math_bac": 15.0,
        "note_physique_bac": 13.0,
        "note_francais_bac": 14.0,
        "note_anglais_bac": 16.0,
        "consentement_tiers": True,
        "consentement_le": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    defauts.update(champs)
    c = Candidature(**defauts, numero_dossier=numero)
    db.add(c)
    db.commit()
    return c


def _ajouter_piece(
    db,
    dossier,
    chemin_relatif,
    sha,
    mime="application/pdf",
    taille=1024,
    type_document="attestation_bac",
    fichier=None,
):
    if fichier is not None:
        chemin = os.path.join(rapport.racine_stockage(), chemin_relatif)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "wb") as f:
            f.write(fichier)
    d = DocumentCandidature(
        numero_dossier=dossier.numero_dossier,
        type_document=type_document,
        nom_original=os.path.basename(chemin_relatif),
        nom_stockage=os.path.basename(chemin_relatif),
        chemin_relatif=chemin_relatif,
        mime_type=mime,
        taille=taille,
        sha256=sha,
        statut="DEPOSE",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(d)
    db.commit()
    return d


PDF_VIDE = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
PNG_VIDE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Session isolée + racine de stockage temporaire."""
    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_ROOT", str(tmp_path / "storage"))
    (tmp_path / "storage").mkdir(exist_ok=True)
    engine = create_engine(
        f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db, tmp_path
    finally:
        db.close()


# ── 1. le double de pièce est détecté ────────────────────────────────────


def test_piece_identique_signalee_entre_deux_dossiers(env):
    """Le même fichier sur deux dossiers est le signal le plus fort."""
    db, racine = env
    a = _creer_dossier(db, "CDT_0001")
    b = _creer_dossier(db, "CDT_0002", email="b@test.ci")
    rel = "candidats/CDT_0001/attestation_bac/a.pdf"
    _ajouter_piece(db, a, rel, "sha-identique", fichier=PDF_VIDE)
    _ajouter_piece(db, b, "candidats/CDT_0002/attestation_bac/a.pdf", "sha-identique")

    constats = rapport.lancer_controles(db, a)
    doublons = [
        c
        for c in constats
        if c.controle == "doublon_piece" and c.statut == "signalement"
    ]
    assert len(doublons) == 1
    assert doublons[0].gravite == "majeur"
    assert "CDT_0002" in doublons[0].message


def meme_fichier_dans_le_meme_dossier_reste_normal(env):
    """Remplacer sa propre pièce n'est pas un constat."""
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    _ajouter_piece(
        db, a, "candidats/CDT_0001/attestation_bac/a.pdf", "sha-x", fichier=PDF_VIDE
    )
    _ajouter_piece(
        db, a, "candidats/CDT_0001/acte_naissance/b.pdf", "sha-x", fichier=PDF_VIDE
    )
    constats = rapport.lancer_controles(db, a)
    assert not [
        c
        for c in constats
        if c.controle == "doublon_piece" and c.statut == "signalement"
    ]


# ── 2. la nature réelle du fichier est vérifiée ──────────────────────────


def test_image_renommee_en_pdf_signalee(env):
    """Un PNG enregistré comme PDF doit être signalé."""
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    _ajouter_piece(
        db,
        a,
        "candidats/CDT_0001/attestation_bac/faux.pdf",
        "sha-1",
        mime="application/pdf",
        fichier=PNG_VIDE,
    )
    constats = rapport.lancer_controles(db, a)
    natures = [
        c
        for c in constats
        if c.controle == "nature_fichier" and c.statut == "signalement"
    ]
    assert len(natures) == 1
    assert natures[0].gravite == "majeur"


def test_pdf_honnete_passe_sans_constat(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    _ajouter_piece(
        db, a, "candidats/CDT_0001/attestation_bac/bon.pdf", "sha-2", fichier=PDF_VIDE
    )
    constats = rapport.lancer_controles(db, a)
    assert not [
        c
        for c in constats
        if c.controle == "nature_fichier" and c.statut == "signalement"
    ]


def test_piece_absente_du_disque_reste_indeterminee(env):
    """Un fichier introuvable ne doit pas être traité comme conforme."""
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    _ajouter_piece(db, a, "candidats/CDT_0001/attestation_bac/absent.pdf", "sha-3")
    constats = rapport.lancer_controles(db, a)
    natures = [c for c in constats if c.controle == "nature_fichier"]
    assert natures and natures[0].statut == "indeterminate"


# ── 3. cohérence des notes ────────────────────────────────────────────────


def test_note_hors_echelle_signalee(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001", note_math_bac=25.0)
    constats = rapport.lancer_controles(db, a)
    notes = [
        c
        for c in constats
        if c.controle == "coherence_notes" and c.statut == "signalement"
    ]
    assert any(c.gravite == "majeur" for c in notes)


def test_moyenne_loinee_des_notes_signalee_comme_heuristique(env):
    db, _ = env
    a = _creer_dossier(
        db,
        "CDT_0001",
        moyenne_bac=18.5,
        note_math_bac=11.0,
        note_physique_bac=10.0,
        note_francais_bac=12.0,
        note_anglais_bac=11.0,
    )
    constats = rapport.lancer_controles(db, a)
    notes = [
        c
        for c in constats
        if c.controle == "coherence_notes" and c.statut == "signalement"
    ]
    assert notes, "une moyenne à 18,5 avec des notes autour de 11 doit être signalée"
    assert notes[0].gravite == "mineur", "c'est une heuristique, pas une preuve"
    # Le message doit dire qu'il s'agit d'un seuil indicatif.
    assert "toutes les matières" in notes[0].message


def test_notes_coherentes_sans_constat(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    constats = rapport.lancer_controles(db, a)
    assert not [
        c
        for c in constats
        if c.controle == "coherence_notes" and c.statut == "signalement"
    ]


# ── 4. cohérence des dates ───────────────────────────────────────────────


def test_annee_bac_future_signalee(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001", annee_bac=2099)
    constats = rapport.lancer_controles(db, a)
    temps = [
        c
        for c in constats
        if c.controle == "coherence_temps" and c.statut == "signalement"
    ]
    assert temps and temps[0].gravite == "majeur"


def test_age_inhabituel_au_bac_signale(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001", date_naissance=date(1975, 1, 1), annee_bac=2024)
    constats = rapport.lancer_controles(db, a)
    temps = [
        c
        for c in constats
        if c.controle == "coherence_temps" and c.statut == "signalement"
    ]
    assert temps and temps[0].gravite == "mineur"


def test_horodatage_au_fuseau_pret_du_depot_ne_signale_rien():
    """17h58 locales et 15h58 UTC sont le même instant.

    Sans conversion, ce contrôle inonderait le rapport de faux positifs
    sur toutes les pièces déposées depuis une machine en UTC+2.
    """
    depot = datetime(2026, 9, 28, 15, 58, 0)
    assert _posterieur("2026:09:28 17:58:21+02:00", depot) is False
    assert _posterieur("2026:09:28 15:58:21+00:00", depot) is False
    # Un jour franc, en revanche, se signale.
    assert _posterieur("2026:10:02 10:00:00+02:00", depot) is True
    # Une heure d'horloge ne se signale pas.
    assert _posterieur("2026:09:28 18:30:00+02:00", depot) is False


# ── 5. la promesse centrale : ne jamais décider ──────────────────────────


def test_verifier_ne_modifie_jamais_le_dossier(env):
    """Aucun contrôle ne touche au statut, aux notes ni à la validation."""
    db, _ = env
    a = _creer_dossier(
        db, "CDT_0001", statut="SOUMIS_A_VERIFIER" if False else "SUBMIS"
    )
    avant = {
        "statut": a.statut,
        "moyenne": a.moyenne_bac,
        "math": a.note_math_bac,
        "valide": a.dossier_valide,
        "revu": a.reviewed_at,
        "admis": a.admis_concours,
        "note": a.note_interne,
        "motif": a.motif_refus,
    }
    # Un dossier fait pour être maximally suspect.
    _ajouter_piece(
        db,
        a,
        "candidats/CDT_0001/attestation_bac/x.pdf",
        "sha-z",
        mime="application/pdf",
        fichier=PNG_VIDE,
    )
    b = _creer_dossier(db, "CDT_0002", email="b@test.ci")
    _ajouter_piece(
        db, b, "candidats/CDT_0002/acte_naissance/y.pdf", "sha-z", fichier=PDF_VIDE
    )
    a.note_math_bac = 99.0
    a.annee_bac = 2099
    db.commit()

    rapport.lancer_controles(db, a)
    db.commit()
    db.refresh(a)

    assert a.statut == avant["statut"]
    assert a.moyenne_bac == avant["moyenne"]
    assert a.dossier_valide == avant["valide"]
    assert a.reviewed_at == avant["revu"]
    assert a.admis_concours == avant["admis"]
    assert a.note_interne == avant["note"]
    assert a.motif_refus == avant["motif"]


def test_constats_enregistres_et_purges_a_la_seconde_passe(env):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001", note_math_bac=30.0)
    rapport.lancer_controles(db, a)
    db.commit()
    premier = db.query(Controle).filter(Controle.numero_dossier == "CDT_0001").count()
    assert premier > 0

    rapport.lancer_controles(db, a)
    db.commit()
    second = db.query(Controle).filter(Controle.numero_dossier == "CDT_0001").count()
    assert (
        second == premier
    ), "une seconde analyse remplace la première, elle ne s'y ajoute pas"


def test_dossier_propre_ne_produit_rien_a_signaler(env):
    """Un dossier cohérent ne doit pas fabriquer de l'inquiétude."""
    db, _ = env
    a = _creer_dossier(db, "CDT_0001")
    _ajouter_piece(
        db, a, "candidats/CDT_0001/attestation_bac/ok.pdf", "sha-ok", fichier=PDF_VIDE
    )
    constats = rapport.lancer_controles(db, a)
    assert [c for c in constats if c.statut == "signalement"] == []


def test_un_controle_qui_echoue_n_empeche_pas_les_autres(env, monkeypatch):
    db, _ = env
    a = _creer_dossier(db, "CDT_0001", note_math_bac=42.0)
    _ajouter_piece(
        db, a, "candidats/CDT_0001/attestation_bac/ok.pdf", "sha-ok", fichier=PDF_VIDE
    )

    import app.verif.forensics as f

    def casse(ctx):
        raise RuntimeError("panne")

    others = [c for c in f.TOUS_LES_CONTROLES if c.__name__ != "controle_doublons"]
    monkeypatch.setattr(f, "TOUS_LES_CONTROLES", [casse] + others)
    constats = f.analyser(
        Contexte(
            candidature=a,
            documents=[],
            doublons={},
            racine=rapport.racine_stockage(),
        )
    )
    # Le contrôle en panne se déclare indisponible, et les autres rendent
    # quand même leur verdict.
    en_panne = [c for c in constats if c.statut == "indeterminate"]
    assert en_panne and en_panne[0].controle == "casse"
    assert en_panne[0].gravite == "info"
    assert any(
        c.controle == "coherence_notes" and c.statut == "signalement" for c in constats
    )


# ── 6. API d'administration ───────────────────────────────────────────────


@pytest.fixture()
def client_admin(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path/'a.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    _creer_user(db, "admin@emsp.ci", role="ADMIN")
    _creer_dossier(db, "CDT_0001", note_math_bac=30.0)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_ROOT", str(tmp_path / "storage"))
    (tmp_path / "storage").mkdir(exist_ok=True)
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_verification_refusee_sans_session(client_admin):
    assert (
        client_admin.post("/api/admin/candidatures/CDT_0001/controles").status_code
        == 401
    )


def test_api_verification_refusee_a_un_candidat(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path/'c.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    _creer_user(db, "candidat@emsp.ci")
    _creer_dossier(db, "CDT_0001")

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        client.post(
            "/api/auth/login",
            json={"email": "candidat@emsp.ci", "password": "motdepasse-de-test"},
        )
        r = client.post("/api/admin/candidatures/CDT_0001/controles")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_verification_lance_et_rend_le_rapport(client_admin):
    from app.rate_limit import clear_rate_limits

    clear_rate_limits()
    connexion = client_admin.post(
        "/api/auth/login",
        json={"email": "admin@emsp.ci", "password": "motdepasse-de-test"},
    )
    assert connexion.status_code == 200, connexion.text

    r = client_admin.post("/api/admin/candidatures/CDT_0001/controles")
    assert r.status_code == 200, r.text
    corps = r.json()
    # Le dossier de la fixture a une note de maths à 30 : hors échelle.
    assert corps["resume"]["majeur"] >= 1
    assert corps["resume"]["signalements"] >= 1
    controles = {c["controle"] for c in corps["constats"]}
    assert "coherence_notes" in controles

    # Le dossier n'a pas bougé d'un pouce.
    detail = client_admin.get("/api/admin/candidatures/CDT_0001").json()
    assert detail["dossier"]["statut"] == "SUBMIS"
    assert detail["dossier"]["moyenne_bac"] == 14.5
    assert "verification" in detail, "le rapport doit accompagner la fiche du dossier"

    # L'analyse est journalisée : une vérification laisse une trace.
    overview = client_admin.get("/api/admin/overview").json()
    actions = [a["action"] for a in overview.get("dernieres_actions", [])]
    assert "VERIFICATION_LANCEE" in actions


def test_lecture_du_rapport_ne_modifie_rien(client_admin):
    """Consulter ne doit pas être un acte d'administration."""
    from app.rate_limit import clear_rate_limits

    clear_rate_limits()
    client_admin.post(
        "/api/auth/login",
        json={"email": "admin@emsp.ci", "password": "motdepasse-de-test"},
    )
    avant = client_admin.get("/api/admin/overview").json().get("dernieres_actions", [])
    client_admin.get("/api/admin/candidatures/CDT_0001/controles")
    apres = client_admin.get("/api/admin/overview").json().get("dernieres_actions", [])
    assert len(avant) == len(apres)


# ── 7. consentement : sans lui, rien ne sort ────────────────────────────


@pytest.fixture()
def app_temps(tmp_path, monkeypatch):
    """Client et session pour dérouler une candidature jusqu'à la soumission."""
    engine = create_engine(
        f"sqlite:///{tmp_path/'s.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_ROOT", str(tmp_path / "storage"))
    (tmp_path / "storage").mkdir(exist_ok=True)
    app.dependency_overrides[get_db] = override_db
    from app.rate_limit import clear_rate_limits

    clear_rate_limits()
    try:
        yield TestClient(app, raise_server_exceptions=False), Session()
    finally:
        app.dependency_overrides.clear()
        clear_rate_limits()


@pytest.fixture()
def app_admin(tmp_path, monkeypatch):
    """Session d'administration et un dossier prêt à être modifié."""
    engine = create_engine(
        f"sqlite:///{tmp_path/'m.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    _creer_user(db, "admin@emsp.ci", role="ADMIN")
    _creer_dossier(db, "CDT_0001")

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_ROOT", str(tmp_path / "storage"))
    (tmp_path / "storage").mkdir(exist_ok=True)
    app.dependency_overrides[get_db] = override_db
    from app.rate_limit import clear_rate_limits

    clear_rate_limits()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        client.post(
            "/api/auth/login",
            json={"email": "admin@emsp.ci", "password": "motdepasse-de-test"},
        )
        yield client, db
    finally:
        app.dependency_overrides.clear()
        clear_rate_limits()


def _dossier_complet(client):
    """Crée un compte et dépose les 10 pièces : le dossier est soumettable."""
    from fastapi.testclient import TestClient as _TC

    r = client.post(
        "/api/auth/register",
        json={
            "email": "candidat@emsp.ci",
            "password": "motdepasse-de-test",
            "confirmation": "motdepasse-de-test",
            "nom": "Kouassi",
            "prenoms": "Aya Marie",
        },
    )
    assert r.status_code in (200, 201, 409), r.text
    client.post(
        "/api/auth/login",
        json={"email": "candidat@emsp.ci", "password": "motdepasse-de-test"},
    )
    client.patch(
        "/api/candidature",
        json={
            "sexe": "Féminin",
            "date_naissance": "2004-05-12",
            "lieu_naissance": "Abidjan",
            "nationalite": "Ivoirienne",
            "nature_piece": "CNI",
            "numero_piece": "CI123456",
            "telephone": "+2250701020304",
            "commune": "Cocody",
            "ville": "Abidjan",
            "adresse": "Rue 12, Cocody",
        },
    )
    client.patch(
        "/api/candidature",
        json={
            "annee_bac": 2024,
            "serie_bac": "D",
            "numero_bac": "BAC2024001",
            "numero_table": "TBL001",
            "mention": "Bien",
            "moyenne_bac": 14.5,
            "note_math_bac": 15,
            "note_physique_bac": 13,
            "note_francais_bac": 14,
            "note_anglais_bac": 16,
            "choix_1_filiere": "LNUM — Logistique et Numérique",
            "choix_2_filiere": "FDIG — Finance Digitale",
        },
    )
    client.patch(
        "/api/candidature",
        json={
            "tuteur1_nom": "Kouassi Yao",
            "tuteur1_contact": "+2250700000000",
            "tuteur1_lien": "Père",
            "tuteur1_residence": "Cocody, Abidjan",
        },
    )
    for type_doc in (
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
    ):
        client.post(
            "/api/candidature/documents",
            files={"file": (f"{type_doc}.pdf", PDF_VIDE, "application/pdf")},
            data={"type_document": type_doc},
        )
    return client


def test_soumettre_avec_consentement_horodate(app_temps):
    """Un accord sans date n'est pas un accord."""
    client, db = app_temps
    _dossier_complet(client)
    r = client.post(
        "/api/candidature/submit",
        json={"confirmation": True, "consentement_tiers": True},
    )
    assert r.status_code == 200, r.text
    dossier = (
        db.query(Candidature).filter(Candidature.numero_dossier == "CDT_0001").one()
    )
    assert dossier.consentement_tiers is True
    assert dossier.consentement_le is not None, "le consentement doit être daté"


def test_soumettre_sans_consentement_reste_possible(app_temps):
    """Refuser l'analyse automatisée ne doit jamais bloquer une candidature."""
    client, db = app_temps
    _dossier_complet(client)
    r = client.post(
        "/api/candidature/submit",
        json={"confirmation": True, "consentement_tiers": False},
    )
    assert r.status_code == 200, r.text
    dossier = (
        db.query(Candidature).filter(Candidature.numero_dossier == "CDT_0001").one()
    )
    assert dossier.consentement_tiers is False
    assert dossier.consentement_le is None
    assert dossier.statut == "SUBMITTED", "le dossier reste recevable"


def test_soumettre_sans_mentionner_le_consentement_reste_possible(app_temps):
    """Le champ est facultatif : un ancien client ne doit pas être rejeté."""
    client, _ = app_temps
    _dossier_complet(client)
    r = client.post("/api/candidature/submit", json={"confirmation": True})
    assert r.status_code == 200, r.text


def test_rapport_signale_le_manquement_de_consentement(env):
    db, _ = env
    dossier = _creer_dossier(
        db, "CDT_0001", consentement_tiers=False, consentement_le=None
    )
    r = rapport.resume(db, dossier)
    assert r["consentement"]["accorde"] is False
    assert r["consentement"]["exige"] is True
    assert r["consentement"]["le"] is None


# ── 8. l'API ne doit jamais mentir à l'écran ───────────────────────────


def test_detail_dossier_renvoie_le_nom(app_admin):
    """La fiche du jury affichait une ligne « Nom » vide.

    Le dossier existe, le nom aussi : c'est la réponse de l'API qui
    l'omettait, et l'écran ne pouvait qu'afficher une case vide.
    """
    client, db = app_admin
    db.query(Candidature).filter(
        Candidature.numero_dossier == "CDT_0001"
    ).one().nom = "Kouassi"
    db.commit()
    corps = client.get("/api/admin/candidatures/CDT_0001").json()
    assert corps["dossier"]["nom"] == "Kouassi"
    assert corps["dossier"]["prenoms"]


def test_admis_concours_refuse_explicitement(app_admin):
    """Envoyer l'admission par la route de détail ne doit pas échouer
    en silence : le client doit apprendre où agir."""
    client, db = app_admin
    r = client.patch("/api/admin/candidatures/CDT_0001", json={"admis_concours": True})
    assert r.status_code == 422
    assert "statut" in r.json()["detail"].lower()
    # Le dossier n'a pas bougé.
    dossier = (
        db.query(Candidature).filter(Candidature.numero_dossier == "CDT_0001").one()
    )
    assert dossier.admis_concours in (None, False)


# ── 9. Le concours réel ne doit jamais revenir aux anciennes filières ──


def test_les_cinq_specialites_du_concours_sont_acceptees():
    """Cinq spécialités, pas six. Un test qui passe avec des valeurs
    fausses ne teste rien : c'est ce que faisaient les anciens tests."""
    from app.schemas import SPECIALITES

    assert len(SPECIALITES) == 5, "le FS MENUM propose cinq spécialités"
    codes = {s.split(" — ")[0] for s in SPECIALITES}
    assert codes == {"LNUM", "FDIG", "MDIG", "DSER", "GARE"}


def test_aucune_trace_de_l_ancienne_ecole():
    """« Informatique », « Génie logiciel », « Infographie » n'appartiennent
    à aucun concours de l'EMSP. Ils ne doivent plus nulle part."""
    from app.schemas import SPECIALITES, FILIERES

    for liste in (SPECIALITES, FILIERES):
        for obsolete in (
            "Informatique",
            "Génie logiciel",
            "Infographie",
            "Création digitale",
            "Prépa Scientifique",
            "Prépa Économique et Commerciale",
        ):
            assert obsolete not in liste, f"« {obsolete} » a fait retour"


def test_les_sept_series_admises_sont_acceptees():
    """A, B, C, D, F1, F2, G2. « E » et « Autre » n'existent pas."""
    from app.routes_candidature import SERIES_BAC

    assert SERIES_BAC == {"A", "B", "C", "D", "F1", "F2", "G2"}
    for inexistante in ("E", "F", "G", "Autre"):
        assert inexistante not in SERIES_BAC


def test_la_liste_du_jury_est_alignee_sur_celle_du_candidat():
    """Si les deux divergent, le jury ne peut pas attribuer une spécialité
    que le candidat a le droit de demander."""
    from app.schemas import FILIERES
    from app.routes_admin import FILIERES as FILIERES_ADMIN

    assert FILIERES == FILIERES_ADMIN


def test_les_series_reelles_passe_entrement_par_l_api(app_temps):
    """Un bachelier série F1 doit pouvoir enregistrer son dossier."""
    client, _ = app_temps
    _dossier_complet(client)
    for serie in ("A", "B", "C", "D", "F1", "F2", "G2"):
        r = client.patch("/api/candidature", json={"serie_bac": serie})
        assert r.status_code == 200, f"série {serie} rejetée : {r.text}"


def test_une_serie_hors_concours_est_refusee(app_temps):
    client, _ = app_temps
    _dossier_complet(client)
    r = client.patch("/api/candidature", json={"serie_bac": "E"})
    assert r.status_code == 422


def test_une_specialite_reelle_passe_entrement_par_l_api(app_temps):
    """Les cinq spécialités du concours doivent être acceptées une par une.

    Les deux choix sont posés ensemble et toujours distincts : l'API
    refuse légitimement deux choix identiques, ce qui masquerait le test.
    """
    client, _ = app_temps
    _dossier_complet(client)
    from app.schemas import SPECIALITES

    for i, specialite in enumerate(SPECIALITES):
        autre = SPECIALITES[(i + 1) % len(SPECIALITES)]
        r = client.patch(
            "/api/candidature",
            json={
                "choix_1_filiere": specialite,
                "choix_2_filiere": autre,
            },
        )
        assert r.status_code == 200, f"« {specialite} » rejetée : {r.text}"


def test_une_ancienne_specialite_est_refusee(app_temps):
    client, _ = app_temps
    _dossier_complet(client)
    r = client.patch("/api/candidature", json={"choix_1_filiere": "Informatique"})
    assert r.status_code == 422


def test_les_specialites_affichees_par_le_backend_sont_celles_du_serveur():
    """Les cartes de formation générées par le serveur reflètent ses schémas."""
    from html import escape

    from app.schemas import SPECIALITES
    from app.ui import render_public_home

    page = render_public_home(None).body.decode("utf-8")

    for specialite in SPECIALITES:
        code, nom = (part.strip() for part in specialite.split("—", maxsplit=1))
        assert f'<span class="program-code">{escape(code)}</span>' in page, specialite
        assert f"<h3>{escape(nom)}</h3>" in page, specialite


def test_la_navigation_backend_suit_le_role_de_session():
    from app.models import User
    from app.ui import render_public_home

    visiteur = render_public_home(None).body.decode("utf-8").split("</header>", 1)[0]
    candidat = render_public_home(
        User(email="candidat@example.ci", role="CANDIDAT")
    ).body.decode("utf-8").split("</header>", 1)[0]
    admin = render_public_home(
        User(email="admin@example.ci", role="ADMIN")
    ).body.decode("utf-8").split("</header>", 1)[0]

    assert 'href="/connexion.html"' in visiteur
    assert 'href="/espace-candidat.html"' in candidat
    assert 'href="/admin.html"' not in candidat
    assert 'href="/admin.html"' in admin
    assert 'href="/candidature.html"' not in admin


def test_modele_vision_openai_compatible_est_appele_et_masque_les_identifiants(monkeypatch):
    """Le modèle reçoit l'image consentie et son texte ne réaffiche pas de téléphone."""
    import json
    from types import SimpleNamespace

    from app.config import settings
    from app.verif import modele

    monkeypatch.setattr(settings, "VERIF_ACTIF", True)
    monkeypatch.setattr(settings, "VERIF_BASE_URL", "https://ia.example/v1")
    monkeypatch.setattr(settings, "VERIF_CLE_API", "cle-de-test")
    monkeypatch.setattr(settings, "VERIF_MODELE", "modele-vision-test")
    monkeypatch.setattr(settings, "VERIF_TIMEOUT_SEC", 10)

    answer = {
        "constats": [{
            "controle": "identite",
            "statut": "signalement",
            "gravite": "mineur",
            "message": "Le numéro +225 01 02 03 04 05 06 diffère des données du dossier.",
        }]
    }
    payload = {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}
    observed = {}

    class FauxResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def faux_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["body"] = json.loads(request.data.decode("utf-8"))
        return FauxResponse()

    monkeypatch.setattr(modele, "urlopen", faux_urlopen)
    candidature = SimpleNamespace(
        nom="Kouassi", prenoms="Aya", date_naissance=None, annee_bac=None,
        serie_bac=None, moyenne_bac=None, note_math_bac=None,
        note_physique_bac=None, note_francais_bac=None, note_anglais_bac=None,
    )
    document = SimpleNamespace(type_document="piece_identite", mime_type="image/png")
    constats, methode = modele._appel_modele(document, PNG_VIDE, candidature)

    assert methode == "vision"
    assert observed["url"] == "https://ia.example/v1/chat/completions"
    assert observed["body"]["model"] == "modele-vision-test"
    assert observed["body"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "[numéro masqué]" in constats[0]["message"]
    assert "+225" not in constats[0]["message"]


def test_consentement_ia_se_donne_et_se_retire_apres_soumission(app_temps):
    """Le candidat garde la maîtrise du partage après avoir envoyé son dossier."""
    client, _ = app_temps
    _dossier_complet(client)

    avant = client.get("/api/candidature/consentement-ia")
    assert avant.status_code == 200, avant.text
    assert avant.json() == {"accorde": False, "le": None}

    accord = client.put("/api/candidature/consentement-ia", json={"consentement": True})
    assert accord.status_code == 200, accord.text
    assert accord.json()["accorde"] is True
    assert accord.json()["le"]

    retrait = client.put("/api/candidature/consentement-ia", json={"consentement": False})
    assert retrait.status_code == 200, retrait.text
    assert retrait.json()["accorde"] is False
    assert retrait.json()["le"] is None
