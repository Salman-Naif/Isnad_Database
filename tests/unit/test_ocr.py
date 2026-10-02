"""Tests for OCR: page layout, comparing readings, the vision model client and the fallbacks."""

import httpx
import pytest
from PIL import Image, ImageDraw

from app.config import get_settings
from app.services import ocr

# --- Page layout ---


def line(draw, x0, x1, y, height=30):
    """A line of "text": words of ink separated by spaces, shifted line to line."""
    for x in range(x0 - (y * 37) % 140, x1, 140):
        left, right = max(x, x0), min(x + 115, x1)
        if right > left:
            draw.rectangle((left, y, right, y + height), fill="black")


def page(columns: int = 2, footer: bool = False, header: bool = True, angle: float = 0.0):
    """A synthetic 300-DPI page."""
    image = Image.new("L", (1800, 2600), "white")
    draw = ImageDraw.Draw(image)
    if header:
        line(draw, 150, 1650, 100, 40)  # running header text
        draw.rectangle((150, 170, 1650, 176), fill="black")  # rule under it
    bottom = 2150 if footer else 2450
    spans = [(150, 860), (940, 1650)] if columns == 2 else [(150, 1650)]
    for y in range(260, bottom, 60):
        for x0, x1 in spans:
            line(draw, x0, x1, y)
    if columns == 2:
        draw.rectangle((898, 240, 902, bottom), fill="black")  # rule down the gutter
    if footer:
        for y in (2250, 2320):
            line(draw, 150, 1650, y, 25)  # full-width footnotes
    return image.rotate(angle, fillcolor=255) if angle else image


def test_two_columns_are_read_right_column_first():
    right, left = ocr.text_regions(page(columns=2))
    assert right.width < 1000 and left.width < 1000
    # The right column holds the part of the page to the right of the gutter.
    assert ocr.ink_share(right) > 0.1 and ocr.ink_share(left) > 0.1


def test_single_column_page_stays_whole():
    regions = ocr.text_regions(page(columns=1))
    assert len(regions) == 1 and regions[0].width == 1800


def test_running_header_is_removed():
    (region,) = ocr.text_regions(page(columns=1))
    assert region.height < 2600 - 170


def test_full_width_footnotes_keep_their_place():
    regions = [r for r in ocr.text_regions(page(columns=2, footer=True)) if ocr.ink_share(r) > ocr.BLANK_MAX_INK]
    assert len(regions) == 3
    assert regions[2].width == 1800  # the footnotes, after both columns


def test_skewed_scan_is_straightened():
    regions = ocr.text_regions(page(columns=2, angle=1.5))
    assert len(regions) == 2


def test_blank_page_has_no_ink():
    assert ocr.ink_share(Image.new("L", (800, 1000), "white")) < ocr.BLANK_MAX_INK


def test_low_resolution_scans_are_enlarged_for_tesseract():
    small = Image.new("RGB", (800, 1100), "white")
    prepared = ocr.prepare_for_tesseract(small)
    assert prepared.mode == "L"
    assert max(prepared.size) == 3000

    big = Image.new("L", (2480, 3508), "white")  # A4 at 300 DPI: left as is
    assert ocr.prepare_for_tesseract(big).size == (2480, 3508)


# --- Comparing readings ---

READING = (
    "حَدَّثَنَا مُحَمَّدُ بْنُ بَشَّارٍ: حَدَّثَنَا الْأَنْصَارِيُّ: حَدَّثَنَا أَشْعَثُ عَنِ الْحَسَنِ، "
    "عَنْ أَبِي بَكْرَةَ، أَنَّ النَّبِيَّ ﷺ قَالَ ذَاتَ يَوْمٍ: «مَنْ رَأَى مِنْكُمْ رُؤْيَا؟» فَقَالَ رَجُلٌ: "
    "أَنَا رَأَيْتُ كَأَنَّ مِيزَانًا نَزَلَ مِنَ السَّمَاءِ فَوُزِنْتَ أَنْتَ وَأَبُو بَكْرٍ فَرَجَحْتَ أَنْتَ "
    "بِأَبِي بَكْرٍ، وَوُزِنَ أَبُو بَكْرٍ وَعُمَرُ فَرَجَحَ أَبُو بَكْرٍ، وَوُزِنَ عُمَرُ وَعُثْمَانُ فَرَجَحَ عُمَرُ، "
    "ثُمَّ رُفِعَ الْمِيزَانُ، فَرَأَيْنَا الْكَرَاهِيَةَ فِي وَجْهِ رَسُولِ اللَّهِ ﷺ. " * 2
)
# The same text with a phrase skipped — the classic OCR slip ("…فرجح أبو بكر، ووزن عمر وعثمان")
SKIPPED = READING.replace("فَرَجَحَ أَبُو بَكْرٍ، وَوُزِنَ عُمَرُ وَعُثْمَانُ ", "", 1)
# The same text without diacritics and with a different spelling of one name
PLAIN = ocr._DIACRITICS.sub("", READING).replace("الله", "اللّه")


def test_readings_that_differ_only_in_diacritics_agree():
    assert ocr.agree(READING, PLAIN)


def test_one_misread_word_in_a_short_block_is_tolerated():
    assert ocr.agree("وقال: إن الماء لا يتغير بشيء أبدا", "وقال: إن الماء لا يتغير بشيء أبد")
    assert not ocr.agree("وقال: إن الماء لا يتغير بشيء أبدا", "وقيل: إن الماءَ لم تغير شيء أبدا")


def test_a_skipped_phrase_is_a_disagreement():
    ratio, _, gap = ocr.compare(READING, SKIPPED)
    assert ratio > 0.95  # nearly the same text...
    assert gap >= ocr.AGREEMENT_MAX_GAP  # ...but a whole phrase is missing
    assert not ocr.agree(READING, SKIPPED)


def test_majority_reading_wins():
    best, disputed = ocr.pick_majority([SKIPPED, READING, PLAIN])
    assert best == READING and not disputed


def test_three_different_readings_are_disputed():
    other = "نص مختلف تماما عن الصفحة " * 10
    _, disputed = ocr.pick_majority([READING, SKIPPED[: len(SKIPPED) // 2], other])
    assert disputed


def test_model_output_is_tidied():
    assert ocr.tidy("```\n٢٢۸۳ - حدثنی\n```") == "٢٢٨٣ - حدثني"


# --- Vision model client ---


@pytest.fixture
def vision(monkeypatch):
    """Vision engine on, with instant retries and a scripted OpenRouter."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OCR_ENGINE", "vision")
    get_settings.cache_clear()
    monkeypatch.setattr(ocr, "RETRY_DELAYS", (0, 0, 0))
    ocr._needs_reasoning.clear()
    yield
    get_settings.cache_clear()


def scripted(*responses):
    """An httpx client answering with the given (status, json) pairs in order."""
    queue = list(responses)
    sent = []

    def handler(request):
        sent.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.sent = sent
    return client


def completion(text, finish="stop", cost=0.002):
    return 200, {"choices": [{"message": {"content": text}, "finish_reason": finish}], "usage": {"cost": cost}}


IMAGE = Image.new("L", (400, 600), "white")


def test_vision_read_returns_text_and_cost(vision):
    client = scripted(completion("نص الصفحة"))
    reading = ocr.vision_read(IMAGE, "google/model", client)
    assert reading.text == "نص الصفحة" and reading.cost == 0.002
    body = client.sent[0].read().decode()
    assert '"temperature":0' in body.replace(" ", "")
    assert "image/png;base64" in body


def test_rate_limits_are_retried(vision):
    client = scripted((429, {"error": "slow down"}), (503, {"error": "busy"}), completion("نص"))
    assert ocr.vision_read(IMAGE, "google/model", client).text == "نص"
    assert len(client.sent) == 3


def test_permanent_errors_are_not_retried(vision):
    client = scripted((401, {"error": "bad key"}))
    with pytest.raises(ocr.VisionError):
        ocr.vision_read(IMAGE, "google/model", client)
    assert len(client.sent) == 1


def test_out_of_credit_stops_the_file_instead_of_falling_back(vision, monkeypatch):
    main, check, _ = models()
    broke = ocr.OutOfCredit("HTTP 402")
    with (
        reader_with(monkeypatch, {main: broke, check: broke}) as reader,
        pytest.raises(ocr.OcrUnavailable, match="رصيد OpenRouter"),
    ):
        reader.read(IMAGE)


def test_402_is_out_of_credit(vision):
    with pytest.raises(ocr.OutOfCredit):
        ocr.vision_read(IMAGE, "google/model", scripted((402, {"error": "Insufficient credits"})))


def test_models_that_require_reasoning_are_retried_with_it(vision):
    client = scripted((400, {"error": "Reasoning is mandatory for this endpoint"}), completion("نص"))
    assert ocr.vision_read(IMAGE, "google/thinker", client).text == "نص"
    assert '"effort"' in client.sent[1].read().decode()


def test_cut_off_or_blocked_transcriptions_are_errors(vision):
    for finish in ("length", "content_filter"):
        with pytest.raises(ocr.VisionError):
            ocr.vision_read(IMAGE, "google/model", scripted(completion("نص ناقص", finish)))


# --- Reading a page: second reading, referee, fallbacks ---


def reader_with(monkeypatch, answers: dict, tesseract="قراءة تسراكت"):
    """A PageReader whose models answer from `answers` (model → text or exception)."""
    calls = []

    def fake_vision(image, model, client=None):
        calls.append(model)
        answer = answers[model]
        if isinstance(answer, Exception):
            raise answer
        return ocr.Reading(answer, 0.001)

    monkeypatch.setattr(ocr, "vision_read", fake_vision)
    monkeypatch.setattr(ocr, "tesseract_read", lambda image: tesseract)
    monkeypatch.setattr(ocr, "text_regions", lambda image: [image])
    monkeypatch.setattr(ocr, "ink_share", lambda image: 0.1)
    reader = ocr.PageReader()
    reader.calls = calls
    return reader


def models():
    s = get_settings()
    return s.ocr_model, s.ocr_check_model, s.ocr_referee_model


def test_agreeing_readings_keep_the_main_one(vision, monkeypatch):
    main, check, referee = models()
    with reader_with(monkeypatch, {main: READING, check: PLAIN}) as reader:
        result = reader.read(IMAGE)
    assert result.text == READING and not result.disputed
    assert referee not in reader.calls
    assert result.cost == pytest.approx(0.002)


def test_disagreement_calls_the_referee(vision, monkeypatch):
    main, check, referee = models()
    with reader_with(monkeypatch, {main: SKIPPED, check: READING, referee: READING}) as reader:
        result = reader.read(IMAGE)
    assert result.text == READING  # the main model skipped a phrase and was outvoted
    assert referee in reader.calls and not result.disputed


def test_main_model_failure_uses_the_second_reading(vision, monkeypatch):
    main, check, _ = models()
    with reader_with(monkeypatch, {main: ocr.VisionError("down"), check: READING}) as reader:
        assert reader.read(IMAGE).text == READING


def test_vision_outage_falls_back_to_tesseract(vision, monkeypatch):
    main, check, _ = models()
    down = ocr.VisionError("down")
    with reader_with(monkeypatch, {main: down, check: down}) as reader:
        result = reader.read(IMAGE)
    assert result.text == "قراءة تسراكت" and result.fallback


def test_without_a_key_tesseract_is_used(monkeypatch):
    # conftest leaves OPENROUTER_API_KEY empty
    assert not ocr.vision_enabled()
    with reader_with(monkeypatch, {}) as reader:
        assert reader.read(IMAGE).text == "قراءة تسراكت"
    assert reader.calls == []


def test_stats_note_lists_pages_to_review():
    stats = ocr.OcrStats()
    stats.add(12, ocr.PageResult("x", disputed=True))
    stats.add(3, ocr.PageResult("x", fallback=True))
    stats.add(4, ocr.PageResult("x"))
    assert stats.pages == 3
    assert "12" in stats.note() and "3" in stats.note()
    assert ocr.OcrStats().note() is None
