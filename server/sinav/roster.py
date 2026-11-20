"""Student roster import (Excel .xlsx or CSV)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .naming import NUMARA_RE, header_key

NUMARA_HEADERS = {
    "numara", "no", "numarasi", "ogrencino", "ogrencinumarasi", "ogrno",
    "okulno", "okulnumarasi", "ogrencinumara",
}
AD_HEADERS = {"ad", "adi", "isim", "ismi", "ogrenciadi"}
SOYAD_HEADERS = {"soyad", "soyadi", "soyisim", "soyismi", "ogrencisoyadi"}
FULLNAME_HEADERS = {
    "adsoyad", "adisoyadi", "adivesoyadi", "adsoyadi", "isimsoyisim", "adsoyisim",
    "ogrenciadisoyadi", "adisoyad",
}

MAX_ROWS = 5000


class RosterError(ValueError):
    """Raised with a Turkish message when the list cannot be read."""


@dataclass
class RosterEntry:
    numara: str
    ad: str
    soyad: str
    # Added by hand in the panel ("Öğrenci ekle"), not read from the list file.
    manual: bool = False


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _numara_text(value: object) -> str:
    text = _cell_text(value)
    # "2021123456.0" style values coming from text cells
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.replace(" ", "")


def _rows_from_xlsx(data: bytes) -> list[list[object]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise RosterError("openpyxl kurulu değil; Excel dosyası okunamıyor.") from exc
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise RosterError(
            "Excel dosyası açılamadı. Dosyayı .xlsx biçiminde kaydedip yeniden deneyin."
        ) from exc
    try:
        sheet = workbook.worksheets[0]
        rows: list[list[object]] = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_ROWS:
                break
        return rows
    finally:
        workbook.close()


def _rows_from_csv(data: bytes) -> list[list[object]]:
    text = None
    for encoding in ("utf-8-sig", "cp1254"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RosterError("CSV dosyasının karakter kodlaması okunamadı (UTF-8 kaydedin).")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = max(";,\t", key=first_line.count) if first_line else ";"
    return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)][:MAX_ROWS]


def _find_header(rows: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    for index, row in enumerate(rows[:15]):
        columns: dict[str, int] = {}
        for col, cell in enumerate(row):
            key = header_key(_cell_text(cell))
            if not key:
                continue
            if key in NUMARA_HEADERS:
                columns.setdefault("numara", col)
            elif key in AD_HEADERS:
                columns.setdefault("ad", col)
            elif key in SOYAD_HEADERS:
                columns.setdefault("soyad", col)
            elif key in FULLNAME_HEADERS:
                columns.setdefault("adsoyad", col)
        if "numara" in columns and ("ad" in columns or "adsoyad" in columns):
            return index, columns
    return None


def parse_roster(data: bytes, filename: str) -> list[RosterEntry]:
    """Parse a roster file. Columns: numara, ad, soyad (header names are tolerant)."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        rows = _rows_from_xlsx(data)
    elif lower.endswith(".csv"):
        rows = _rows_from_csv(data)
    elif lower.endswith(".xls"):
        raise RosterError(
            "Eski .xls biçimi desteklenmiyor. Excel'de 'Farklı Kaydet → Excel Çalışma "
            "Kitabı (.xlsx)' ile kaydedip yeniden yükleyin."
        )
    else:
        raise RosterError("Öğrenci listesi .xlsx (Excel) veya .csv dosyası olmalı.")

    rows = [row for row in rows if any(_cell_text(cell) for cell in row)]
    if not rows:
        raise RosterError("Dosya boş.")

    header = _find_header(rows)
    if header is not None:
        start, columns = header[0] + 1, header[1]
    else:
        # No recognisable header: accept "numara, ad, soyad" in the first three columns.
        first = rows[0]
        first_numara = _numara_text(first[0]) if first else ""
        if len(first) >= 2 and NUMARA_RE.match(first_numara) and any(ch.isdigit() for ch in first_numara):
            start = 0
            columns = {"numara": 0, "ad": 1}
            if len(first) >= 3:
                columns["soyad"] = 2
        else:
            raise RosterError(
                "Sütun başlıkları bulunamadı. İlk satırda 'numara', 'ad', 'soyad' "
                "başlıkları olmalı."
            )

    def cell(row: list[object], key: str) -> object:
        col = columns.get(key)
        return row[col] if col is not None and col < len(row) else None

    entries: dict[str, RosterEntry] = {}
    for row in rows[start:]:
        numara = _numara_text(cell(row, "numara"))
        if not numara:
            continue
        if not NUMARA_RE.match(numara):
            raise RosterError(
                f"Geçersiz öğrenci numarası: '{numara}'. Numara yalnızca harf ve "
                "rakamdan oluşmalı (en fazla 20 karakter)."
            )
        if "ad" in columns:
            ad = _cell_text(cell(row, "ad"))
            soyad = _cell_text(cell(row, "soyad"))
            if not soyad and "adsoyad" not in columns and " " in ad:
                ad, soyad = ad.rsplit(" ", 1)
        else:
            full = _cell_text(cell(row, "adsoyad"))
            ad, _, soyad = full.rpartition(" ")
            if not ad:
                ad, soyad = soyad, ""
        entries[numara] = RosterEntry(numara=numara, ad=ad, soyad=soyad)

    if not entries:
        raise RosterError("Listede hiç öğrenci bulunamadı.")
    return list(entries.values())
