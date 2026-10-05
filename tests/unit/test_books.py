"""Unit tests: every name a book arrives with maps to its published title and its compiler."""

import pytest

from app.services import books
from app.services.isnad_tree import book_author


@pytest.mark.parametrize(("name", "title"), [
    # English names that CSV collections use
    ("Sahih Bukhari", "صحيح البخاري"), ("Sahih Muslim Without_Tashkel", "صحيح مسلم"),
    ("Sunan al Tirmidhi", "جامع الترمذي"), ("Sunan Ibn Maja", "سنن ابن ماجه"),
    ("Sunan Abu Dawud", "سنن أبي داود"), ("Sunan al-Nasai", "سنن النسائي"),
    ("Musnad Ahmad ibn Hanbal", "مسند الإمام أحمد بن حنبل"), ("Maliks Muwatta", "موطأ الإمام مالك"),
    # Arabic titles of JSON collections and of earlier uploads
    ("صحيح البخاري", "صحيح البخاري"), ("موطأ مالك", "موطأ الإمام مالك"), ("مسند أحمد", "مسند الإمام أحمد بن حنبل"),
    ("سنن الترمذي", "جامع الترمذي"), ("سنن ابى داود", "سنن أبي داود"),
    # File names and references
    ("صحيح مسلم.json", "صحيح مسلم"), ("صحيح مسلم، 12", "صحيح مسلم"),
    # Shamela's book names: title, then the edition
    ("صحيح البخاري - ط السلطانية", "صحيح البخاري"), ("سنن الترمذي - ت بشار", "جامع الترمذي"),
    ("موطأ مالك - رواية يحيى - ت الأعظمي", "موطأ الإمام مالك"), ("مسند أحمد - ط الرسالة", "مسند الإمام أحمد بن حنبل"),
    ("سنن أبي داود - ت الأرنؤوط", "سنن أبي داود"),
])
def test_every_name_gives_the_published_title(name, title):
    assert books.title(name) == title


@pytest.mark.parametrize("name", [
    "كتاب الصلاة.pdf", "رياض الصالحين", "", "مذكرة",
    # Books that name one of the eight in their title, but are other books
    "ضعيف سنن الترمذي", "صحيح سنن النسائي", "مختصر صحيح مسلم للمنذري ت الألباني",
    "الجامع الصحيح للسنن والمسانيد", "بر الوالدين - البخاري - ت مكي",
])
def test_other_names_are_left_alone(name):
    assert books.title(name) == name
    assert books.find(name) is None


def test_eight_books_each_with_its_compiler():
    assert len(books.BOOKS) == 8
    assert len({b.title for b in books.BOOKS}) == 8
    tirmidhi = books.find("سنن الترمذي - ت بشار")
    assert tirmidhi.compiler == "الإمام أبو عيسى محمد بن عيسى الترمذي"
    assert tirmidhi.credit == "الإمام أبو عيسى محمد بن عيسى الترمذي (ت 279هـ)"


@pytest.mark.parametrize(("book", "compiler"), [
    ("صحيح البخاري", "البخاري"), ("موطأ مالك", "مالك"), ("Musnad Ahmad ibn Hanbal", "أحمد بن حنبل"),
    ("سنن الترمذي - ت بشار", "الترمذي"), ("كتاب غير معروف", ""),
])
def test_chains_end_with_the_compiler(book, compiler):
    assert book_author(book) == compiler


def test_books_rank_in_the_order_they_are_cited():
    ranks = [books.rank(name) for name in ("صحيح البخاري - ط السلطانية", "صحيح مسلم", "سنن ابن ماجه", "كتاب آخر")]
    assert ranks == sorted(ranks) and ranks[0] == 0 and ranks[-1] == len(books.BOOKS)
