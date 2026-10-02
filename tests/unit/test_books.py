"""Unit tests: every name a book arrives with maps to its published title and its compiler."""

import pytest

from app.services import books
from app.services.isnad_tree import book_author


@pytest.mark.parametrize(("name", "title"), [
    # English names of the CSV datasets (Hadith-Data-Sets, docs/DATA_SOURCES.md)
    ("Sahih Bukhari", "صحيح البخاري"), ("Sahih Muslim Without_Tashkel", "صحيح مسلم"),
    ("Sunan al Tirmidhi", "جامع الترمذي"), ("Sunan Ibn Maja", "سنن ابن ماجه"),
    ("Sunan Abu Dawud", "سنن أبي داود"), ("Sunan al-Nasai", "سنن النسائي"),
    ("Musnad Ahmad ibn Hanbal", "مسند الإمام أحمد بن حنبل"), ("Maliks Muwatta", "موطأ الإمام مالك"),
    ("Sunan al Darami", "سنن الدارمي"),
    # Arabic titles of the JSON datasets (hadith-json) and of earlier uploads
    ("صحيح البخاري", "صحيح البخاري"), ("موطأ مالك", "موطأ الإمام مالك"), ("مسند أحمد", "مسند الإمام أحمد بن حنبل"),
    ("سنن الترمذي", "جامع الترمذي"), ("مسند الدارمي", "سنن الدارمي"), ("سنن ابى داود", "سنن أبي داود"),
    # File names and references
    ("صحيح مسلم.json", "صحيح مسلم"), ("صحيح مسلم، 12", "صحيح مسلم"),
])
def test_every_name_gives_the_published_title(name, title):
    assert books.title(name) == title


@pytest.mark.parametrize("name", ["كتاب الصلاة.pdf", "رياض الصالحين", "", "مذكرة"])
def test_other_names_are_left_alone(name):
    assert books.title(name) == name
    assert books.find(name) is None


def test_nine_books_each_with_its_compiler():
    assert len(books.BOOKS) == 9
    assert len({b.title for b in books.BOOKS}) == 9
    darimi = books.find("سنن الدارمي")
    # The dataset swaps his names; he is ʿAbdullah son of ʿAbd al-Rahman.
    assert darimi.compiler == "الإمام أبو محمد عبد الله بن عبد الرحمن الدارمي"
    assert darimi.credit == "الإمام أبو محمد عبد الله بن عبد الرحمن الدارمي (ت 255هـ)"


@pytest.mark.parametrize(("book", "compiler"), [
    ("صحيح البخاري", "البخاري"), ("موطأ مالك", "مالك"), ("Musnad Ahmad ibn Hanbal", "أحمد بن حنبل"),
    ("سنن الدارمي", "الدارمي"), ("كتاب غير معروف", ""),
])
def test_chains_end_with_the_compiler(book, compiler):
    assert book_author(book) == compiler
