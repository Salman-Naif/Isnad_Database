# Data sources

What Isnad holds, where it comes from, under what terms, and how it is used and checked.

The texts are the words of the Prophet ﷺ and the narrations of the scholars who compiled them:
classical works, in the public domain. The datasets below are the work of the people who
digitised and published them — credit them wherever their data is used. The team decides
which editions are approved before uploading anything to the database; Isnad never adds a
hadith, a ruling or a source of its own.

## The nine books

Every text in the database belongs to one of these books. Whatever name a file arrives with
(the CSV's English name, the JSON's Arabic title, an older title), it is stored and shown under
the published title below (`app/services/books.py`), and every isnad tree ends with the compiler.

| Published title | Full title | Compiler | Died (AH) |
| --- | --- | --- | --- |
| صحيح البخاري | الجامع المسند الصحيح المختصر من أمور رسول الله ﷺ وسننه وأيامه | الإمام أبو عبد الله محمد بن إسماعيل البخاري | 256 |
| صحيح مسلم | المسند الصحيح المختصر بنقل العدل عن العدل إلى رسول الله ﷺ | الإمام أبو الحسين مسلم بن الحجاج القشيري النيسابوري | 261 |
| سنن أبي داود | السنن | الإمام أبو داود سليمان بن الأشعث السجستاني | 275 |
| جامع الترمذي | الجامع (سنن الترمذي) | الإمام أبو عيسى محمد بن عيسى الترمذي | 279 |
| سنن النسائي | المجتبى من السنن (السنن الصغرى) | الإمام أبو عبد الرحمن أحمد بن شعيب النسائي | 303 |
| سنن ابن ماجه | السنن | الإمام أبو عبد الله محمد بن يزيد القزويني ابن ماجه | 273 |
| موطأ الإمام مالك | الموطأ (رواية يحيى بن يحيى الليثي) | الإمام أبو عبد الله مالك بن أنس الأصبحي | 179 |
| مسند الإمام أحمد بن حنبل | المسند | الإمام أبو عبد الله أحمد بن محمد بن حنبل الشيباني | 241 |
| سنن الدارمي | المسند الجامع (مسند الدارمي) | الإمام أبو محمد عبد الله بن عبد الرحمن الدارمي | 255 |

Titles, compilers and dates follow the printed editions and the reference platforms the
challenge's reference pack names for hadith: [الدرر السنية](https://dorar.net/hadith) and
[المكتبة الشاملة](https://shamela.ws). Corrections made to the datasets:

- hadith-json names Sunan al-Darimi's compiler «عبد الرحمن بن عبد الله» — the names are swapped;
  he is أبو محمد عبد الله بن عبد الرحمن الدارمي.
- The same book had different titles depending on the file («مسند أحمد» from the CSV,
  «مسند الإمام أحمد بن حنبل» from the JSON; «موطأ مالك»): each now has one title. Texts uploaded
  before are shown under the published title without re-uploading them.
- The Muwatta in both datasets is Yahya ibn Yahya al-Laythi's transmission (its chains open
  «حدثني يحيى عن مالك»), the one printed as «الموطأ»; its isnad trees end with Malik.

On the live service (October 2026): the nine books, 40,818 hadiths.

## Hadith-Data-Sets — CSV

- **Repository:** https://github.com/abdelrahmaan/Hadith-Data-Sets
- **Files used:** https://github.com/abdelrahmaan/Hadith-Data-Sets/tree/master/All%20Hadith%20Books
- **License:** none stated (the repository has no license file; checked 2026-10-02).
- **Contents:** the nine books, each as `<Book>.csv` (with diacritics) and
  `<Book> Without_Tashkel.csv`; one hadith per row, the book's English name as the header.
- **Counts (as read by Isnad):** Sahih Bukhari 7,008 · Sahih Muslim 5,362 ·
  Sunan al Tirmidhi 3,891 · Sunan Ibn Maja 4,332 · Sunan Abu Dawud 4,590 · Sunan al-Nasai 5,662 ·
  Musnad Ahmad ibn Hanbal 26,363 · Maliks Muwatta 1,594 · Sunan al Darami 3,367.
- **Read by:** `app/services/hadith_import.py` (CSV), from the dashboard or
  `scripts/import_hadiths.py`. No rulings are included.

## hadith-json — JSON (sunnah.com)

- **Repository:** https://github.com/AhmedBaset/hadith-json
- **File used:** https://github.com/AhmedBaset/hadith-json/blob/main/db/by_book/the_9_books/muslim.json
  (the other books are in the same folder: `bukhari.json`, `tirmidhi.json`, `ibnmajah.json`, …)
- **License:** none stated (no license file; checked 2026-10-02). Its data was scraped from
  [sunnah.com](https://sunnah.com).
- **Contents:** one book per file — `metadata` (Arabic and English titles), `chapters`, and
  `hadiths` with the Arabic text and sunnah.com's English translation.
  Sahih Muslim: 7,459 hadiths (sunnah.com numbering).
- **Read by:** `app/services/hadith_import.py` (JSON). Only the **Arabic** text is stored; the
  English translations (sunnah.com's work) are not stored or shown. Each chapter's Arabic title
  becomes the hadith's topic.

A corrected edition with scholars' grades, in the same format:
[Hadith-JSON-Engine](https://github.com/TheAbubakrAbu/Hadith-JSON-Engine) (**MIT License**) —
its `english.grades` (e.g. Al-Albani: Sahih) become the ruling, in Arabic, and the scholar who
gave it.

## Rights, and what is published here

- The hadith texts are classical works in the public domain. The digitisation is its authors'
  work, and the two datasets publish no license: **their files are not redistributed** in this
  repository or the website's — the team downloads them from the links above and uploads them
  to its own database, and they are credited here, in the README and in the code that reads them.
- What visitors see is the Arabic text of a hadith with its book; no translation is shown.
- The tests quote a handful of short narrations (classical text) in the same formats.
- Before wider use, the team should ask the datasets' authors for permission, or move to
  sources the reference pack lists with published terms — e.g. the
  [موسوعة الأحاديث النبوية — HadeethEnc API](https://hadeethenc.com/api-docs) or the
  [Dorar hadith search API](https://dorar.net/article/389).

## How the data is used and checked

| Step | What happens | Where |
| --- | --- | --- |
| Approval | The team chooses the editions; nothing is uploaded without them | Dashboard, `scripts/import_hadiths.py` |
| Import | Arabic text only; the book under its published title; rulings only from the file | `app/services/hadith_import.py`, `app/services/books.py` |
| Rulings | Never guessed or generated: a text without a ruling is shown as «found», not «verified» | `app/services/hadith_import.py`; the website's verdicts |
| Isnad | Taken from the file when it has one; otherwise read from the narration's wording and marked «مستخرج آليًا» | `app/services/isnad_tree.py` |
| Search | Word-for-word quotes (literal index) and meaning (embeddings); every result carries its book | `app/services/text_index.py`, `app/api/routes/site_api.py` |
| Checking a result by hand | Search the text on [الدرر السنية](https://dorar.net/hadith) (rulings of the scholars with their sources) or in the printed book on [المكتبة الشاملة](https://shamela.ws) | — |

## Where the datasets are used in this repository

| Place | How |
| --- | --- |
| `app/services/hadith_import.py` | Reads both formats (links in the module's docstring) |
| `app/services/books.py` | The nine books' titles and compilers, and the corrections above |
| `scripts/import_hadiths.py` | Converts, measures the cost of, and indexes these files |
| `tests/unit/test_hadith_import.py`, `tests/integration/test_hadith_collections.py` | Small samples in the same formats |
| `app/services/isnad_tree.py`, `tests/unit/test_isnad_tree.py` | Chain reading checked on samples from the nine books; test narrations quoted from them |
| `README.md` → "Hadith collections as text" | How to upload them |

The full files are not stored in this repository; download them from the links above.
