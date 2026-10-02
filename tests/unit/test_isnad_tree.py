"""Unit tests: reading chains of narration from a hadith's wording, and drawing them as a tree.

The narrations are quoted, some shortened, from the hadith-json and Hadith-Data-Sets datasets
(see docs/DATA_SOURCES.md).
"""

import pytest

from app.models.schemas import Narrator
from app.services import isnad_tree
from app.services.isnad_tree import extract_chains, tree_for, tree_from_sanad, tree_from_text

BUKHARI_1 = (
    "حدثنا الحميدي عبد الله بن الزبير، قال حدثنا سفيان، قال حدثنا يحيى بن سعيد الأنصاري، قال أخبرني "
    "محمد بن إبراهيم التيمي، أنه سمع علقمة بن وقاص الليثي، يقول سمعت عمر بن الخطاب رضى الله عنه على "
    "المنبر قال سمعت رسول الله صلى الله عليه وسلم يقول \" إنما الأعمال بالنيات \""
)
TIRMIDHI_1 = (
    "حدثنا قتيبة بن سعيد، حدثنا أبو عوانة، عن سماك بن حرب، ح وحدثنا هناد، حدثنا وكيع، عن إسرائيل، عن "
    "سماك، عن مصعب بن سعد، عن ابن عمر، عن النبي صلى الله عليه وسلم قال \" لا تقبل صلاة بغير طهور \""
)


def names(node: dict) -> list[str]:
    """Every path from the root to a leaf, as «a > b > c»."""
    if not node["children"]:
        return [node["name"]]
    return [f"{node['name']} > {rest}" for child in node["children"] for rest in names(child)]


def test_a_chain_is_read_in_order_and_stops_before_the_prophet():
    chains, reaches_prophet = extract_chains(BUKHARI_1)
    assert reaches_prophet
    assert chains == [[
        "الحميدي عبد الله بن الزبير", "سفيان", "يحيى بن سعيد الأنصاري", "محمد بن إبراهيم التيمي",
        "علقمة بن وقاص الليثي", "عمر بن الخطاب",
    ]]


def test_the_tree_runs_from_the_prophet_to_the_compiler():
    tree = tree_from_text(BUKHARI_1, "صحيح البخاري").as_dict()
    assert names(tree) == [
        "النبي ﷺ > عمر بن الخطاب > علقمة بن وقاص الليثي > محمد بن إبراهيم التيمي > "
        "يحيى بن سعيد الأنصاري > سفيان > الحميدي عبد الله بن الزبير > البخاري"
    ]


def test_a_tahwil_chain_branches_where_it_meets_the_main_one():
    tree = tree_from_text(TIRMIDHI_1, "جامع الترمذي").as_dict()
    assert sorted(names(tree)) == [
        "النبي ﷺ > ابن عمر > مصعب بن سعد > سماك > أبو عوانة > قتيبة بن سعيد > الترمذي",
        "النبي ﷺ > ابن عمر > مصعب بن سعد > سماك > إسرائيل > وكيع > هناد > الترمذي",
    ]


@pytest.mark.parametrize(("text", "chain"), [
    # The text has begun after «قال»: not a narrator.
    ("حدثنا محمد بن قدامة، قال حدثنا جرير، عن منصور، عن عمران بن حذيفة، قال كانت ميمونة تدان "
     "فقالت سمعت خليلي صلى الله عليه وسلم يقول",
     ["محمد بن قدامة", "جرير", "منصور", "عمران بن حذيفة"]),
    # A clarification belongs to the narrator before it; «عن أبيه» is his father.
    ("حدثنا عبد الله بن مسلمة، حدثنا عبد العزيز، - يعني ابن محمد - عن هشام بن عروة، عن أبيه، عن "
     "عائشة، أن النبي صلى الله عليه وسلم قال",
     ["عبد الله بن مسلمة", "عبد العزيز (ابن محمد)", "هشام بن عروة", "والد هشام بن عروة", "عائشة"]),
    # «وهو …» that is not a name is the story, not a clarification.
    ("حدثنا يحيى بن سعيد، عن علقمة بن وقاص، عن عمر بن الخطاب، وهو يخطب الناس فقال سمعت رسول الله "
     "صلى الله عليه وسلم",
     ["يحيى بن سعيد", "علقمة بن وقاص", "عمر بن الخطاب"]),
    # Narrators who heard it together; a kunya followed by the name of the same man.
    ("حدثني أبو خيثمة، زهير بن حرب حدثنا وكيع، حدثنا عمرو الناقد، وحسن الحلواني، عن نافع، عن ابن "
     "عمر، عن النبي صلى الله عليه وسلم",
     ["أبو خيثمة زهير بن حرب", "وكيع", "عمرو الناقد وحسن الحلواني", "نافع", "ابن عمر"]),
    # A client named with his patron; a narrator whose name begins with و.
    ("حدثنا وكيع، عن موسى بن عقبة، عن كريب مولى ابن عباس، عن أسامة بن زيد، أن رسول الله صلى الله "
     "عليه وسلم",
     ["وكيع", "موسى بن عقبة", "كريب مولى ابن عباس", "أسامة بن زيد"]),
    # The story starts before the Prophet ﷺ is named.
    ("حدثنا مسدد، حدثنا أبو الأحوص، عن أنس، قال بينما نحن جلوس مع رسول الله صلى الله عليه وسلم",
     ["مسدد", "أبو الأحوص", "أنس"]),
])
def test_names_are_told_from_the_text(text, chain):
    assert extract_chains(text)[0] == [chain]


def test_a_saying_without_the_prophet_is_rooted_at_its_earliest_narrator():
    tree = tree_from_text("حدثني يحيى، عن مالك، عن نافع، أن عبد الله بن عمر كان يقول لا يصوم أحد", "موطأ مالك")
    assert names(tree.as_dict()) == ["عبد الله بن عمر > نافع > مالك > يحيى"]  # Malik is not added again


@pytest.mark.parametrize("text", ["إنما الأعمال بالنيات", "قال عمر الصلاة الصلاة", "", "حدثنا مسدد"])
def test_no_tree_without_a_chain(text):
    assert tree_from_text(text) is None


def test_a_structured_sanad_is_used_as_given():
    sanad = [Narrator(name="النبي ﷺ", grade="المصدر"), Narrator(name="أبو هريرة", grade="صحابي")]
    tree, extracted = tree_for(BUKHARI_1, sanad, "صحيح مسلم")
    assert not extracted
    assert names(tree.as_dict()) == ["النبي ﷺ > أبو هريرة > مسلم"]
    assert tree.children[0].grade == "صحابي"


def test_the_compiler_is_not_added_twice():
    sanad = [Narrator(name="عمر بن الخطاب"), Narrator(name="الإمام البخاري")]
    assert names(tree_from_sanad(sanad, "صحيح البخاري").as_dict()) == ["عمر بن الخطاب > الإمام البخاري"]


def test_the_wording_is_read_when_no_sanad_was_uploaded():
    tree, extracted = tree_for(TIRMIDHI_1, [], "جامع الترمذي، 1")
    assert extracted and tree.name == isnad_tree.PROPHET
    assert tree_for("نص بلا سند", [], "") == (None, False)


@pytest.mark.parametrize(("a", "b", "same"), [
    ("الليث", "ليث", True), ("أبي هريرة", "ابي هريره", True), ("سماك", "سماك بن حرب", False),
])
def test_same_narrator(a, b, same):
    assert isnad_tree.same_narrator(a, b) is same


def test_book_author():
    assert isnad_tree.book_author("سنن أبي داود") == "أبو داود"
    assert isnad_tree.book_author("كتاب غير معروف") == ""


# Sunan Ibn Majah #4227 as Hadith-Data-Sets writes it: «ح و حدثنا», with a space.
IBN_MAJAH_4227 = (
    "حدثنا أبو بكر بن أبي شيبة حدثنا يزيد بن هارون ح و حدثنا محمد بن رمح أنبأنا الليث بن سعد قالا "
    "أنبأنا يحيى بن سعيد أن محمد بن إبراهيم التيمي أخبره أنه سمع علقمة بن وقاص أنه سمع عمر بن الخطاب "
    "وهو يخطب الناس فقال سمعت رسول الله صلى الله عليه وسلم يقول إنما الأعمال بالنيات"
)


def test_tahwil_with_a_space_after_the_waw_still_starts_another_chain():
    chains, _ = extract_chains(IBN_MAJAH_4227)
    assert [c[0] for c in chains] == ["أبو بكر بن أبي شيبة", "محمد بن رمح"]
    tree = tree_from_text(IBN_MAJAH_4227, "سنن ابن ماجه").as_dict()
    # The two chains join at Yahya ibn Sa'id; Yazid ibn Harun never narrates from Ibn Rumh.
    assert names(tree) == [
        "النبي ﷺ > عمر بن الخطاب > علقمة بن وقاص > محمد بن إبراهيم التيمي > يحيى بن سعيد > الليث بن سعد > محمد بن رمح > ابن ماجه",
        "النبي ﷺ > عمر بن الخطاب > علقمة بن وقاص > محمد بن إبراهيم التيمي > يحيى بن سعيد > يزيد بن هارون > أبو بكر بن أبي شيبة > ابن ماجه",
    ]


def test_wahuwa_after_a_name_is_the_story_not_a_second_narrator():
    chains, _ = extract_chains(IBN_MAJAH_4227)
    assert chains[-1][-1] == "عمر بن الخطاب"
