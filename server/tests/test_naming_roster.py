from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from sinav.naming import camel_name, name_key, natural_key, normalise_mac, submission_basename
from sinav.roster import RosterError, parse_roster


@pytest.mark.parametrize(
    ("ad", "soyad", "expected"),
    [
        ("Ahmet Şahin", "Çakır", "AhmetSahinCakir"),
        ("AHMET ŞAHİN", "ÇAKIR", "AhmetSahinCakir"),
        ("ışıl", "öztürk", "IsilOzturk"),
        ("İbrahim", "IŞIK", "IbrahimIsik"),
        ("Gül  Nur", "Ağaoğlu-Ünal", "GulNurAgaogluunal"),
        ("Âdem", "Kâhya", "AdemKahya"),
        ("", "", "Isimsiz"),
    ],
)
def test_camel_name(ad, soyad, expected):
    assert camel_name(ad, soyad) == expected


def test_submission_basename():
    assert submission_basename("2021000001", "Şükrü Can", "Özgüç") == "2021000001_SukruCanOzguc"


def test_name_key_is_turkish_insensitive():
    assert name_key("IŞIK  Çağrı") == name_key("ışık çağrı") == name_key("Isik Cagri")
    assert name_key("İNCİ") == name_key("inci") == name_key("INCI")
    assert name_key("Ali") != name_key("Veli")


def test_normalise_mac():
    assert normalise_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalise_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF"
    assert normalise_mac("00:00:00:00:00:00") == ""
    assert normalise_mac("xyz") == ""
    assert normalise_mac("") == ""


def test_natural_key_orders_numbers_numerically():
    assert sorted(["100", "20", "3", "A1"], key=natural_key) == ["3", "20", "100", "A1"]


def xlsx(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_roster_standard_headers():
    entries = parse_roster(xlsx([["numara", "ad", "soyad"], [2021000001, "Ali", "Veli"], ["2021000002", "Ayşe", "Yılmaz"]]),
                           "liste.xlsx")
    assert [(e.numara, e.ad, e.soyad) for e in entries] == [("2021000001", "Ali", "Veli"), ("2021000002", "Ayşe", "Yılmaz")]


def test_roster_header_tolerance_case_and_turkish():
    rows = [["Sınıf listesi"], [], ["SIRA", "ÖĞRENCİ NO", "ADI", "SOYADI"], [1, 2021000001.0, "Çağrı", "Işık"]]
    entries = parse_roster(xlsx(rows), "LISTE.XLSX")
    assert [(e.numara, e.ad, e.soyad) for e in entries] == [("2021000001", "Çağrı", "Işık")]


def test_roster_full_name_column():
    entries = parse_roster(xlsx([["No", "Adı Soyadı"], [2021000007, "Ahmet Şahin Çakır"]]), "a.xlsx")
    assert (entries[0].ad, entries[0].soyad) == ("Ahmet Şahin", "Çakır")


def test_roster_without_header():
    entries = parse_roster(xlsx([[2021000001, "Ali", "Veli"], [2021000002, "Can", "Er"]]), "a.xlsx")
    assert len(entries) == 2 and entries[1].soyad == "Er"


def test_roster_numbers_must_be_ten_digits_and_the_wrong_lines_are_named():
    rows = [["Sınıf listesi"], [], ["Numara", "Ad", "Soyad"],
            [2021000001, "Ali", "Veli"],
            [202100002, "Dokuz", "Hane"],          # line 5: 9 digits
            ["20210000033", "Onbir", "Hane"],      # line 6: 11 digits
            [],
            ["2021A00004", "Harf", "Var"],         # line 8: a letter
            ["2021000005", "Şule", "Öz"]]
    with pytest.raises(RosterError) as error:
        parse_roster(xlsx(rows), "liste.xlsx")
    message = str(error.value)
    assert "10 haneli" in message
    assert "5. satır “202100002”" in message and "6. satır “20210000033”" in message
    assert "8. satır “2021A00004”" in message and "2021000001" not in message

    # Many wrong lines: the first few are named, the rest counted.
    many = [["Numara", "Ad", "Soyad"]] + [[1000 + i, "A", "B"] for i in range(8)]
    with pytest.raises(RosterError) as error:
        parse_roster(xlsx(many), "liste.xlsx")
    assert "2. satır “1000”" in str(error.value) and "ve 3 satır daha" in str(error.value)

    # A list without a header row and with short numbers says what is wrong with the numbers.
    with pytest.raises(RosterError) as error:
        parse_roster(xlsx([[2021001, "Ali", "Veli"], [2021002, "Can", "Er"]]), "a.xlsx")
    assert "10 haneli" in str(error.value) and "1. satır “2021001”" in str(error.value)


def test_roster_csv_semicolon_and_cp1254():
    data = "Numara;Ad;Soyad\r\n2021000005;Şule;Öz\r\n".encode("cp1254")
    entries = parse_roster(data, "liste.csv")
    assert (entries[0].numara, entries[0].ad, entries[0].soyad) == ("2021000005", "Şule", "Öz")


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"not an excel file", "liste.xlsx"),
        (b"x", "liste.xls"),
        (b"x", "liste.pdf"),
        (xlsx([["foo", "bar"], ["a", "b"]]), "liste.xlsx"),
        (xlsx([["numara", "ad", "soyad"]]), "liste.xlsx"),
        (xlsx([["numara", "ad", "soyad"], ["20 21/1", "Ali", "Veli"]]), "liste.xlsx"),
    ],
)
def test_roster_errors_are_turkish_messages(data, name):
    with pytest.raises(RosterError) as error:
        parse_roster(data, name)
    assert str(error.value)
