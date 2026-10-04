"""Unit tests: reading hadith collections in each published JSON and CSV format.

The samples follow the formats the importer reads: a JSON collection per book (with or without
scholars' grades), and CSV with one hadith per row (a column headed by the book's name, or
number and text).
"""

import json

import pytest

from app.services.extraction import ExtractionError
from app.services.hadith_import import read_collection, to_isnad_json

H1 = "حَدَّثَنَا الْحُمَيْدِيُّ قَالَ إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ"
H2 = "حدثنا قتيبة قال الدين النصيحة"


def as_json(data) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


# --- JSON ---


def test_isnad_format_is_read_as_is():
    data = as_json([{"id": "1", "text": H2, "hukm": "صحيح", "mohaddith": "مسلم",
                     "sanad": [{"name": "تميم الداري", "grade": "صحابي"}], "topic": "النصيحة", "source": "صحيح مسلم"}])
    [record] = read_collection(data, "my.json").records
    assert record.hukm == "صحيح" and record.sanad[0].name == "تميم الداري" and record.source == "صحيح مسلم"


SUNNAH_BOOK = {
    "id": 1,
    "metadata": {"id": 1, "length": 3, "arabic": {"title": "صحيح البخاري", "author": "البخاري"},
                 "english": {"title": "Sahih al-Bukhari"}},
    "chapters": [{"id": 1, "bookId": 1, "arabic": "كتاب بدء الوحى", "english": "Revelation"}],
    "hadiths": [
        {"id": 1, "idInBook": 1, "chapterId": 1, "bookId": 1, "arabic": H1,
         "english": {"narrator": "Narrated Umar", "text": "Actions are by intentions"}},
        {"id": 2, "idInBook": 2, "chapterId": 1, "bookId": 1, "arabic": "",
         "english": {"narrator": "", "text": "English only"}},
    ],
}


def test_sunnah_json_book():
    collection = read_collection(as_json(SUNNAH_BOOK), "bukhari.json")
    [record] = collection.records
    assert collection.title == "صحيح البخاري" and collection.skipped == 1
    assert record.id == "1" and record.text == H1
    assert record.topic == "كتاب بدء الوحى"
    assert record.source == "صحيح البخاري"
    assert record.hukm == "" and record.mohaddith == ""  # no ruling in the file → none invented


def test_engine_grades_become_the_ruling():
    book = {"metadata": {"arabic": {"title": "سنن ابن ماجه"}}, "chapters": [], "hadiths": [
        {"idInBook": 7, "arabic": {"text": H2}, "english": {"grades": [
            {"name": "Zubair Ali Zai", "grade": "Hasan"}, {"name": "Al-Albani", "grade": "Hasan Sahih"}]}},
        {"idInBook": 8, "arabic": H2 + " أيضا", "english": {"grades": [{"name": "Al-Albani", "grade": "Da'if Jiddan"}]}},
        {"idInBook": 9, "arabic": H2 + " كذلك", "english": {"grades": [{"name": "", "grade": "Something Else"}]}},
    ]}
    collection = read_collection(as_json(book), "ibnmajah.json")
    first, second, third = collection.records
    assert (first.hukm, first.mohaddith) == ("حسن صحيح", "الألباني")  # Al-Albani preferred
    assert (second.hukm, second.mohaddith) == ("ضعيف جدًا", "الألباني")
    assert (third.hukm, third.mohaddith) == ("Something Else", "")  # unknown grade kept as written
    assert collection.graded == 3


def test_by_chapter_file_uses_its_chapter_as_topic():
    data = {"metadata": {}, "chapter": {"id": 4, "arabic": "كتاب الإيمان"},
            "hadiths": [{"idInBook": 10, "chapterId": 4, "arabic": H2}]}
    assert read_collection(as_json(data), "2.json").records[0].topic == "كتاب الإيمان"


def test_team_ruling_fills_only_hadiths_without_one():
    book = {"hadiths": [{"idInBook": 1, "arabic": H2},
                        {"idInBook": 2, "arabic": H1, "english": {"grades": [{"name": "Al-Albani", "grade": "Sahih"}]}}]}
    first, second = read_collection(as_json(book), "b.json", source="صحيح مسلم",
                                    default_hukm="صحيح", default_mohaddith="مسلم").records
    assert (first.hukm, first.mohaddith, first.source) == ("صحيح", "مسلم", "صحيح مسلم")
    assert (second.hukm, second.mohaddith) == ("صحيح", "الألباني")


@pytest.mark.parametrize(("data", "message"), [
    (b"{not json", "غير صالح"),
    (as_json({"books": []}), "غير معروفة"),
    (as_json([{"id": "1"}]), "بنية"),
    (as_json([]), "لا يحتوي"),
    (as_json({"hadiths": [{"idInBook": 1, "arabic": H1}, {"idInBook": 1, "arabic": H2}]}), "مكررة"),
])
def test_bad_json_is_explained(data, message):
    with pytest.raises(ExtractionError, match=message):
        read_collection(data, "x.json")


# --- CSV ---


def test_csv_with_the_book_name_as_header():
    # a CSV collection: one column headed by the book's name
    data = f"Sunan Ibn Maja\n{H1}\n\"{H2}, في سطر فيه فاصلة\"\n".encode()
    collection = read_collection(data, "Sunan Ibn Maja.csv", source="سنن ابن ماجه")
    assert collection.title == "Sunan Ibn Maja"
    assert [r.id for r in collection.records] == ["1", "2"]
    assert collection.records[1].text == f"{H2}, في سطر فيه فاصلة"
    assert collection.records[0].source == "سنن ابن ماجه"


def test_csv_of_numbers_and_texts_without_header():
    # numbers and texts, with invisible direction marks in the text
    data = f'"1"," ‏{H1} "\n"2"," {H2} "\n"5","{H2} مرة أخرى"\n'.encode()
    records = read_collection(data, "ibn-maja.csv").records
    assert [r.id for r in records] == ["1", "2", "5"]
    assert records[0].text == H1  # marks and extra spaces removed, diacritics kept
    assert records[0].source == "سنن ابن ماجه"  # the file's name, as the Arabic title


def test_csv_with_named_columns_and_semicolons():
    data = f"رقم;الحديث;الدرجة\n1;{H1};صح\n2;{H2};صح\n".encode()
    records = read_collection(data, "book.csv").records
    assert [r.id for r in records] == ["1", "2"] and records[1].text == H2


def test_csv_in_windows_arabic_encoding():
    data = f"1,{H2}\n2,{H2} ثانية\n".encode("cp1256")
    assert len(read_collection(data, "old.csv").records) == 2


def test_csv_rows_without_arabic_are_skipped():
    collection = read_collection(f"1,{H2}\n2,\n3,English only\n".encode(), "x.csv")
    assert len(collection.records) == 1 and collection.skipped == 2


def test_unsupported_extension():
    with pytest.raises(ExtractionError):
        read_collection(b"x", "book.xlsx")


def test_conversion_to_isnad_json_round_trips():
    collection = read_collection(as_json(SUNNAH_BOOK), "bukhari.json")
    again = read_collection(to_isnad_json(collection), "converted.json")
    assert again.records == collection.records


# --- Matn and titles ---

from app.services.hadith_import import arabic_title, matn_of  # noqa: E402


@pytest.mark.parametrize(("text", "matn"), [
    ("حدثنا قتيبة عن مالك عن نافع عن تميم أن رسول الله صلى الله عليه وسلم قال: «الدين النصيحة لله ولكتابه ولرسوله ولأئمة المسلمين وعامتهم»",
     "الدين النصيحة لله ولكتابه ولرسوله ولأئمة المسلمين وعامتهم"),
    ("حَدَّثَنَا الْحُمَيْدِيُّ قَالَ سَمِعْتُ رَسُولَ اللَّهِ صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ يَقُولُ إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ وإنما لكل امرئ ما نوى",
     "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى"),
    ("عن أنس عن النبي ﷺ قال لا يؤمن أحدكم حتى يحب لأخيه ما يحب لنفسه", "لا يؤمن أحدكم حتى يحب لأخيه ما يحب لنفسه"),
])
def test_matn_is_the_text_after_the_prophet_is_named(text, matn):
    assert matn_of(text) == matn


@pytest.mark.parametrize("text", [
    "حدثنا مالك عن نافع عن ابن عمر أنه كان يقول لا يصلي أحد عن أحد",  # a companion's saying
    "عن أنس عن النبي صلى الله عليه وسلم قال نعم",  # too short to stand alone
    "عن أنس عن النبي صلى الله عليه وسلم قال لا ضرر ولا ضرار",  # short: found by the literal index
])
def test_no_matn_when_it_cannot_be_told_apart(text):
    assert matn_of(text) == ""


@pytest.mark.parametrize(("name", "title"), [
    ("Sahih Bukhari", "صحيح البخاري"), ("Sahih Muslime Without_Tashkel", "صحيح مسلم"),
    ("Sunan al Tirmidhi", "جامع الترمذي"), ("Sunan Ibn Maja", "سنن ابن ماجه"), ("ibnmajah", "سنن ابن ماجه"),
    ("كتاب آخر", "كتاب آخر"),
])
def test_file_names_become_arabic_titles(name, title):
    assert arabic_title(name) == title


@pytest.mark.parametrize(("text", "start"), [
    ("حدثنا قتيبة عن عائشة أنها سألت النبي صلى الله عليه وسلم فقالت يا رسول الله أنعتمر بعد الحج قال نعم والعمرة كفارة",
     "يا رسول الله"),
    ("حدثنا ابن عياش أن وفد الجن قدموا على النبي صلى الله عليه وسلم فقالوا يا محمد انه أمتك أن يستنجوا بعظم أو روثة",
     "يا محمد"),
])
def test_the_matn_starts_at_a_whole_word(text, start):
    assert matn_of(text).startswith(start)
