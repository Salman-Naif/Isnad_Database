"""Unit tests: a short query names a subject, matched in the hadith's own words."""

import pytest

from app.services.text_index import is_subject, subject_overlap

pytestmark = pytest.mark.unit

CHAIN_ONLY = ("عن عائشة أم المؤمنين رضي الله عنها قالت قال رسول الله صلى الله عليه وسلم "
              "فضل عائشة على النساء كفضل الثريد على سائر الطعام")


def test_a_few_words_are_a_subject_a_sentence_is_not():
    assert is_subject("فضل الأم")
    assert not is_subject("إنما الأعمال بالنيات وإنما لكل امرئ ما نوى")
    assert not is_subject("  ")


@pytest.mark.parametrize("text", [
    "قال رسول الله ﷺ أمك ثم أمك ثم أمك",
    "قال النبي ﷺ الجنة تحت أقدام الأمهات",
    "قال ﷺ أحية أمك قال نعم",
])
def test_the_subject_is_found_in_its_forms(text):
    assert subject_overlap("فضل الأم", text) == 1.0


def test_a_mother_of_the_believers_or_a_chain_is_not_the_subject():
    assert subject_overlap("فضل الأم", CHAIN_ONLY) == 0.0
    assert subject_overlap("فضل الأم", "قال ﷺ لا تجتمع هذه الأمة على ضلالة") == 0.0  # أمة, not أم


def test_framing_words_alone_match_nothing():
    assert subject_overlap("فضل", CHAIN_ONLY) == 0.0


SAID = "قال رسول الله صلى الله عليه وسلم "


@pytest.mark.parametrize(("query", "text"), [
    ("بر الوالدين", SAID + "رغم أنف من أدرك والديه عند الكبر"),
    ("ما حكم ترك الصلاة", SAID + "بين الرجل وبين الشرك والكفر ترك الصلاة"),
    ("فضل الصلاة", SAID + "كذلك مثل الصلوات الخمس يمحو الله بهن الخطايا"),
    ("فضل الصدقة", SAID + "ما نقصت صدقة من مال"),
    ("حق الجار", SAID + "ما زال جبريل يوصيني بالجار حتى ظننت أنه سيورثه"),
    ("فضل العلم", SAID + "من سلك طريقا يلتمس فيه علما سهل الله له به طريقا إلى الجنة"),
    ("الغيبة", SAID + "أتدرون ما الغيبة قال ذكرك أخاك بما يكره"),
])
def test_common_subjects_are_found_in_the_hadiths_about_them(query, text):
    assert subject_overlap(query, text) > 0
