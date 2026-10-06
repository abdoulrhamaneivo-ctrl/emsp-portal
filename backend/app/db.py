"""Moteur SQLAlchemy, fabrique de sessions et helpers d'initialisation.

Compatible SQLite (dev) et Postgres (prod) via `DATABASE_URL`.
Toutes les requêtes passent par l'ORM (prepared statements) :
aucun SQL brut concaténé dans le code applicatif.
"""

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import settings


def _build_engine():
    url = settings.DATABASE_URL
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Requis pour l'usage FastAPI (sessions par requête, threads).
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Neon et la plupart des hébergeurs donnent une URL PostgreSQL
        # standard. Choisir explicitement Psycopg 3 évite de dépendre du
        # pilote par défaut de la version de SQLAlchemy installée.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return create_engine(url, **kwargs)


engine = _build_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dépendance FastAPI : fournit une session SQLAlchemy par requête."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Ajoutements de colonnes apportés après la première version du schéma.
# `create_all` ne modifie jamais une table existante : sans cette étape, une
# base déjà peuplée resterait avec l'ancien schéma et planterait au premier
# SELECT. Chaque entrée est (table, colonne, type SQL) ; l'opération est
# idempotente, elle peut donc être rejouée à chaque démarrage.
COLONNES_AJOUTEES = [
    ("users", "role", "VARCHAR(16) NOT NULL DEFAULT 'CANDIDAT'"),
    ("users", "nom_affiche", "VARCHAR(255)"),
    ("users", "actif", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "derniere_connexion", "DATETIME"),
    ("candidatures", "reviewed_at", "DATETIME"),
    ("candidatures", "heure_compo", "VARCHAR(5)"),
    ("candidatures", "note_interne", "TEXT"),
    ("candidatures", "motif_refus", "TEXT"),
    # Consentement du candidat à la lecture automatisée de ses pièces.
    # Tant qu'il n'est pas accordé, aucune pièce ne peut être transmise
    # à un fournisseur extérieur. `consentement_le` est l'horodatage :
    # un consentement sans date n'est pas un consentement.
    ("candidatures", "consentement_tiers", "BOOLEAN NOT NULL DEFAULT 0"),
    ("candidatures", "consentement_le", "DATETIME"),
    # Un administrateur n'a pas de dossier candidat : la colonne doit être
    # nullable. SQLite ne sait pas relâcher une contrainte existante, on
    # reconstruit donc la table si nécessaire (voir _relacher_dossier).
    ("sessions", "x", None),
]


def _relacher_dossier() -> None:
    """Rend `users.numero_dossier` nullable (Postgres + reconstruction SQLite).

    Un administrateur n'a pas de candidature : sans cela, impossible d'avoir
    un compte ADMIN en base. Sur SQLite on reconstruit la table en copiant
    les lignes, ce qui préserve les comptes existants.
    """
    from sqlalchemy import text as sql

    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "postgresql":
            conn.execute(
                sql("ALTER TABLE users ALTER COLUMN numero_dossier DROP NOT NULL")
            )
            return
        if dialect != "sqlite":
            return

        lignes = conn.execute(sql("PRAGMA table_info(users)")).fetchall()
        colonnes = [r[1] for r in lignes]
        if not colonnes or "numero_dossier" not in colonnes:
            return
        # NOT NULL est dans row[3] pour PRAGMA table_info
        idx_notnull = next((r for r in lignes if r[1] == "numero_dossier"), None)
        if idx_notnull is None or int(idx_notnull[3]) == 0:
            return  # déjà nullable

        def _sql(dtype: str, default: str) -> str:
            base = f"{dtype}"
            if default:
                base += f" DEFAULT {default}"
            if "NOT NULL" in dtype.upper():
                base += " NOT NULL"
            return base

        defs = []
        for r in lignes:
            nom, typ, notnull, dflt, pk = r[1], r[2], r[3], r[4], r[5]
            if nom == "id":
                defs.append(f'"id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT')
            elif nom == "numero_dossier":
                defs.append('"numero_dossier" VARCHAR(16)')
            elif notnull:
                defs.append(f'"{nom}" {_sql(typ, dflt if dflt else "")}')
            else:
                defs.append(f'"{nom}" {typ}')
        conn.execute(sql("PRAGMA foreign_keys=OFF"))
        conn.execute(sql("ALTER TABLE users RENAME TO users_avant_migration"))
        conn.execute(sql(f"CREATE TABLE users ({', '.join(defs)})"))
        comunes = [c for c in colonnes if c in _colonnes_de(conn, "users_avant_migration")]
        conn.execute(
            sql(
                f"INSERT INTO users ({', '.join(chr(34)+c+chr(34) for c in comunes)}) "
                f"SELECT {', '.join(chr(34)+c+chr(34) for c in comunes)} FROM users_avant_migration"
            )
        )
        conn.execute(sql("DROP TABLE users_avant_migration"))
        conn.execute(sql("PRAGMA foreign_keys=ON"))


def _colonnes_de(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(text(f'PRAGMA table_info("{table}")')).fetchall()]


# ── Migration de données : filières et séries du concours ────────────────
# L'institution est l'École Multinationale Supérieure des Postes. Six
# intitulés de filière et trois séries qui figuraient dans le schéma
# n'appartiennent à aucun concours de cet établissement : les conserver
# affirmerait une vérité fausse sur un dossier réel. On les efface donc,
# et on le dit — une migration destructive doit laisser une trace.
INTITULES_OBSOLETES = (
    "Prépa Scientifique",
    "Prépa Économique et Commerciale",
    "Informatique",
    "Génie logiciel",
    "Création digitale",
    "Infographie",
)
SERIES_OBSOLETES = ("E", "F", "G", "Autre")


def _aligner_concours() -> None:
    """Efface les valeurs de filière et de série qui n'existent pas."""
    marques: list[str] = []
    with engine.begin() as conn:
        for colonne in ("choix_1_filiere", "choix_2_filiere", "filiere_formation"):
            conditions = " OR ".join(f'"{colonne}" = :v{i}' for i in range(len(INTITULES_OBSOLETES)))
            params = {f"v{i}": v for i, v in enumerate(INTITULES_OBSOLETES)}
            res = conn.execute(
                text(f'UPDATE candidatures SET "{colonne}" = NULL WHERE {conditions}'),
                params,
            )
            if res.rowcount:
                marques.append(f"{colonne} : {res.rowcount}")
        res = conn.execute(
            text('UPDATE candidatures SET serie_bac = NULL WHERE serie_bac IN :series')
            .bindparams(sa.bindparam("series", expanding=True)),
            {"series": list(SERIES_OBSOLETES)},
        )
        if res.rowcount:
            marques.append(f"serie_bac : {res.rowcount}")
    if marques:
        print(f"[db] données hors concours effacées — {'; '.join(marques)}")


def appliquer_migrations_legeres() -> None:
    """Aligne une base existante sur le schéma actuel (idempotent)."""
    inspecteur = inspect(engine)
    tables = set(inspecteur.get_table_names())
    with engine.begin() as conn:
        dialect = conn.dialect.name
        for table, colonne, definition in COLONNES_AJOUTEES:
            if definition is None or table not in tables:
                continue
            existantes = {c["name"] for c in inspecteur.get_columns(table)}
            if colonne in existantes:
                continue
            if dialect == "postgresql":
                # Les définitions historiques sont écrites pour SQLite.
                # PostgreSQL utilise TIMESTAMP et des booléens TRUE/FALSE.
                definition = definition.replace("DATETIME", "TIMESTAMP")
                if "BOOLEAN" in definition:
                    definition = definition.replace("DEFAULT 1", "DEFAULT TRUE")
                    definition = definition.replace("DEFAULT 0", "DEFAULT FALSE")
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{colonne}" {definition}'))
    try:
        _relacher_dossier()
    except Exception as exc:  # pragma: no cover - jamais bloquant au démarrage
        print(f"[db] migration légère partielle : {type(exc).__name__}")
    try:
        _aligner_concours()
    except Exception as exc:  # pragma: no cover - jamais bloquant au démarrage
        print(f"[db] alignement concours partiel : {type(exc).__name__}")


def init_db() -> None:
    """Crée les tables si elles n'existent pas (dev / bootstrap).

    Import local pour éviter les imports circulaires (models -> db).
    """
    from app import models  # noqa: F401  (enregistrement des tables)

    Base.metadata.create_all(bind=engine)
    appliquer_migrations_legeres()
