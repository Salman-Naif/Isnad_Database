# Data sources

What Isnad holds, where it comes from, under what terms, and how it is used and checked.

The texts are the words of the Prophet ﷺ and the narrations of the scholars who compiled them:
classical works, in the public domain. They are taken from the printed editions in
**المكتبة الشاملة**, and checked against **الدرر السنية** — the two reference platforms the
challenge's reference pack names for the books of the Sunnah. The team decides which editions
are approved before anything is uploaded; Isnad never adds a hadith, a ruling or a source of
its own.

## The eight books

Every text in the database belongs to one of these books, stored and shown under its published
title with its compiler (`app/services/books.py`); every isnad tree ends with the compiler.

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

Titles, compilers and dates follow the printed editions, as Shamela and al-Dorar al-Saniyya give
them.

## المكتبة الشاملة — the source of the texts

- **What:** [المكتبة الشاملة](https://shamela.ws), desktop edition, installed by the team.
- **Read by:** `scripts/import_shamela.py` (see the README). Each record keeps the edition's
  hadith number in its id (`1681-20`), its chapter, its chain as Shamela links its narrators to
  its narrators database (where the edition links them), its matn (where the edition marks it),
  and the ruling the edition records (below).
- **Editions** (one per book; converted 2026-10-04):

  | Book | Shamela edition (book id) | Hadiths | Chain from the edition's links | Rulings |
  | --- | --- | --- | --- | --- |
  | صحيح البخاري | ط السلطانية (1681) | 7,329 | 7,130 | — |
  | صحيح مسلم | ط التركية (711) | 7,621 | 6,427 | — |
  | سنن أبي داود | ت محمد محيي الدين عبد الحميد (1726) | 5,284 | read from the wording | 5,173 — الألباني |
  | جامع الترمذي | ت بشار عواد معروف (7895) | 3,947 | 3,870 | 2,692 — الترمذي |
  | سنن النسائي | ط المصرية (829) | 5,764 | 5,611 | — |
  | سنن ابن ماجه | ت محمد فؤاد عبد الباقي (1198) | 4,343 | read from the wording | 4,298 — الألباني |
  | موطأ الإمام مالك | رواية يحيى، ت محمد مصطفى الأعظمي (28107) | 2,891 | 2,448 | — |
  | مسند الإمام أحمد بن حنبل | ط الرسالة (25794) | 26,636 | read from the wording | 25,288 — شعيب الأرنؤوط وآخرون |
  | **All eight** | | **63,815** | **25,486** | **37,451** |

  A narration with several chains («ح») is left to the database, which reads all its chains from
  the wording and branches the tree where they meet. Each edition's own numbering is kept: the
  Muwatta ت الأعظمي prints two numbers on many paragraphs («٤/ ١ -»), Muslim
  «١٢٨ - (٧٤)» (the running number, then Abd al-Baqi's), and Musnad Ahmad numbers the parts of a
  long hadith «٨٥٧١/ ١ -». What is not a hadith is left out: the editors' introductions (the
  import starts at the book's own numbering; for Muslim this leaves out the 9 entries of his
  preface), each volume's title page and the introduction Musnad Ahmad ط الرسالة repeats at its
  head, the basmala before each book, the printer's closing note after each volume of Muslim
  ط التركية, the copyist's «كمل كتاب…» lines of the Muwatta, and the places an edition leaves
  empty («……»). Embedding all eight: about 12.3 M tokens ≈ $0.25
  (`scripts/import_hadiths.py --estimate`).
- **Taken:** the hadith texts, the narrator links, the chapter titles, and the ruling recorded
  for each hadith (also where a page keeps its footnotes inside its text, as a few pages of
  Musnad Ahmad do). **Not taken:** the editions' introductions and footnotes — their notes,
  variant readings and takhrij — beyond the ruling phrase.

## Rulings — only as the sources record them

A ruling is shown with the scholar who gave it, exactly as the edition records it. Isnad never
grades a hadith; a text without a recorded ruling is shown as «found in the sources», not as
«verified».

| Book | Ruling | Taken from |
| --- | --- | --- |
| جامع الترمذي | الإمام الترمذي's own words on each hadith («هذا حديث حسن صحيح») | the text of the hadith itself |
| سنن أبي داود، سنن ابن ماجه | الشيخ محمد ناصر الدين الألباني | the edition's «[حكم الألباني]» notes in Shamela |
| مسند الإمام أحمد | الشيخ شعيب الأرنؤوط ومن معه من محققي ط الرسالة | the grading phrase opening each hadith's footnote («إسناده صحيح على شرط الشيخين») — the phrase only |
| صحيح البخاري، صحيح مسلم، سنن النسائي، الموطأ | none recorded in these editions | — |

## الدرر السنية — the reference for checking

[الدرر السنية](https://dorar.net/hadith) (مؤسسة الدرر السنية) holds the rulings of the scholars on
some 300,000 hadiths with their sources. Isnad does not copy from it; it is where a result is
checked by hand, and where the chat assistant refers a visitor when the books Isnad holds don't
answer a question («الدرر السنية (dorar.net)»).

## Rights, and what is published here

- The hadith texts and al-Tirmidhi's words are classical works in the public domain.
- The editions' own work — verification, numbering, notes — belongs to their editors and
  publishers. Shamela's [terms](https://shamela.ws/page/terms) (checked 2026-10-03) say that rights
  in books and editions stay with their holders and grant no right to reuse content beyond the
  law or the holder's permission. Accordingly:
  - the converted files are **never published** in this repository (`data/structured/` is not
    committed) — only the code that converts them;
  - every result names its book, and every ruling the scholar or the editors who gave it; the
    editions are credited here;
  - of the editors' notes, only the short ruling phrase is kept, attributed to them;
  - **before the texts and rulings are served publicly beyond the challenge, the team should ask
    Shamela and the publishers (مؤسسة الرسالة for Musnad Ahmad) for permission.**
- What visitors see is the Arabic text of a hadith, its book, its chain and its ruling with its
  author; no translation is shown.
- The tests quote a handful of short narrations (classical text) in the editions' markup. The
  website's verification cases and their report (Isnad_Website `docs/evaluation/verification*`)
  quote the first ten words of 64 hadiths and the opening words of each first result, without
  the editions' diacritics.

## How the data is used and checked

| Step | What happens | Where |
| --- | --- | --- |
| Approval | The team chooses the editions; nothing is uploaded without them | Dashboard |
| Import | The edition's text, chain, matn, chapter and recorded ruling; the book under its published title | `scripts/import_shamela.py`, `app/services/books.py` |
| Rulings | Only as recorded, with their author; never generated | `scripts/import_shamela.py`; the website's verdicts |
| Isnad | The edition's linked narrators when it has them; otherwise read from the narration's wording and marked «مستخرج آليًا» | `app/services/isnad_tree.py` |
| Search | Word-for-word quotes (literal index) and meaning (embeddings); every result carries its book | `app/services/text_index.py`, `app/api/routes/site_api.py` |
| Checking a result by hand | Search the text on [الدرر السنية](https://dorar.net/hadith), or open the printed edition in [المكتبة الشاملة](https://shamela.ws) | — |

## Where the sources are used in this repository

| Place | How |
| --- | --- |
| `scripts/import_shamela.py`, `scripts/shamela/ShamelaExport.java` | Convert the Shamela editions (tests: `tests/unit/test_import_shamela.py`) |
| `app/services/books.py` | The eight books' titles and compilers |
| `scripts/import_hadiths.py` | Measures the cost of, and indexes, the converted files |
| `app/services/isnad_tree.py` | Reads chains from the wording where an edition doesn't link them |
| `README.md` → "Hadith books from المكتبة الشاملة" | How to convert and upload them |
