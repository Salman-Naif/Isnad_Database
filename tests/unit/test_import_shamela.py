"""Unit tests: reading hadiths from Shamela's page markup (scripts/import_shamela.py).

The pages are short samples in the markup of Shamela's «صحيح البخاري - ط السلطانية» — the
numbers, narrator links, matn and title tags as the program stores them.
"""

import scripts.import_shamela as shamela

PAGES = [
    "<span data-type='title' id=toc-18>بَابُ قَوْلِ النَّبِيِّ ﷺ أَنَا أَعْلَمُكُمْ بِاللهِ</span>\r"
    "٢٠ - حَدَّثَنَا <a href=\"inr://man-5638\">مُحَمَّدُ بْنُ سَلَامٍ </a>قَالَ: أَخْبَرَنَا "
    "<a href=\"inr://man-4092\">عَبْدَةُ، </a>عَنْ <a href=\"inr://man-6702\">هِشَامٍ، </a>عَنْ "
    "<a href=\"inr://man-4361\">أَبِيهِ، </a>عَنْ <a href=\"inr://man-3026\">عَائِشَةَ ﵂</a> قَالَتْ: "
    "<hadeeth-20>«كَانَ رَسُولُ اللهِ ﷺ إِذَا أَمَرَهُمْ أَمَرَهُمْ مِنَ الْأَعْمَالِ بِمَا يُطِيقُونَ».<hadeeth>",
    "⦗١٤⦘\r٤٠٨ - ٤٠٩ - حَدَّثَنَا <a href=\"inr://man-1\">مُوسَى </a>عَنْ <a href=\"inr://man-2\">حُمَيْدٍ</a>: "
    "أَنَّ <a href=\"inr://man-3\">أَبَا هُرَيْرَةَ </a><a href=\"inr://man-4\">وَأَبَا سَعِيدٍ </a>حَدَّثَاهُ: "
    "<hadeeth-1>«أَنَّ رَسُولَ اللهِ ﷺ رَأَى نُخَامَةً فِي جِدَارِ الْمَسْجِدِ فَحَكَّهَا».<hadeeth>\r"
    "<span data-type='title' id=toc-19>بَابٌ</span>\r"
    "٤١٠ - قَالَ مَالِكٌ: أَخْبَرَنِي زَيْدٌ أَنَّ رَسُولَ اللهِ ﷺ قَالَ: إِذَا أَسْلَمَ الْعَبْدُ، ٤١١ - وَقَالَ: فَحَسُنَ إِسْلَامُهُ",
]
BOOK = shamela.Book(1681, "صحيح البخاري - ط السلطانية", None)


def records():
    return [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(PAGES)]


def test_each_numbered_hadith_becomes_a_record_under_its_published_title():
    found = records()
    assert [r.id for r in found] == ["1681-20", "1681-408-409", "1681-410"]
    assert {r.source for r in found} == {"صحيح البخاري"}


def test_the_chain_is_taken_from_the_narrator_links_prophet_first():
    first = records()[0]
    assert [n.name for n in first.sanad] == [
        "النبي ﷺ", "عَائِشَةَ رضي الله عنها", "والد هِشَامٍ", "هِشَامٍ", "عَبْدَةُ", "مُحَمَّدُ بْنُ سَلَامٍ"]


def test_narrators_who_heard_it_together_are_one_link():
    second = records()[1]
    assert [n.name for n in second.sanad][1] == "أَبَا هُرَيْرَةَ وأَبَا سَعِيدٍ"


def test_the_matn_and_the_chapter_are_the_editions_own():
    first, second, third = records()
    assert first.matn.startswith("كَانَ رَسُولُ اللهِ ﷺ إِذَا أَمَرَهُمْ")
    assert first.topic.startswith("بَابُ قَوْلِ النَّبِيِّ")
    assert second.topic == first.topic  # an unnamed «بابٌ» keeps the chapter before it
    assert third.matn == "" and third.sanad == []  # no links, no marked matn: the database reads it


def test_the_text_is_clean_for_search():
    first, second, third = records()
    for record in (first, second, third):
        assert "<" not in record.text and "⦗" not in record.text and "﵂" not in record.text
    assert "رضي الله عنها" in first.text
    assert "٤١١" not in third.text  # a number inside the narration is not part of its words


def test_a_tahwil_chain_is_left_to_the_database():
    raw = ("حَدَّثَنَا <a href=\"inr://man-1\">قُتَيْبَةُ</a>، عَنْ <a href=\"inr://man-2\">اللَّيْثِ</a> ح "
           "وَحَدَّثَنَا <a href=\"inr://man-3\">ابْنُ رُمْحٍ</a>، عَنْ <a href=\"inr://man-2\">اللَّيْثِ</a> <hadeeth-1>«نص»<hadeeth>")
    assert shamela.chain_of(raw) == []


def test_a_number_printed_twice_keeps_both_hadiths():
    twice = [*PAGES, '\r٢٠ - حَدَّثَنَا <a href="inr://man-9">فُلَانٌ</a> <hadeeth-2>«نص آخر»<hadeeth>']
    found = shamela.unique_ids([shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(twice)])
    assert [r.id for r in found].count("1681-20") == 1 and "1681-20-b" in [r.id for r in found]
