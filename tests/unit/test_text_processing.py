"""Tests for Arabic cleaning and chunking."""

from app.services.text_processing import chunk, clean


def test_clean_removes_diacritics_tatweel_and_extra_space():
    raw = "إِنَّمَا   الأَعْمَالُ‏ بالنـــيات\r\n\n\n\nسطر آخر"
    assert clean(raw) == "إنما الأعمال بالنيات\n\nسطر آخر"


def test_clean_can_keep_diacritics():
    assert clean("الأَعْمَالُ", strip_diacritics=False) == "الأَعْمَالُ"


def test_short_paragraphs_stay_whole():
    hadith_a = "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى"
    hadith_b = "من حسن إسلام المرء تركه ما لا يعنيه من القول والعمل"
    assert chunk(f"{hadith_a}\n\n{hadith_b}") == [hadith_a, hadith_b]


def test_wrapped_lines_are_joined():
    assert chunk("سطر أول من فقرة\nيكمل هنا") == ["سطر أول من فقرة يكمل هنا"]


def test_long_paragraph_respects_max_and_overlaps():
    sentence = "هذه جملة عربية للاختبار تتكرر عدة مرات."
    paragraph = " ".join([sentence] * 30)
    chunks = chunk(paragraph, max_chars=200, overlap=40)

    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # consecutive chunks share some text
    assert any(w in chunks[1] for w in chunks[0].split()[-3:])


def test_unbroken_text_is_split_on_words():
    text = " ".join(["كلمة"] * 200)  # no punctuation at all
    chunks = chunk(text, max_chars=100, overlap=0)
    assert all(len(c) <= 100 for c in chunks)
    assert sum(c.count("كلمة") for c in chunks) == 200


def test_extraction_junk_is_dropped():
    assert chunk("12\n\nصفحة 13\n\n* * *\n\n— ٤٥ —") == []


def test_short_hadiths_are_kept():
    text = "الدين النصيحة\n\nاطلبوا العلم من المهد إلى اللحد\n\nمن حسن إسلام المرء تركه ما لا يعنيه"
    assert chunk(text) == [
        "الدين النصيحة",
        "اطلبوا العلم من المهد إلى اللحد",
        "من حسن إسلام المرء تركه ما لا يعنيه",
    ]


def test_garbled_passages_are_dropped():
    garbled = "دعا BE gall أن التعال بعد رسول الله وي أفضل من جعفر INKS sect enoncacnupicce غريب أنا دار الحكمة"
    good = "من حسن إسلام المرء تركه ما لا يعنيه"
    assert chunk(f"{garbled}\n\n{good}") == [good]


def test_clean_normalizes_presentation_forms():
    assert clean("ﻻ ﺇﻟﻪ ﺇﻻ ﺍﻟﻠﻪ") == "لا إله إلا الله"
