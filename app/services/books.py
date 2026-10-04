"""
The nine books of hadith Isnad holds, under their published titles, with their compilers.

Every name a book can arrive with — an English name in a CSV file, the Arabic title in
a JSON collection, a Shamela edition («صحيح البخاري - ط السلطانية»), a file name, a shorter or
older title — is mapped to one entry here, at
upload time and again when results are shown, so a book has one name everywhere (including
texts uploaded before this list existed).

Titles, compilers and dates of death (Hijri) follow the standard printed editions and the
reference platforms named in the challenge's reference pack (dorar.net, shamela.ws). Author
fields in uploaded files are not used: one gave Sunan al-Darimi's compiler as «عبد الرحمن بن
عبد الله» — he is Abu Muhammad ʿAbdullah ibn ʿAbd al-Rahman al-Darimi.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    title: str  # the title it is published and cited under
    full_title: str  # the compiler's own title for it, or the edition's
    compiler: str  # full name
    compiler_short: str  # how chains and citations name him
    died_ah: int
    aliases: tuple[str, ...] = ()

    @property
    def credit(self) -> str:
        return f"{self.compiler} (ت {self.died_ah}هـ)"


BOOKS = (
    Book("صحيح البخاري",
         "الجامع المسند الصحيح المختصر من أمور رسول الله ﷺ وسننه وأيامه",
         "الإمام أبو عبد الله محمد بن إسماعيل البخاري", "البخاري", 256,
         ("bukhari", "bokhari")),
    Book("صحيح مسلم",
         "المسند الصحيح المختصر بنقل العدل عن العدل إلى رسول الله ﷺ",
         "الإمام أبو الحسين مسلم بن الحجاج القشيري النيسابوري", "مسلم", 261,
         ("muslim",)),
    Book("سنن أبي داود", "السنن",
         "الإمام أبو داود سليمان بن الأشعث السجستاني", "أبو داود", 275,
         ("abu dawud", "abudawud", "abi dawud", "abu daud")),
    Book("جامع الترمذي", "الجامع (سنن الترمذي)",
         "الإمام أبو عيسى محمد بن عيسى الترمذي", "الترمذي", 279,
         ("tirmidhi", "tirmizi", "سنن الترمذي")),
    Book("سنن النسائي", "المجتبى من السنن (السنن الصغرى)",
         "الإمام أبو عبد الرحمن أحمد بن شعيب النسائي", "النسائي", 303,
         ("nasai", "nasa'i", "nisai", "المجتبى", "السنن الصغرى")),
    Book("سنن ابن ماجه", "السنن",
         "الإمام أبو عبد الله محمد بن يزيد القزويني ابن ماجه", "ابن ماجه", 273,
         ("ibn maja", "ibnmajah", "ibn majah")),
    Book("موطأ الإمام مالك", "الموطأ (رواية يحيى بن يحيى الليثي)",
         "الإمام أبو عبد الله مالك بن أنس الأصبحي", "مالك", 179,
         ("muwatta", "malik", "موطأ مالك", "الموطأ")),
    Book("مسند الإمام أحمد بن حنبل", "المسند",
         "الإمام أبو عبد الله أحمد بن محمد بن حنبل الشيباني", "أحمد بن حنبل", 241,
         ("ahmad", "ahmed", "musnad", "مسند أحمد")),
    Book("سنن الدارمي", "المسند الجامع (مسند الدارمي)",
         "الإمام أبو محمد عبد الله بن عبد الرحمن الدارمي", "الدارمي", 255,
         ("darami", "darimi", "مسند الدارمي")),
)

_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})


def _key(name: str) -> str:
    text = name.lower().translate(_LETTERS)
    text = re.sub(r"\.(json|csv|txt|pdf|docx?)$", "", text)
    return " ".join(re.sub(r"[-_.]+", " ", text).split())


_BY_KEY = {_key(name): book for book in BOOKS for name in (book.title, *book.aliases)}


def find(name: str) -> Book | None:
    """The book a name refers to: its title or an alias, a file name that contains an
    English one («Sahih Bukhari Without_Tashkel»), or an Arabic name that starts with one
    («صحيح البخاري، 1», «سنن الترمذي - ت بشار»). An Arabic name that only contains a title is
    another book: «ضعيف سنن الترمذي», «صحيح سنن النسائي» (al-Albani's), «مختصر صحيح مسلم»."""
    if not name:
        return None
    key = _key(name)
    if key in _BY_KEY:
        return _BY_KEY[key]
    # Longest names first, so «مسند الدارمي» is not taken for «المسند» (Ahmad).
    for alias in sorted(_BY_KEY, key=len, reverse=True):
        if (alias in key) if alias.isascii() else key.startswith(alias):
            return _BY_KEY[alias]
    return None


def title(name: str) -> str:
    """The published title of the book a name refers to, or the name unchanged."""
    book = find(name)
    return book.title if book else name
