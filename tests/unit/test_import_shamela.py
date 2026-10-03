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


def test_muslims_two_numbers_and_footnote_marks():
    pages = ["\r١٢٨ - (٧٤) حَدَّثَنَا <a href=\"inr://man-1\">قُتَيْبَةُ</a> عَنْ <a href=\"inr://man-2\">أَنَسٍ</a> (١) قَالَ: "
             "<hadeeth-1>«لَا يُؤْمِنُ أَحَدُكُمْ حَتَّى يُحِبَّ لِأَخِيهِ مَا يُحِبُّ لِنَفْسِهِ» (٢).<hadeeth>"]
    [record] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert record.id == "1681-128-74"
    assert "(" not in record.text and "٧٤" not in record.text
    assert record.text.startswith("حَدَّثَنَا قُتَيْبَةُ عَنْ أَنَسٍ قَالَ")


def test_the_editors_introduction_is_left_out(monkeypatch):
    monkeypatch.setattr(shamela, "MIN_BODY_RUN", 3)  # a real book's body runs far longer
    intro = ["\r١ - الجهدُ التوثيقيُّ الجديد للمسند ومقابلة الأصول\r٢ - ضبطُ النصِّ ضبطاً يقترب من التمام"]
    first = ["\r١ - حَدَّثَنَا <a href=\"inr://man-1\">الْحُمَيْدِيُّ</a> عَنْ <a href=\"inr://man-2\">سُفْيَانَ</a> "
             "<hadeeth-1>«نص»<hadeeth>"]
    found = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(intro + first + PAGES)]
    assert [r.id for r in found] == ["1681-1", "1681-20", "1681-408-409", "1681-410"]


def test_an_unknown_honorific_glyph_is_never_shown_raw():
    assert "﵋" not in shamela.plain("قال فلان ﵋ ثم")


def test_a_tahwil_in_parentheses_is_seen():
    """Muslim ط التركية and al-Tirmidhi ت بشار write «(ح)»: two chains must never be joined."""
    raw = ("حَدَّثَنَا <a href=\"inr://man-1\">أَبُو بَكْرٍ</a>، حَدَّثَنَا <a href=\"inr://man-2\">غُنْدَرٌ</a>، عَنْ "
           "<a href=\"inr://man-3\">شُعْبَةَ</a> (ح) وَحَدَّثَنَا <a href=\"inr://man-4\">مُحَمَّدٌ</a>، عَنْ "
           "<a href=\"inr://man-3\">شُعْبَةَ</a> <hadeeth-1>«نص»<hadeeth>")
    assert shamela.chain_of(raw) == []
    assert shamela.chain_of(raw.replace("(ح)", "،ح،")) == []
    # «حدثنا» and names with «ح» in them are not a tahwil
    assert shamela.chain_of("حَدَّثَنَا <a href=\"inr://man-5\">حَمَّادٌ</a> عَنْ <a href=\"inr://man-6\">حُمَيْدٍ</a> "
                            "<hadeeth-1>«نص»<hadeeth>") == ["حَمَّادٌ", "حُمَيْدٍ"]


def test_a_chain_without_marked_words_still_rises_to_the_prophet():
    pages = ["\r٥ - حَدَّثَنَا <a href=\"inr://man-1\">قُتَيْبَةُ</a> عَنْ <a href=\"inr://man-2\">أَبِي هُرَيْرَةَ</a>، "
             "عَنِ النَّبِيِّ ﷺ بِمِثْلِهِ."]
    [record] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert [n.name for n in record.sanad] == ["النبي ﷺ", "أَبِي هُرَيْرَةَ", "قُتَيْبَةُ"]


def test_al_tirmidhis_own_ruling_is_taken_from_his_words():
    book = shamela.Book(7895, "سنن الترمذي - ت بشار", None)
    pages = ["\r١ - حَدَّثَنَا <a href=\"inr://man-1\">قُتَيْبَةُ</a> عَنِ <a href=\"inr://man-2\">ابْنِ عُمَرَ</a> "
             "<hadeeth-1>«لاَ تُقْبَلُ صَلاَةٌ بِغَيْرِ طُهُورٍ»<hadeeth>. قَالَ أَبُو عِيسَى: هَذَا الْحَدِيثُ أَصَحُّ شَيْءٍ، "
             "وَهَذَا حَدِيثٌ حَسَنٌ صَحِيحٌ."]
    [record] = [shamela.to_record(h, book, "", "") for h in shamela.split_hadiths(pages)]
    assert (record.hukm, record.mohaddith) == ("حسن صحيح", "الترمذي")


def test_the_editors_grading_is_taken_from_its_footnote_and_nothing_else():
    book = shamela.Book(25794, "مسند أحمد - ط الرسالة", None)
    pages = ["\r٣٥١ - حَدَّثَنَا مُحَمَّدُ بْنُ جَعْفَرٍ، عَنْ أَبِي مُوسَى قَالَ: «نص» (١).\r"
             "٣٥٢ - حَدَّثَنَا حَجَّاجٌ، عَنْ ابْنِ عَبَّاسٍ: فَدَنَوْتُ (٢) مِنْهُ «نص آخر» (٣)."]
    feet = ["(١) إسناده صحيح على شرط مسلم، رجاله ثقات رجال الشيخين. وأخرجه مسلم (١٢٢٢)."
            "(٢) القائل: دنوتُ، هو ابن عباس.(٣) حسن، رجاله ثقات."]
    first, second = [shamela.to_record(h, book, "", "") for h in shamela.split_hadiths(pages, feet)]
    assert first.hukm == "إسناده صحيح على شرط مسلم"
    assert second.hukm == "حسن"  # the gloss «القائل: دنوت…» is not a grading
    assert first.mohaddith == "شعيب الأرنؤوط وآخرون (مسند أحمد ط الرسالة)"
    assert "رجاله" not in first.hukm and "أخرجه" not in first.hukm


def test_no_ruling_is_made_up():
    [record] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(PAGES[:1])]
    assert record.hukm == "" and record.mohaddith == ""
