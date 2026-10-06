"""Configuration centrale de l'application (DB + Auth + stockage).

Toutes les valeurs sont surchargeables via variables d'environnement
ou fichier `.env` (voir `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SQLite dev par défaut, Postgres prod via DATABASE_URL.
    # Ex : postgresql+psycopg2://user:password@localhost:5432/emsp
    DATABASE_URL: str = "sqlite:///./emsp.db"

    # Racine de stockage des pièces justificatives (chemins relatifs en BDD).
    DOCUMENT_STORAGE_ROOT: str = "./storage"

    # Secret applicatif (usage futur : signature/CSRF). Les sessions
    # actuelles sont des tokens opaques stockés en BDD (voir app/auth.py).
    SESSION_SECRET: str = "change-me-dev-only"

    # Durée de vie d'une session en minutes.
    SESSION_EXPIRE_MINUTES: int = 120

    # ─── E-mails transactionnels Brevo ────────────────────────────────
    BREVO_API_KEY: str = ""
    BREVO_SENDER_EMAIL: str = ""
    BREVO_SENDER_NAME: str = "EMSP · Portail candidat"
    # Domaine public de l'application. Utilisé dans les liens à usage unique.
    APP_PUBLIC_URL: str = "http://127.0.0.1:8765"
    PASSWORD_RESET_TTL_MINUTES: int = 30
    RATE_LIMIT_PASSWORD_RESET: int = 5

    # Mettre à True en production (HTTPS) pour le cookie `Secure`.
    COOKIE_SECURE: bool = False

    # ─── Limitation de débit ──────────────────────────────────────────
    # Tentatives de connexion et d'inscription par IP et par minute.
    # 0 désactive le limiteur : réservé à l'agent de vérification, qui
    # ouvre des dizaines de sessions sur SON PROPRE serveur de test.
    # Ne jamais désactiver en production.
    RATE_LIMIT_CONNEXION: int = 5
    RATE_LIMIT_INSCRIPTION: int = 5

    # ─── Vérification des dossiers ────────────────────────────────────
    # Les contrôles déterministes (doublons, forensics, cohérence des
    # notes et des dates) ne dépendent d'aucun de ces réglages : ils
    # tournent toujours. Ce bloc ne concerne que la LECTURE des pièces
    # par un modèle, qui sort les documents du serveur.
    #
    # L'interface retenue est celle de l'API OpenAI : un même code sert
    # OpenRouter, NVIDIA NIM, OpenAI, ou un modèle servi en local.
    VERIF_ACTIF: bool = False
    VERIF_BASE_URL: str = ""
    VERIF_CLE_API: str = ""
    VERIF_MODELE: str = ""
    VERIF_PIECES_MAX: int = 3
    VERIF_TOLERANCE_MOYENNE: float = 0.5
    VERIF_TIMEOUT_SEC: int = 60

    # Le consentement explicite du candidat est un préalable : sans lui,
    # aucune pièce ne peut quitter le serveur.
    CONSENTEMENT_TIERS_REQUIS: bool = True

    # ─── Administration ───────────────────────────────────────────────
    # Compte « super admin » créé automatiquement au démarrage si ces
    # variables sont renseignées. Sans ces variables, aucun compte admin
    # n'existe : la création se fait alors via le script app/admin_cli.py.
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""
    ADMIN_NOM: str = "Administration EMSP"


settings = Settings()
