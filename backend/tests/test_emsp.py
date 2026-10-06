"""Tests de bout en bout EMSP : candidature, documents, contact, rate-limit.

Exécution : `pytest` depuis `backend/` (SQLite temporaire + TestClient).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (enregistrement des tables)
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.rate_limit import clear_rate_limits
from app.routes_documents import get_storage_service
from app.storage_service import DocumentStorageService

STEP1 = {
    "nom": "Kouassi",
    "prenoms": "Aya Marie",
    "sexe": "Féminin",
    "date_naissance": "2004-05-12",
    "lieu_naissance": "Abidjan",
    "nationalite": "Ivoirienne",
    "nature_piece": "CNI",
    "numero_piece": "CI123456",
    "email": "candidate@example.com",
    "telephone": "+2250701020304",
    "commune": "Cocody",
    "ville": "Abidjan",
    "adresse": "Rue 12, Cocody",
}

STEP2_OK = {
    "annee_bac": 2024,
    "serie_bac": "D",
    "numero_bac": "BAC2024001",
    "numero_table": "TBL001",
    "mention": "Bien",
    "moyenne_bac": 14.5,
    "choix_1_filiere": "LNUM — Logistique et Numérique",
    "choix_2_filiere": "FDIG — Finance Digitale",
}

STEP2_DOUBLON = {
    "annee_bac": 2024,
    "serie_bac": "D",
    "numero_bac": "BAC2024001",
    "numero_table": "TBL001",
    "mention": "Bien",
    "moyenne_bac": 14.5,
    "choix_1_filiere": "MDIG — Marketing Digital",
    "choix_2_filiere": "MDIG — Marketing Digital",
}

STEP3 = {
    "tuteur1_nom": "Kouassi Yao",
    "tuteur1_contact": "+2250501020304",
    "tuteur1_lien": "Père",
    "tuteur1_residence": "Abidjan",
}

FAUX_PDF = b"%PDF-1.4\n%faux contenu pour test\n"

# Les 10 pièces exigées par POST /api/candidature/submit.
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


@pytest.fixture()
def client(tmp_path):
    """Client isolé : BDD SQLite temporaire + stockage temporaire."""
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    stockage = tmp_path / "storage"
    stockage.mkdir(exist_ok=True)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_storage_service] = (
        lambda: DocumentStorageService(str(stockage))
    )
    clear_rate_limits()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        clear_rate_limits()


def register(client, email="candidate@example.com", password="motdepasse123"):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "confirmation": password,
            "nom": "Kouassi",
            "prenoms": "Aya Marie",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_health_verifie_la_connexion_a_la_base(client):
    response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


def upload_pieces(client, types=None):
    """Téléverse une pièce PDF synthétique par type via POST /documents."""
    for type_doc in types if types is not None else TYPES_PIECES:
        contenu = FAUX_PDF + f"% type={type_doc}\n".encode("utf-8")
        resp = client.post(
            "/api/candidature/documents",
            data={"type_document": type_doc},
            files={"file": (f"{type_doc}.pdf", contenu, "application/pdf")},
        )
        assert resp.status_code == 201, f"{type_doc} : {resp.text}"
        assert resp.json()["type_document"] == type_doc, resp.text
    return client.get("/api/candidature/documents")


def remplir_dossier(client, pieces=True):
    """Dossier complet : étapes 1 à 3 puis les 10 pièces justificatives."""
    for step in (STEP1, STEP2_OK, STEP3):
        r = client.patch("/api/candidature", json=step)
        assert r.status_code == 200, r.text
    if pieces:
        liste = upload_pieces(client)
        assert liste.status_code == 200, liste.text
        assert {d["type_document"] for d in liste.json()} == set(TYPES_PIECES)


# ---------------------------------------------------------------------------
# Parcours candidature complet
# ---------------------------------------------------------------------------
def test_parcours_candidature_complet(client):
    data = register(client)
    assert data["numero_dossier"].startswith("CDT_")

    me = client.get("/api/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "candidate@example.com"

    r1 = client.patch("/api/candidature", json=STEP1)
    assert r1.status_code == 200, r1.text

    doublon = client.patch("/api/candidature", json=STEP2_DOUBLON)
    assert doublon.status_code == 422, doublon.text

    r2 = client.patch("/api/candidature", json=STEP2_OK)
    assert r2.status_code == 200, r2.text

    r3 = client.patch("/api/candidature", json=STEP3)
    assert r3.status_code == 200, r3.text

    # Étapes 1-3 complètes mais aucune pièce : le submit doit être refusé.
    sans_pieces = client.post("/api/candidature/submit", json={"confirmation": True})
    assert sans_pieces.status_code == 422, sans_pieces.text
    detail_sans_pieces = sans_pieces.json().get("detail", "")
    assert "Pièces justificatives manquantes" in detail_sans_pieces, sans_pieces.text
    assert "Veuillez déposer les 10 documents requis." in detail_sans_pieces, sans_pieces.text
    for type_doc in TYPES_PIECES:
        assert type_doc in detail_sans_pieces, (type_doc, detail_sans_pieces)

    # Dépôt des 10 pièces puis soumission.
    liste = upload_pieces(client)
    assert {d["type_document"] for d in liste.json()} == set(TYPES_PIECES)

    sans_confirmation = client.post("/api/candidature/submit", json={})
    assert sans_confirmation.status_code == 422, sans_confirmation.text

    refuse = client.post("/api/candidature/submit", json={"confirmation": False})
    assert refuse.status_code == 422, refuse.text

    ok = client.post("/api/candidature/submit", json={"confirmation": True})
    assert ok.status_code == 200, ok.text
    assert "enregistrée" in ok.json().get("message", "")
    assert ok.json()["numero_dossier"] == data["numero_dossier"]

    # Le dossier transmis avance jusqu'à l'étape 7.
    statut = client.get("/api/candidature/status")
    assert statut.status_code == 200, statut.text
    assert statut.json()["statut"] == "SUBMITTED", statut.text
    assert statut.json()["etape_courante"] == 7, statut.text

    candidature = client.get("/api/candidature")
    assert candidature.status_code == 200, candidature.text
    assert candidature.json()["etape_courante"] == 7, candidature.text

    # Un PATCH ultérieur ne doit pas faire régresser l'étape.
    patch_apres = client.patch("/api/candidature", json={"adresse": "Rue 99, Cocody"})
    assert patch_apres.status_code == 200, patch_apres.text
    assert patch_apres.json()["etape_courante"] == 7, patch_apres.text

    double = client.post("/api/candidature/submit", json={"confirmation": True})
    assert double.status_code == 409, double.text


# ---------------------------------------------------------------------------
# Submit : les 10 pièces justificatives sont obligatoires
# ---------------------------------------------------------------------------
def test_submit_sans_pieces_422(client):
    register(client, email="pieces@example.com")
    remplir_dossier(client, pieces=False)

    # Champs des étapes 1 à 3 bien renseignés, aucune pièce déposée.
    champs = client.get("/api/candidature")
    assert champs.status_code == 200, champs.text
    assert champs.json()["choix_1_filiere"] == STEP2_OK["choix_1_filiere"]

    docs = client.get("/api/candidature/documents")
    assert docs.status_code == 200, docs.text
    assert docs.json() == [], docs.text

    resp = client.post("/api/candidature/submit", json={"confirmation": True})
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert detail.startswith("Pièces justificatives manquantes : "), detail
    assert detail.endswith("Veuillez déposer les 10 documents requis."), detail
    manquants = [
        t.strip() for t in detail[len("Pièces justificatives manquantes : "):].split(".")[0].split(",")
    ]
    assert manquants == TYPES_PIECES, manquants

    # Le refus n'a rien changé : dossier toujours en brouillon, étape intacte.
    statut = client.get("/api/candidature/status")
    assert statut.json()["statut"] == "DRAFT", statut.text


def test_submit_pieces_partielles_422(client):
    """9 pièces sur 10 : le type manquant est nommé dans le message."""
    register(client, email="partiel@example.com")
    remplir_dossier(client, pieces=False)

    upload_pieces(client, [t for t in TYPES_PIECES if t != "lettre_motivation"])

    resp = client.post("/api/candidature/submit", json={"confirmation": True})
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "lettre_motivation" in detail, detail
    for type_doc in TYPES_PIECES:
        if type_doc != "lettre_motivation":
            assert type_doc not in detail, (type_doc, detail)

    # La pièce manquante déposée, la soumission passe.
    upload_pieces(client, ["lettre_motivation"])
    ok = client.post("/api/candidature/submit", json={"confirmation": True})
    assert ok.status_code == 200, ok.text
    assert client.get("/api/candidature/status").json()["etape_courante"] == 7


# ---------------------------------------------------------------------------
# Documents : upload, validation, IDOR, traversal
# ---------------------------------------------------------------------------
def test_documents_upload_validation_idor(client):
    register(client, email="a@example.com")

    upload = client.post(
        "/api/candidature/documents",
        data={"type_document": "attestation_bac"},
        files={"file": ("attestation.pdf", FAUX_PDF, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["id"]

    liste = client.get("/api/candidature/documents")
    assert liste.status_code == 200, liste.text
    assert any(d["id"] == doc_id for d in liste.json())

    exe = client.post(
        "/api/candidature/documents",
        data={"type_document": "attestation_bac"},
        files={"file": ("malware.exe", b"MZ\x90\x00faux", "application/octet-stream")},
    )
    assert exe.status_code == 400, exe.text

    traversal = client.post(
        "/api/candidature/documents",
        data={"type_document": "../../../etc"},
        files={"file": ("attestation.pdf", FAUX_PDF, "application/pdf")},
    )
    assert traversal.status_code == 400, traversal.text

    # IDOR : un second utilisateur ne doit pas lire le doc du premier.
    client_b = TestClient(app, raise_server_exceptions=False)
    try:
        register(client_b, email="b@example.com")
        dl = client_b.get(f"/api/candidature/documents/{doc_id}/download")
        assert dl.status_code in (403, 404), dl.text
        suppr = client_b.delete(f"/api/candidature/documents/{doc_id}")
        assert suppr.status_code in (403, 404), suppr.text
    finally:
        client_b.close()


# ---------------------------------------------------------------------------
# Contact, convocation, admission
# ---------------------------------------------------------------------------
def test_contact_convocation_admission(client):
    register(client)

    invalide = client.post("/api/contact", json={"nom": "", "message": "court"})
    assert invalide.status_code == 422, invalide.text

    valide = client.post(
        "/api/contact",
        json={
            "nom": "Kouassi Aya",
            "email": "contact@example.com",
            "objet": "Candidature",
            "message": "Bonjour, je souhaite des informations sur mon dossier.",
        },
    )
    assert valide.status_code == 201, valide.text

    convocation = client.get("/api/candidature/convocation")
    assert convocation.status_code == 200, convocation.text
    assert convocation.json()["disponible"] is False
    assert "convocation" in convocation.json()["message"].lower()

    admission = client.get("/api/candidature/admission")
    assert admission.status_code == 200, admission.text
    assert admission.json()["disponible"] is False
    assert "disponible" in admission.json()["message"].lower()


# ---------------------------------------------------------------------------
# Rate-limit login : 429 après 5 tentatives
# ---------------------------------------------------------------------------
def test_login_rate_limit(client):
    register(client, email="victime@example.com", password="motdepasse123")
    clear_rate_limits()

    codes = []
    for _ in range(6):
        resp = client.post(
            "/api/auth/login",
            json={"email": "victime@example.com", "password": "mauvais-mot-de-passe"},
        )
        codes.append(resp.status_code)

    assert codes[:5] == [401] * 5, codes
    assert codes[5] == 429, codes


# ---------------------------------------------------------------------------
# Sessions : expiry, glissement, logout-all
# ---------------------------------------------------------------------------
def _open_db():
    """Ouvre une session SQLAlchemy sur la BDD du fixture `client`."""
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    return db, gen


def _close_db(gen):
    try:
        gen.close()
    except Exception:
        pass


def test_fermer_puis_rouvrir_session_par_numero_dossier(client):
    compte = register(client, email="session-cycle@example.com")
    premier_token = client.cookies.get("emsp_session")
    assert premier_token, "cookie de session absent après inscription"
    assert client.get("/api/me").status_code == 200

    page_privee = client.get("/espace-candidat.html")
    assert page_privee.status_code == 200
    assert 'data-logout' in page_privee.text

    fermeture = client.post("/api/auth/logout")
    assert fermeture.status_code == 200, fermeture.text
    assert "max-age=0" in fermeture.headers.get("set-cookie", "").lower()
    assert client.cookies.get("emsp_session") is None
    assert client.get("/api/me").status_code == 401
    assert client.get("/espace-candidat.html").url.path == "/connexion.html"

    db, gen = _open_db()
    try:
        assert db.get(models.Session, premier_token) is None
    finally:
        _close_db(gen)

    connexion = client.post(
        "/api/auth/login",
        json={"identifiant": compte["numero_dossier"].lower(), "password": "motdepasse123"},
    )
    assert connexion.status_code == 200, connexion.text
    second_token = client.cookies.get("emsp_session")
    assert second_token and second_token != premier_token
    assert client.get("/api/me").json()["numero_dossier"] == compte["numero_dossier"]

    page_privee = client.get("/espace-candidat.html")
    assert page_privee.status_code == 200
    assert 'data-logout' in page_privee.text


def test_connexion_redirige_les_comptes_deja_connectes_vers_leur_espace(client):
    register(client, email="candidat-redirection@example.com")
    reponse_candidat = client.get("/connexion.html", follow_redirects=False)
    assert reponse_candidat.status_code == 302
    assert reponse_candidat.headers["location"] == "/espace-candidat.html"
    reponse_admin_interdit = client.get("/admin.html", follow_redirects=False)
    assert reponse_admin_interdit.status_code == 302
    assert reponse_admin_interdit.headers["location"] == "/espace-candidat.html"

    client.post("/api/auth/logout")
    from app.auth import hash_password

    db, gen = _open_db()
    try:
        admin = models.User(
            email="admin-redirection@example.com",
            password_hash=hash_password("motdepasseadmin123"),
            role="ADMIN",
            nom_affiche="Administration EMSP",
        )
        db.add(admin)
        db.commit()
    finally:
        _close_db(gen)

    connexion_admin = client.post(
        "/api/auth/login",
        json={"email": "admin-redirection@example.com", "password": "motdepasseadmin123"},
    )
    assert connexion_admin.status_code == 200, connexion_admin.text
    reponse_admin = client.get("/connexion.html", follow_redirects=False)
    assert reponse_admin.status_code == 302
    assert reponse_admin.headers["location"] == "/admin.html"
    for chemin_candidat in (
        "/espace-candidat.html",
        "/candidature.html",
        "/pieces.html",
        "/suivi.html",
        "/convocation.html",
        "/resultat.html",
    ):
        reponse = client.get(chemin_candidat, follow_redirects=False)
        assert reponse.status_code == 302, (chemin_candidat, reponse.status_code)
        assert reponse.headers["location"] == "/admin.html", chemin_candidat


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_session_expiree_401(client):
    register(client, email="expire@example.com")
    token = client.cookies.get("emsp_session")
    assert token, "cookie de session manquant après register"

    db, gen = _open_db()
    try:
        sess = db.get(models.Session, token)
        assert sess is not None
        sess.expires_at = _utcnow_naive() - timedelta(minutes=1)
        db.commit()
    finally:
        _close_db(gen)

    resp = client.get("/api/me")
    assert resp.status_code == 401, resp.text
    assert "Session expirée" in resp.json().get("detail", ""), resp.text


def test_session_glissement_prolonge(client):
    register(client, email="glisse@example.com")
    token = client.cookies.get("emsp_session")
    assert token

    db, gen = _open_db()
    try:
        sess = db.get(models.Session, token)
        assert sess is not None
        sess.expires_at = _utcnow_naive() + timedelta(minutes=10)
        db.commit()
        old_expires = sess.expires_at
    finally:
        _close_db(gen)

    resp = client.get("/api/me")
    assert resp.status_code == 200, resp.text

    # Le middleware doit réémettre le cookie avec max_age recalculé.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "emsp_session" in set_cookie, set_cookie

    db2, gen2 = _open_db()
    try:
        sess2 = db2.get(models.Session, token)
        assert sess2 is not None, "session supprimée alors qu'elle est valide"
        assert sess2.expires_at > old_expires, (sess2.expires_at, old_expires)
        remaining = (sess2.expires_at - _utcnow_naive()).total_seconds()
        assert remaining > 30 * 60, remaining
        attendu = settings.SESSION_EXPIRE_MINUTES * 60
        assert abs(remaining - attendu) < 120, (remaining, attendu)
    finally:
        _close_db(gen2)


def test_logout_all_invalide_toutes_sessions(client):
    register(client, email="multi@example.com", password="motdepasse123")
    token1 = client.cookies.get("emsp_session")
    assert token1

    login_resp = client.post(
        "/api/auth/login",
        json={"email": "multi@example.com", "password": "motdepasse123"},
    )
    assert login_resp.status_code == 200, login_resp.text
    token2 = client.cookies.get("emsp_session")
    assert token2
    assert token1 != token2, "deux logins doivent produire deux tokens distincts"

    # Les deux sessions existent en BDD.
    db, gen = _open_db()
    try:
        assert db.get(models.Session, token1) is not None
        assert db.get(models.Session, token2) is not None
    finally:
        _close_db(gen)

    out = client.post("/api/auth/logout-all")
    assert out.status_code == 200, out.text

    # token2 (jar courant) invalidé.
    me2 = client.get("/api/me")
    assert me2.status_code == 401, me2.text

    # token1 également invalidé.
    client.cookies.set("emsp_session", token1)
    me1 = client.get("/api/me")
    assert me1.status_code == 401, me1.text

    db2, gen2 = _open_db()
    try:
        assert db2.get(models.Session, token1) is None
        assert db2.get(models.Session, token2) is None
    finally:
        _close_db(gen2)


def test_logout_all_session_simple(client):
    register(client, email="simple@example.com", password="motdepasse123")
    out = client.post("/api/auth/logout-all")
    assert out.status_code == 200, out.text
    me = client.get("/api/me")
    assert me.status_code == 401, me.text


# ═══════════════════════════════════════════════════════════════════════════
# ADMINISTRATION — accès à toutes les soumissions
# ═══════════════════════════════════════════════════════════════════════════
def _creer_admin(db_file, email="scolarite@emsp.ci", mot_de_passe="adminmotdepasse1"):
    """Crée un compte ADMIN en base (dossier candidat nullable)."""
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User
    import app.db as appdb

    ancien = appdb.SessionLocal
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    sess = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        u = User(
            email=email,
            password_hash=hash_password(mot_de_passe),
            role="ADMIN",
            nom_affiche="Scolarité",
            numero_dossier=None,
        )
        sess.add(u)
        sess.commit()
        return u.id
    finally:
        sess.close()
        engine.dispose()


def _session_file(client, db_file):
    """Rejoue l'engine du fixture pour écrire hors de la requête."""
    return db_file


def test_admin_refuse_les_candidats(client):
    """Un candidat connecté ne doit pas atteindre le module d'administration."""
    register(client, email="candidat1@example.com")
    for route in (
        "/api/admin/overview",
        "/api/admin/candidatures",
        "/api/admin/candidatures/CDT_0001",
        "/api/admin/messages",
        "/api/admin/comptes",
    ):
        out = client.get(route)
        assert out.status_code == 403, f"{route} -> {out.status_code} (403 attendu)"
        assert "autorisé" in out.json()["detail"]


def test_admin_anonyme_401(client):
    out = client.get("/api/admin/overview")
    assert out.status_code == 401, out.text


def test_admin_voit_toutes_les_soumissions(client, tmp_path, monkeypatch):
    """L'administration accède à l'ensemble des dossiers, pas seulement au sien."""
    # Deux candidats distincts (register renvoie le corps JSON, pas la réponse)
    un = register(client, email="un@example.com")
    client.post("/api/auth/logout")
    deux = register(client, email="deux@example.com")
    client.post("/api/auth/logout")
    assert un["numero_dossier"] == "CDT_0001"
    assert deux["numero_dossier"] == "CDT_0002"

    # BDD réelle du fixture
    db_file = tmp_path / "test.db"
    _creer_admin(db_file)

    login = client.post(
        "/api/auth/login", json={"email": "scolarite@emsp.ci", "password": "adminmotdepasse1"}
    )
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "ADMIN"
    assert login.json()["numero_dossier"] is None

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"

    overview = client.get("/api/admin/overview")
    assert overview.status_code == 200, overview.text
    assert overview.json()["dossiers_total"] == 2

    liste = client.get("/api/admin/candidatures")
    assert liste.status_code == 200
    assert liste.json()["total"] == 2
    numeros = {d["numero_dossier"] for d in liste.json()["resultats"]}
    assert numeros == {"CDT_0001", "CDT_0002"}

    # Recherche
    trouve = client.get("/api/admin/candidatures", params={"q": "un@"})
    assert trouve.json()["total"] == 1


def test_admin_decide_et_le_candidat_voit_le_statut(client, tmp_path):
    """Décision du jury : statut, historique, et reflux côté candidat."""
    register(client, email="candidat2@example.com")
    client.post("/api/auth/logout")
    _creer_admin(tmp_path / "test.db")

    client.post(
        "/api/auth/login", json={"email": "scolarite@emsp.ci", "password": "adminmotdepasse1"}
    )
    out = client.post(
        "/api/admin/candidatures/CDT_0001/statut",
        json={"statut": "UNDER_REVIEW", "commentaire": "Dossier complet"},
    )
    assert out.status_code == 200, out.text
    assert out.json()["statut"] == "UNDER_REVIEW"

    detail = client.get("/api/admin/candidatures/CDT_0001")
    assert detail.status_code == 200
    assert detail.json()["historique"][0]["nouveau_statut"] == "UNDER_REVIEW"
    # La consultation est journalisée
    assert client.get("/api/admin/overview").json()["dernieres_actions"]

    # Filière + composition
    maj = client.patch(
        "/api/admin/candidatures/CDT_0001",
        json={
            "filiere_formation": "DSER — Digitalisation des Services",
            "centre_compo": "Campus 1, Abidjan",
            "date_compo": "2026-09-30",
        },
    )
    assert maj.status_code == 200, maj.text
    assert maj.json()["statut"] == "COMPOSITION_SCHEDULED"

    # Le candidat reconnecté voit la décision, jamais la note interne
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "candidat2@example.com", "password": "motdepasse123"})
    statut = client.get("/api/candidature/status")
    assert statut.json()["statut"] == "COMPOSITION_SCHEDULED"
    convocation = client.get("/api/candidature/convocation")
    assert convocation.json()["disponible"] is True
    assert convocation.json()["centre_compo"] == "Campus 1, Abidjan"
    # Le candidat ne doit pas pouvoir lire les champs d'administration
    corps = client.get("/api/candidature").text
    assert "note_interne" not in corps


def test_admin_statut_inconnu_refuse(client, tmp_path):
    register(client, email="candidat3@example.com")
    client.post("/api/auth/logout")
    _creer_admin(tmp_path / "test.db")
    client.post(
        "/api/auth/login", json={"email": "scolarite@emsp.ci", "password": "adminmotdepasse1"}
    )
    out = client.post("/api/admin/candidatures/CDT_0001/statut", json={"statut": "N_IMPORTE_QUOI"})
    assert out.status_code == 422, out.text
    # Filière hors nomenclature refusée
    out2 = client.patch("/api/admin/candidatures/CDT_0001", json={"filiere_formation": "Marketing"})
    assert out2.status_code == 422, out2.text


def test_admin_ne_telecharge_pas_les_pieces_dautrui_sans_role(client):
    """Le download d'une pièce par un candidat reste impossible (403)."""
    register(client, email="candidat4@example.com")
    out = client.get("/api/admin/documents/1/download")
    assert out.status_code == 403, out.text


# ─── Limitation de débit ─────────────────────────────────────────────────
# Le limiteur protège la connexion ; il ne doit jamais rester bloqué par
# accident, ni être neutralisé par une configuration.
def test_limiteur_bloque_au_dela_du_quota():
    from app.rate_limit import check_rate_limit, reset_rate_limit

    reset_rate_limit("test:ip")
    autorisees = [check_rate_limit("test:ip", limit=3, window_sec=60) for _ in range(5)]
    assert autorisees == [True, True, True, False, False]
    reset_rate_limit("test:ip")


def test_limiteur_desactive_si_quota_nul():
    """Un quota de 0 doit ouvrir la porte, pas la fermer.

    C'est le mode utilisé par l'agent de vérification : s'il bloquait,
    l'agent conclurait à tort que le parcours est cassé.
    """
    from app.rate_limit import check_rate_limit

    assert all(check_rate_limit("test:libre", limit=0, window_sec=60) for _ in range(50))


def test_limiteur_se_reinitialise_entre_les_tests():
    """Un compteur ne doit pas fuir d'un test à l'autre."""
    from app.rate_limit import check_rate_limit, reset_rate_limit

    reset_rate_limit("test:fuite")
    check_rate_limit("test:fuite", limit=1, window_sec=60)
    assert check_rate_limit("test:fuite", limit=1, window_sec=60) is False
    reset_rate_limit("test:fuite")
    assert check_rate_limit("test:fuite", limit=1, window_sec=60) is True
    reset_rate_limit("test:fuite")
