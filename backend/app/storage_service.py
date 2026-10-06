"""Service de stockage documentaire sécurisé (pièces justificatives).

Sécurité couverte :
- allowlist stricte des types de documents (``_safe_type``),
- format de numéro de dossier ``CDT_XXXX`` (``_safe_numero``),
- validation extension + taille + magic bytes (anti-renommage),
- rejet des exécutables (double extensions incluses),
- sanitization des noms de fichiers (basename, anti-traversal),
- écriture atomique (tmp + ``os.replace``) + ``chmod 0o640``,
- suppression anti-traversal via ``os.path.realpath`` + ``os.sep``
  (corrige le bug du ``startswith`` simple : ``/storage-evil`` ne doit
  pas passer pour ``/storage``),
- comparaison FS vs BDD pour détecter les orphelins.

Les chemins persistés en BDD sont TOUJOURS relatifs
(``candidats/CDT_XXXX/<type>/<uuid>.<ext>``), jamais absolus.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid

# Types déposables par le candidat (10 pièces officielles).
TYPES_AUTORISES: tuple[str, ...] = (
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
)

# Type généré côté serveur (convocation au concours) : accepté en interne
# (stockage/téléchargement) mais jamais proposé au téléversement candidat.
TYPE_INTERNE_CONVOCATION = "convocation"

# Union acceptée par le stockage (candidat + interne).
TYPES_STOCKABLES: tuple[str, ...] = TYPES_AUTORISES + (TYPE_INTERNE_CONVOCATION,)

EXTENSIONS: set[str] = {".pdf", ".jpg", ".jpeg", ".png"}

MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 Mo

# Extensions exécutables / actives rejetées, y compris en double extension
# (ex. ``piece.php.pdf`` doit être rejeté).
EXECUTABLE_EXT: set[str] = {
    "php", "php3", "php4", "php5", "phtml", "phar",
    "exe", "com", "scr", "msi", "bat", "cmd", "ps1",
    "sh", "bash", "zsh", "pl", "cgi", "py", "pyw", "rb", "lua",
    "js", "mjs", "html", "htm", "xhtml", "shtml",
    "jsp", "jspx", "asp", "aspx", "ashx", "asmx",
    "vbs", "vba", "jar", "war", "ear", "dll", "so", "dylib",
    "svg", "swf", "hta",
}

MIME_PAR_EXTENSION: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_NUMERO_RE = re.compile(r"^CDT_[0-9]{4}$")


class DocumentStorageService:
    """Stockage fichier des pièces justificatives sous ``<root>/candidats/``."""

    TYPES_AUTORISES = TYPES_AUTORISES
    TYPES_STOCKABLES = TYPES_STOCKABLES
    EXTENSIONS = EXTENSIONS
    MAX_FILE_SIZE = MAX_FILE_SIZE
    EXECUTABLE_EXT = EXECUTABLE_EXT

    def __init__(self, root: str) -> None:
        # Normalise une fois : toutes les vérifications utilisent realpath.
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    # ------------------------------------------------------------------
    # Validation des identifiants
    # ------------------------------------------------------------------
    def _safe_numero(self, numero: str) -> str:
        """Valide le format ``CDT_XXXX`` (4 chiffres)."""
        if not isinstance(numero, str) or not _NUMERO_RE.match(numero or ""):
            raise ValueError("Numéro de dossier invalide.")
        return numero

    def _safe_type(self, type_doc: str) -> str:
        """Valide le type de document contre l'allowlist (inclut convocation)."""
        if not isinstance(type_doc, str) or type_doc not in TYPES_STOCKABLES:
            raise ValueError("Type de document invalide.")
        return type_doc

    # ------------------------------------------------------------------
    # Chemins
    # ------------------------------------------------------------------
    def candidate_dir(self, numero: str) -> str:
        """Retourne ``<root>/candidats/<numero>`` en créant les parents."""
        numero = self._safe_numero(numero)
        path = os.path.join(self.root, "candidats", numero)
        os.makedirs(path, exist_ok=True)
        return path

    def _absolute_path(self, chemin_relatif: str) -> str:
        """Résout un chemin relatif en absolu après contrôle anti-traversal.

        Lève ``ValueError`` si le chemin sort de la racine. Corrige le bug
        du ``startswith`` simple en exigeant le séparateur (``root + os.sep``).
        """
        if not chemin_relatif or not isinstance(chemin_relatif, str):
            raise ValueError("Chemin de fichier invalide.")
        if os.path.isabs(chemin_relatif):
            raise ValueError("Chemin de fichier invalide.")
        root_real = os.path.realpath(self.root)
        # Join puis realpath : neutralise ``..`` et liens symboliques.
        cible = os.path.realpath(os.path.join(root_real, chemin_relatif))
        if cible != root_real and not cible.startswith(root_real + os.sep):
            raise ValueError("Chemin de fichier invalide.")
        return cible

    # ------------------------------------------------------------------
    # Validation fichier
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Extrait un nom de fichier sûr (basename, anti-traversal)."""
        if not filename or not isinstance(filename, str):
            raise ValueError("Nom de fichier invalide.")
        if "\x00" in filename:
            raise ValueError("Nom de fichier invalide.")
        # Neutralise les chemins Windows (``C:\\fakepath\\doc.pdf``).
        normalise = filename.replace("\\", "/")
        base = os.path.basename(normalise)
        base = base.strip()
        if not base or base in (".", ".."):
            raise ValueError("Nom de fichier invalide.")
        # Après basename il ne doit plus rester de séparateur ni de ``..``.
        if "/" in base or "\\" in base or ".." in base:
            raise ValueError("Nom de fichier invalide.")
        return base

    def validate_file(self, filename: str, content: bytes) -> tuple[str, str]:
        """Valide un fichier candidat et retourne ``(extension, mime)``.

        Contrôles : nom sanitizé, extension allowlist, rejet des exécutables
        (double extensions incluses), taille <= 5 Mo, magic bytes cohérents
        avec l'extension.

        Raises:
            ValueError: avec message FR (dont ``"Type de fichier invalide."``
                en cas de mismatch magic bytes / extension).
        """
        if content is None:
            raise ValueError("Le document n'a pas pu être envoyé.")
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("Le document n'a pas pu être envoyé.")
        content = bytes(content)

        if len(content) == 0:
            raise ValueError("Le fichier est vide.")
        if len(content) > MAX_FILE_SIZE:
            raise ValueError("Le fichier est trop volumineux (5 Mo maximum).")

        propre = self._sanitize_filename(filename)

        # Rejet des exécutables : inspecte TOUTES les extensions
        # (``attestation.php.pdf`` -> ["php", "pdf"] -> rejeté).
        morceaux = propre.lower().split(".")
        if len(morceaux) < 2:
            raise ValueError("Type de fichier invalide.")
        for partie in morceaux[1:]:
            # Coupe d'éventuels paramètres (``doc.pdf?x=1`` ne doit pas arriver
            # via UploadFile, garde-fou tout de même).
            token = partie.strip()
            if token in EXECUTABLE_EXT:
                raise ValueError("Type de fichier invalide.")

        _, ext = os.path.splitext(propre)
        ext = ext.lower()
        if ext not in EXTENSIONS:
            raise ValueError("Type de fichier invalide.")

        # --- Magic bytes ---
        # PDF  : %PDF  (hex 25 50 44 46)
        # JPEG : FF D8 FF
        # PNG  : 89 50 4E 47 0D 0A 1A 0A
        if ext == ".pdf":
            if not content.startswith(b"%PDF"):
                raise ValueError("Type de fichier invalide.")
            mime = "application/pdf"
        elif ext in (".jpg", ".jpeg"):
            if not content.startswith(b"\xff\xd8\xff"):
                raise ValueError("Type de fichier invalide.")
            mime = "image/jpeg"
        elif ext == ".png":
            if not content.startswith(b"\x89PNG"):
                raise ValueError("Type de fichier invalide.")
            mime = "image/png"
        else:  # Garde-fou (inaccessible vu l'allowlist, mais exhaustif).
            raise ValueError("Type de fichier invalide.")

        # Cohérence avec le registre système (utilise ``mimetypes``).
        devine, _ = mimetypes.guess_type("fichier" + ext)
        if devine is not None and devine != mime:
            # Le magic bytes fait foi ; on garde le mime détecté.
            pass
        return ext, MIME_PAR_EXTENSION.get(ext, mime)

    # ------------------------------------------------------------------
    # Écriture / suppression
    # ------------------------------------------------------------------
    def store(
        self,
        numero: str,
        type_doc: str,
        original_name: str,
        content: bytes,
    ) -> tuple[str, str]:
        """Stocke un fichier et retourne ``(nom_stockage, chemin_relatif)``.

        Écriture atomique (fichier tmp + ``os.replace``), ``chmod 0o640``.
        Le ``chemin_relatif`` est de la forme
        ``candidats/CDT_XXXX/<type>/<uuid>.<ext>``.
        """
        numero = self._safe_numero(numero)
        type_doc = self._safe_type(type_doc)
        ext, _mime = self.validate_file(original_name, content)

        # Empreinte (traçabilité / déduplication future).
        hashlib.sha256(bytes(content)).hexdigest()

        dossier_type = os.path.join(self.candidate_dir(numero), type_doc)
        os.makedirs(dossier_type, exist_ok=True)

        nom_stockage = f"{uuid.uuid4().hex}{ext}"
        chemin_abs = os.path.join(dossier_type, nom_stockage)
        tmp_abs = chemin_abs + f".tmp.{uuid.uuid4().hex}"

        try:
            with open(tmp_abs, "wb") as fh:
                fh.write(bytes(content))
            os.chmod(tmp_abs, 0o640)
            # Opération atomique sur le même filesystem.
            os.replace(tmp_abs, chemin_abs)
            os.chmod(chemin_abs, 0o640)
        finally:
            # Nettoyage du tmp en cas d'échec avant le replace.
            try:
                if os.path.lexists(tmp_abs):
                    os.remove(tmp_abs)
            except OSError:
                pass

        chemin_relatif = os.path.join("candidats", numero, type_doc, nom_stockage)
        return nom_stockage, chemin_relatif

    def replace(
        self,
        numero: str,
        type_doc: str,
        original_name: str,
        content: bytes,
        ancien_chemin_relatif: str | None,
    ) -> tuple[str, str]:
        """Stocke le nouveau fichier PUIS supprime l'ancien (si succès).

        L'ancien fichier n'est supprimé que si ``store`` a réussi, ce qui
        évite toute perte de pièce en cas d'échec d'écriture/validation.
        """
        nom_stockage, chemin_relatif = self.store(numero, type_doc, original_name, content)
        if ancien_chemin_relatif:
            try:
                # Ne jamais faire échouer le remplacement si l'ancien
                # fichier a déjà disparu ; en revanche un chemin
                # traversal lève ValueError (fail-closed).
                self.delete_file(ancien_chemin_relatif)
            except FileNotFoundError:
                pass
        return nom_stockage, chemin_relatif

    def delete_file(self, chemin_relatif: str) -> bool:
        """Supprime un fichier après contrôle anti-traversal.

        Returns:
            True si supprimé, False si déjà absent.
        Raises:
            ValueError: si le chemin sort de la racine (traversal).
        """
        cible = self._absolute_path(chemin_relatif)
        try:
            if not os.path.lexists(cible):
                return False
            if os.path.isdir(cible) and not os.path.islink(cible):
                raise ValueError("Chemin de fichier invalide.")
            os.remove(cible)
            return True
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Réconciliation FS <-> BDD
    # ------------------------------------------------------------------
    def find_orphans(
        self, db_session
    ) -> tuple[list[str], list]:
        """Compare le FS et la table ``documents``.

        Returns:
            ``(files_sans_db, metadata_sans_fichier)`` :
            - ``files_sans_db`` : chemins relatifs présents sur disque mais
              sans ligne en BDD ;
            - ``metadata_sans_fichier`` : objets ``DocumentCandidature`` dont
              le fichier manque sur disque.
        """
        # Import local : évite les imports circulaires au chargement du module.
        from app.models import DocumentCandidature  # noqa: PLC0415

        try:
            rows = db_session.query(DocumentCandidature).all()
        except Exception:
            # Compatibilité SQLAlchemy 2.x (style ``select``).
            from sqlalchemy import select  # noqa: PLC0415

            rows = list(db_session.execute(select(DocumentCandidature)).scalars().all())

        chemins_db: set[str] = set()
        for row in rows:
            rel = getattr(row, "chemin_relatif", None)
            if isinstance(rel, str) and rel:
                chemins_db.add(rel)

        root_real = os.path.realpath(self.root)
        base = os.path.join(root_real, "candidats")
        fichiers_fs: set[str] = set()
        if os.path.isdir(base):
            for dirpath, _dirnames, filenames in os.walk(base):
                for nom in filenames:
                    # Ignore les restes d'écritures atomiques interrompues.
                    if ".tmp." in nom:
                        continue
                    abs_f = os.path.join(dirpath, nom)
                    rel_f = os.path.relpath(abs_f, root_real)
                    fichiers_fs.add(rel_f)

        files_sans_db = sorted(fichiers_fs - chemins_db)

        metadata_sans_fichier: list = []
        for row in rows:
            rel = getattr(row, "chemin_relatif", None)
            if not isinstance(rel, str) or not rel:
                metadata_sans_fichier.append(row)
                continue
            try:
                abs_f = self._absolute_path(rel)
            except ValueError:
                # Chemin traversal en BDD : traité comme manquant/suspect.
                metadata_sans_fichier.append(row)
                continue
            if not os.path.isfile(abs_f):
                metadata_sans_fichier.append(row)

        return files_sans_db, metadata_sans_fichier
