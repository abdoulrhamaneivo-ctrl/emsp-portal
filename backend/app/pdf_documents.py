"""Petits documents PDF institutionnels, sans dépendance externe à l'exécution."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import textwrap


_LOGO = Path(__file__).resolve().parent / "assets" / "emsp-logo.jpg"
_PAGE_W, _PAGE_H = 595.28, 841.89
_GREEN = (0.025, 0.243, 0.161)
_INK = (0.105, 0.15, 0.12)
_MUTED = (0.37, 0.42, 0.38)
_GOLD = (0.91, 0.75, 0.02)
_PAPER = (0.98, 0.975, 0.95)


def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _pdf_string(value: str) -> bytes:
    raw = str(value).replace("\r", " ").replace("\n", " ").encode("cp1252", "replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class _Page:
    def __init__(self) -> None:
        self.ops: list[bytes] = []

    def fill(self, x: float, y: float, w: float, h: float, color: tuple[float, float, float]) -> None:
        self.ops.append(
            f"{_n(color[0])} {_n(color[1])} {_n(color[2])} rg {_n(x)} {_n(y)} {_n(w)} {_n(h)} re f\n".encode("ascii")
        )

    def stroke_rect(
        self, x: float, y: float, w: float, h: float,
        color: tuple[float, float, float], width: float = 1,
    ) -> None:
        self.ops.append(
            f"{_n(color[0])} {_n(color[1])} {_n(color[2])} RG {_n(width)} w {_n(x)} {_n(y)} {_n(w)} {_n(h)} re S\n".encode("ascii")
        )

    def line(
        self, x1: float, y1: float, x2: float, y2: float,
        color: tuple[float, float, float] = _GOLD, width: float = 1,
    ) -> None:
        self.ops.append(
            f"{_n(color[0])} {_n(color[1])} {_n(color[2])} RG {_n(width)} w {_n(x1)} {_n(y1)} m {_n(x2)} {_n(y2)} l S\n".encode("ascii")
        )

    def text(
        self, x: float, y: float, value: str, size: float = 12,
        font: str = "F1", color: tuple[float, float, float] = _INK,
        align: str = "left",
    ) -> None:
        value = str(value)
        if align == "center":
            x -= _measure(value, size, font) / 2
        elif align == "right":
            x -= _measure(value, size, font)
        prefix = f"BT /{font} {_n(size)} Tf {_n(color[0])} {_n(color[1])} {_n(color[2])} rg 1 0 0 1 {_n(x)} {_n(y)} Tm ".encode("ascii")
        self.ops.append(prefix + _pdf_string(value) + b" Tj ET\n")

    def logo(self, x: float, y: float, w: float = 178, h: float = 57.5) -> None:
        self.ops.append(f"q {_n(w)} 0 0 {_n(h)} {_n(x)} {_n(y)} cm /Logo Do Q\n".encode("ascii"))


def _measure(value: str, size: float, font: str) -> float:
    factor = 0.49 if font in ("F3", "F4") else 0.51
    widths = {"i": 0.25, "l": 0.25, "I": 0.28, "m": 0.82, "w": 0.76, "W": 0.9, "M": 0.85, " ": 0.28}
    return sum(widths.get(char, factor) for char in value) * size


def _wrap(page: _Page, x: float, y: float, value: str, width: int, size: float = 11, leading: float = 17, **style) -> float:
    for line in textwrap.wrap(str(value), width=width, break_long_words=True, break_on_hyphens=False) or [""]:
        page.text(x, y, line, size=size, **style)
        y -= leading
    return y


def _date_fr(value: date | datetime | None) -> str:
    if value is None:
        return date.today().strftime("%d/%m/%Y")
    return value.strftime("%d/%m/%Y")


def _header(page: _Page, title: str, subtitle: str) -> None:
    page.fill(0, 0, _PAGE_W, _PAGE_H, (1, 1, 1))
    page.stroke_rect(28, 28, _PAGE_W - 56, _PAGE_H - 56, _GREEN, 1.1)
    page.stroke_rect(34, 34, _PAGE_W - 68, _PAGE_H - 68, _GOLD, 0.55)
    page.logo(49, 753)
    page.text(546, 797, "PORTAIL CANDIDAT", 8, "F2", _GREEN, "right")
    page.text(546, 782, "ÉCOLE · ABIDJAN", 8, "F1", _MUTED, "right")
    page.line(48, 741, 547, 741, _GOLD, 1.3)
    page.fill(48, 701, 499, 24, _PAPER)
    page.text(59, 709, "CONCOURS D’ENTRÉE  ·  SESSION 2026–2027", 9, "F2", _GREEN)
    page.text(_PAGE_W / 2, 651, title, 26, "F3", _GREEN, "center")
    page.text(_PAGE_W / 2, 625, subtitle, 10, "F1", _MUTED, "center")
    page.line(115, 606, 480, 606, _GOLD, 1)


def _signature_block(page: _Page, y: float) -> None:
    page.text(372, y + 44, "Pour l’École Multinationale", 9, "F1", _MUTED, "center")
    page.text(372, y + 30, "Supérieure des Postes", 9, "F1", _MUTED, "center")
    page.text(372, y + 14, "Direction de l’établissement", 9, "F2", _GREEN, "center")
    page.line(286, y, 458, y, _GREEN, 0.8)
    page.text(372, y - 14, "Signature habilitée et cachet", 8, "F1", _MUTED, "center")


def _footer(page: _Page, reference: str, demo: bool = False) -> None:
    page.line(48, 66, 547, 66, _GOLD, 0.7)
    if demo:
        page.text(_PAGE_W / 2, 80, "DOCUMENT DE DÉMONSTRATION · NON VALABLE", 7.2, "F2", (0.55, 0.2, 0.16), "center")
    page.text(48, 51, "Document émis depuis l’espace candidat EMSP", 7.5, "F1", _MUTED)
    page.text(547, 51, reference, 7.5, "F2", _GREEN, "right")


def _is_demo(candidature) -> bool:
    return str(getattr(candidature, "email", "") or "").lower().endswith("@demo.emsp.ci")


def _make_pdf(page: _Page) -> bytes:
    logo = _LOGO.read_bytes()
    content = b"".join(page.ops)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Lang (fr-FR) >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /ProcSet [/PDF /Text /ImageC] /Font << /F1 4 0 R /F2 5 0 R /F3 6 0 R /F4 7 0 R /F5 8 0 R >> /XObject << /Logo 9 0 R >> >> /Contents 10 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Italic /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /XObject /Subtype /Image /Width 341 /Height 110 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + str(len(logo)).encode("ascii") + b" >>\nstream\n" + logo + b"\nendstream",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def build_convocation_pdf(candidature) -> bytes:
    page = _Page()
    _header(page, "CONVOCATION AU CONCOURS", "Avis individuel de présentation aux épreuves")
    page.text(_PAGE_W / 2, 572, "Madame, Monsieur", 11, "F1", _MUTED, "center")
    name = f"{candidature.prenoms or ''} {candidature.nom or ''}".strip() or "Candidate / candidat"
    name_size = max(16, min(25, 25 - max(0, len(name) - 24) * 0.35))
    page.text(_PAGE_W / 2, 535, name, name_size, "F3", _GREEN, "center")
    page.text(_PAGE_W / 2, 514, f"Numéro de dossier : {candidature.numero_dossier}", 10, "F2", _MUTED, "center")
    page.fill(48, 458, 499, 34, _GREEN)
    page.text(_PAGE_W / 2, 470, "EST PRIÉ(E) DE SE PRÉSENTER AUX ÉPREUVES", 11, "F2", (1, 1, 1), "center")

    boxes = [(48, "DATE", candidature.date_compo.strftime("%d/%m/%Y") if candidature.date_compo else "À confirmer"),
             (218, "HEURE", candidature.heure_compo or "À confirmer"),
             (388, "DOSSIER", candidature.numero_dossier or "—")]
    for x, label, value in boxes:
        page.fill(x, 373, 159, 61, _PAPER)
        page.stroke_rect(x, 373, 159, 61, _GOLD, 0.5)
        page.text(x + 12, 414, label, 7.5, "F2", _MUTED)
        page.text(x + 12, 390, value, 12, "F2", _GREEN)
    page.text(48, 346, "CENTRE D’EXAMEN", 8, "F2", _MUTED)
    centre_y = _wrap(page, 48, 325, candidature.centre_compo or "À confirmer par l’administration", 64, size=13, leading=17, font="F2", color=_GREEN)
    page.line(48, centre_y - 4, 547, centre_y - 4, _GOLD, 0.7)
    page.text(48, centre_y - 28, "À PRÉVOIR", 8, "F2", _GREEN)
    instructions = "Présentez-vous 30 minutes avant l’heure indiquée, muni(e) de votre pièce d’identité et de cette convocation. En cas d’empêchement, contactez le service des admissions de l’EMSP."
    _wrap(page, 48, centre_y - 49, instructions, 93, size=10, leading=16, font="F1", color=_INK)
    page.text(48, 158, f"Convocation établie le {_date_fr(datetime.now())}.", 8, "F1", _MUTED)
    _signature_block(page, 124)
    _footer(page, candidature.numero_dossier or "EMSP", demo=_is_demo(candidature))
    return _make_pdf(page)


def build_result_certificate_pdf(candidature) -> bytes:
    page = _Page()
    _header(page, "ATTESTATION DE RÉSULTAT", "Décision individuelle du jury d’admission")
    admitted = candidature.admis_concours is True
    status_color = _GREEN if admitted else (0.47, 0.16, 0.12)
    page.fill(48, 551, 499, 39, status_color)
    status = "ADMIS(E) AU CONCOURS" if admitted else "NON ADMIS(E) AU CONCOURS"
    page.text(_PAGE_W / 2, 565, status, 12, "F2", (1, 1, 1), "center")
    page.text(_PAGE_W / 2, 518, "Il est attesté que", 10, "F1", _MUTED, "center")
    name = f"{candidature.prenoms or ''} {candidature.nom or ''}".strip() or "Candidate / candidat"
    name_size = max(16, min(27, 27 - max(0, len(name) - 25) * 0.38))
    page.text(_PAGE_W / 2, 480, name, name_size, "F3", _GREEN, "center")
    page.line(113, 461, 482, 461, _GOLD, 0.8)

    cards = [(48, "NUMÉRO DE DOSSIER", candidature.numero_dossier or "—"),
             (304, "DATE DE DÉLIBÉRATION", _date_fr(candidature.reviewed_at))]
    for x, label, value in cards:
        page.fill(x, 403, 243, 43, _PAPER)
        page.stroke_rect(x, 403, 243, 43, _GOLD, 0.5)
        page.text(x + 12, 428, label, 7.2, "F2", _MUTED)
        page.text(x + 12, 411, value, 10.5, "F2", _GREEN)

    if admitted:
        page.text(48, 371, "Le jury déclare la candidate / le candidat admis(e) au concours d’entrée de l’EMSP.", 10, "F1", _INK)
        if candidature.filiere_formation:
            page.text(48, 348, "Formation attribuée", 8, "F2", _MUTED)
            page.text(48, 328, candidature.filiere_formation, 12, "F2", _GREEN)
        note_top = 294
    else:
        page.text(48, 371, "À l’issue de la délibération, la candidature n’a pas été retenue.", 10, "F1", _INK)
        note_top = 338

    notes = [
        ("Français", candidature.note_francais_compo),
        ("Mathématiques", candidature.note_math_compo),
        ("Anglais", candidature.note_anglais_compo),
        ("Psychotechnique", candidature.note_psycho_compo),
    ]
    notes = [(label, value) for label, value in notes if value is not None]
    if notes:
        page.text(48, note_top, "NOTES COMMUNIQUÉES PAR LE JURY", 8, "F2", _MUTED)
        y = note_top - 22
        for index in range(0, len(notes), 2):
            for col, (label, score) in enumerate(notes[index:index + 2]):
                x = 48 + col * 256
                page.text(x, y, label, 9, "F1", _INK)
                page.text(x + 210, y, f"{score:g} / 20", 9, "F2", _GREEN, "right")
                page.line(x, y - 5, x + 229, y - 5, _GOLD, 0.4)
            y -= 22

    page.text(48, 190, "Document établi à partir de la décision publiée dans l’espace candidat EMSP.", 8, "F1", _MUTED)
    _signature_block(page, 124)
    _footer(page, candidature.numero_dossier or "EMSP", demo=_is_demo(candidature))
    return _make_pdf(page)


_DEMO_DOCUMENT_LABELS = {
    "attestation_bac": "Attestation du baccalauréat",
    "releve_notes_bac": "Relevé de notes du baccalauréat",
    "piece_identite": "Pièce d’identité",
    "bulletins_seconde": "Bulletins de seconde",
    "bulletins_premiere": "Bulletins de première",
    "bulletins_terminale": "Bulletins de terminale",
    "photo_identite": "Photo d’identité",
    "lettre_motivation": "Lettre de motivation",
    "acte_naissance": "Acte de naissance",
    "cv": "Curriculum vitæ",
}


def build_demo_document_pdf(candidature, type_document: str) -> bytes:
    """Génère une pièce-échantillon brandée quand un fichier de démo manque.

    Les comptes ``@demo.emsp.ci`` ne doivent jamais présenter ces PDF comme
    des justificatifs recevables : chaque page porte un marquage explicite.
    """
    label = _DEMO_DOCUMENT_LABELS.get(type_document)
    if label is None:
        raise ValueError("Type de document de démonstration inconnu.")

    page = _Page()
    _header(page, "PIÈCE DE DÉMONSTRATION", "Exemple fictif · non recevable pour une candidature réelle")
    name = f"{candidature.prenoms or ''} {candidature.nom or ''}".strip() or "Candidate / candidat"
    page.text(_PAGE_W / 2, 565, name, 23, "F3", _GREEN, "center")
    page.text(_PAGE_W / 2, 540, f"Numéro de dossier : {candidature.numero_dossier or '—'}", 10, "F2", _MUTED, "center")
    page.fill(48, 460, 499, 58, _PAPER)
    page.stroke_rect(48, 460, 499, 58, _GOLD, 0.8)
    page.text(65, 496, "PIÈCE ATTENDUE", 8, "F2", _MUTED)
    page.text(65, 476, label, 13, "F2", _GREEN)
    page.fill(48, 356, 499, 88, (0.98, 0.94, 0.91))
    page.stroke_rect(48, 356, 499, 88, (0.63, 0.25, 0.19), 0.8)
    page.text(_PAGE_W / 2, 420, "FICTIF · DONNÉES DE DÉMONSTRATION", 10, "F2", (0.55, 0.2, 0.16), "center")
    _wrap(
        page,
        66,
        400,
        "Ce fichier sert uniquement à présenter le portail. Il ne reproduit aucun justificatif réel et ne peut pas être utilisé pour l’instruction d’un dossier.",
        82,
        size=10,
        leading=16,
        font="F1",
        color=_INK,
    )
    page.text(48, 320, "Données affichées", 8, "F2", _GREEN)
    page.text(48, 298, f"Nom : {candidature.nom or '—'}", 10, "F1", _INK)
    page.text(48, 278, f"Prénoms : {candidature.prenoms or '—'}", 10, "F1", _INK)
    page.text(48, 258, f"Pièce : {label}", 10, "F1", _INK)
    _signature_block(page, 124)
    _footer(page, candidature.numero_dossier or "EMSP", demo=True)
    return _make_pdf(page)
