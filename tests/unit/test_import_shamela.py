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


def test_what_is_no_hadith_is_left_out():
    """A volume's introduction repeating early numbers, a «……» placeholder, «(¬١)» marks, the
    printer's colophon and the copyist's line closing a book."""
    pages = [*PAGES,
             "\r٢٠ - نسخة المكتبة الظاهرية ورمزها [ظ ١١]، وما رواه عن أبيه.\r٤١١ - . . . . . . . .\r"
             "٤١٢ - حَدَّثَنَا <a href=\"inr://man-1\">مُوسَى</a> عَنْ <a href=\"inr://man-2\">نَافِعٍ</a> (¬١) "
             "<hadeeth-1>«اقْرَأْ عَلَيْهَا¬ السَّلَامَ»<hadeeth>",
             "\r٤١٣ - قَالَ: فَحَدَّثْتُ هَذَا الْحَدِيثَ عُرْوَةَ، فَقَالَ: صَدَقَ _________ مَالِكٌ.",
             "\r٤١٤ - حَدَّثَنَا مُوسَى عَنْ نَافِعٍ قَالَ: صَلَّى. _________ تم بحمد الله تعالى طبع الجزء الثامن",
             "\r٤١٥ - كَمُلَ كِتَابُ الصَّلَاةِ، والْحَمْدُ للهِ كَثِيراً"]
    records = [r for h in shamela.split_hadiths(pages) if (r := shamela.to_record(h, BOOK, "", ""))]
    found = shamela.unique_ids(shamela.narrations_only(records))
    assert [r.id for r in found] == ["1681-20", "1681-408-409", "1681-410", "1681-412", "1681-413", "1681-414"]
    assert "¬" not in found[3].text and "عَلَيْهَا السَّلَامَ" in found[3].text
    assert found[4].text.endswith("صَدَقَ مَالِكٌ.")  # a rule inside a narration: the narration goes on
    assert found[5].text.endswith("صَلَّى.")  # the printer's colophon after the rule is not the hadith's


def test_a_verse_reference_broken_across_pages_stays_in_its_hadith():
    pages = ["\r٤١٥ - حَدَّثَنَا مُوسَى عَنْ عَائِشَةَ قَالَتْ: فَقَرَأَ ﴿وَالدَّارَ الْآخِرَةَ﴾ [الأحزاب:",
             "٢٨ - ٢٩] الْآيَةَ كُلَّهَا. [", "٤١٦ - حَدَّثَنَا مُوسَى عَنْ نَافِعٍ"]
    first, second = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert (first.id, second.id) == ("1681-415", "1681-416")
    assert first.text.endswith("[الأحزاب: ٢٨ - ٢٩] الْآيَةَ كُلَّهَا.")


def test_numbers_with_a_slash_start_their_own_hadith():
    # The Muwatta ت الأعظمي («٤/ ١ - », «٢٢٣٧/ »), Muslim («(١٦٩٧/ ١٦٩٨)»), never a date
    pages = ["\r٣ - مَالِكٌ عَنْ نَافِعٍ أَنَّهُ قَالَ: صَلَّى.\n٤/ ١ - مَالِكٌ عَنْ زَيْدٍ أَنَّهُ قَالَ: صَامَ.",
             "\r٢٢٣٧/ مَالِكٌ عَنِ ابْنِ شِهَابٍ أَنَّهُ قَالَ: حَجَّ.\r٢٥ - (١٦٩٧/ ١٦٩٨) حَدَّثَنَا قُتَيْبَةُ قَالَ: نَعَمْ."
             "\r٤/ ٧/ ١٤١٢ هـ"]
    found = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert [r.id for r in found] == ["1681-3", "1681-4-1", "1681-2237", "1681-25-1697-1698"]
    assert found[0].text.endswith("صَلَّى.") and found[2].text.startswith("مَالِكٌ")
    assert "١٦٩٧" not in found[3].text and "١٤١٢" in found[3].text  # the date stays text, not a hadith


def test_footnotes_kept_in_a_pages_text_are_set_apart():
    body = "\r٣١١٧ - حَدَّثَنَا مُحَمَّدٌ قَالَ: فَأَدْرَكَتْ (١).\r\r= ومسلم (١١٧٨).\r(١) إسناده صحيح على شرط الشيخين."
    text, foot = shamela.notes_apart(body, "")
    assert text.endswith("فَأَدْرَكَتْ (١).") and foot.startswith("= ومسلم") and "إسناده صحيح" in foot
    assert shamela.notes_apart(body, "(١) حاشية") == (body, "(١) حاشية")  # the page has its own footnotes
    muslim = "قَالَ: فَأَرْسَلَهَا،\r\r(٩٢٧) فَقَالَ ابْنُ عَبَّاسٍ"  # Abd al-Baqi's number, not a footnote
    assert shamela.notes_apart(muslim, "") == (muslim, "")


def test_a_hadith_ends_where_a_volume_or_a_book_opens():
    pages = ["\r٥٦١ - حَدَّثَنَا مُوسَى عَنْ عُثْمَانَ قَالَ: حَتَّى تَوَفَّاهُ اللهُ.",
             "مسند الإمام أحمد بن حنبل (١٦٤ - ٢٤١ هـ) حقق هذا الجزء شعيب الأرنؤوط",
             "\r٥٦٢ - حَدَّثَنَا مُوسَى عَنْ نَافِعٍ قَالَ: صَلَّى.\r\n﷽\r"
             "<span data-type='title' id=toc-9>كِتَابُ الصِّيَامِ</span>\r٥٦٣ - حَدَّثَنَا مُوسَى قَالَ: صَامَ."]
    first, second, third = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages, volumes=[1])]
    assert first.text.endswith("حَتَّى تَوَفَّاهُ اللهُ.")  # the next volume's title page is left out
    assert second.text.endswith("صَلَّى.")  # and so is the basmala that opens the next book
    assert third.topic == "كِتَابُ الصِّيَامِ"


def test_the_number_of_an_addition_by_abdullah_is_not_text():
    pages = ["\r١١٠٢٠ - حَدَّثَنَا مُوسَى قَالَ: نَعَمْ. • ١١٠٢٠/ قَالَ عَبْدُ اللهِ: حَدَّثَنَاهُ أَبِي"]
    [record] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert "١١٠٢٠" not in record.text and "• قَالَ عَبْدُ اللهِ" in record.text


def test_a_spelled_basmala_ends_a_hadith_only_before_a_title():
    before_a_book = ("\r٢٠٢٤ - حَدَّثَنَا مُوسَى قَالَ: وَأَيْقَظَ أَهْلَهُ. <hadeeth>\n- بِسْمِ اللهِ الرَّحْمَنِ الرَّحِيمِ.\r"
                     "<span data-type='title' id=toc-3>بَابُ الِاعْتِكَافِ</span>")
    in_a_letter = "\r٧ - حَدَّثَنَا مُوسَى قَالَ: فَإِذَا فِيهِ:\rبِسْمِ اللهِ الرَّحْمَنِ الرَّحِيمِ\rمِنْ مُحَمَّدٍ إِلَى هِرَقْلَ"
    [first] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths([before_a_book])]
    [second] = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths([in_a_letter])]
    assert first.text.endswith("وَأَيْقَظَ أَهْلَهُ.")
    assert second.text.endswith("بِسْمِ اللهِ الرَّحْمَنِ الرَّحِيمِ مِنْ مُحَمَّدٍ إِلَى هِرَقْلَ")


def test_an_unmarked_title_ends_a_hadith_and_names_the_next_ones_chapter():
    # Ibn Majah writes «باب…» on a line of its own, al-Tirmidhi «(١٤) باب…»; «كتابَ الله» opening a
    # narration's last line is not a title
    pages = ["\r٣٧ - حَدَّثَنَا سُوَيْدٌ قَالَ: «فَلْيَتَبَوَّأْ مَقْعَدَهُ مِنَ النَّارِ»\n"
             "بَابُ مَنْ حَدَّثَ عَنْ رَسُولِ اللَّهِ ﷺ حَدِيثًا\n٣٨ - حَدَّثَنَا عَلِيٌّ قَالَ: تَعَاهَدُوا\n"
             "كِتَابَ اللهِ، وَتَغَنَّوْا بِهِ\n(١٤) بَابُ كَرَاهِيَةِ مَا يُسْتَنْجَى بِهِ\n٣٩ - حَدَّثَنَا هَنَّادٌ"]
    first, second, third = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert first.text.endswith("مِنَ النَّارِ»")
    assert second.topic.startswith("بَابُ مَنْ حَدَّثَ") and second.text.endswith("كِتَابَ اللهِ، وَتَغَنَّوْا بِهِ")
    assert third.topic == "بَابُ كَرَاهِيَةِ مَا يُسْتَنْجَى بِهِ"


def test_a_title_after_a_closed_hadith_keeps_its_chapter_text_out_of_the_hadith():
    # Bukhari: «باب…» after a hadith, then the chapter's own words before the next number; Musnad
    # Ahmad: «بابٌ من أبواب الجنة» continuing a sentence of the narration is not a title
    pages = ["\r٢٨ - حَدَّثَنَا قُتَيْبَةُ قَالَ: «وَمَنْ لَمْ تَعْرِفْ».\r <hadeeth>\n"
             "بَابُ كُفْرَانِ الْعَشِيرِ.\rفِيهِ عَنْ أَبِي سَعِيدٍ، عَنِ النَّبِيِّ ﷺ.\n"
             "٢٩ - حَدَّثَنَا مَالِكٌ قَالَ: " + '" لِكُلِّ أَهْلِ عَمَلٍ\nبَابٌ مِنْ أَبْوَابِ الْجَنَّةِ "']
    first, second = [shamela.to_record(h, BOOK, "", "") for h in shamela.split_hadiths(pages)]
    assert first.text.endswith("وَمَنْ لَمْ تَعْرِفْ».") and second.topic == "بَابُ كُفْرَانِ الْعَشِيرِ."
    assert second.text.endswith("بَابٌ مِنْ أَبْوَابِ الْجَنَّةِ \"")
