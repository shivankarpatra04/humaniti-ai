import cv2
import numpy as np
import pytest

from app.config import settings
from app.pipeline.facts import find_class_start
from app.pipeline.logo import TEMPLATES, logo_score
from app.pipeline.name_cards import check_tesseract, is_name_card, is_tutor, read_name_card, shows_tutor_off
from app.pipeline.video_facts import _tutor_region_brightness, _tutor_summary

ZOOM_GREY = 28


def logo_glyphs(scale: float) -> np.ndarray:
    glyphs = np.hstack(TEMPLATES)
    return cv2.resize(glyphs, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def lichess_board() -> np.ndarray:
    """A 640x360 screen share with a light/dark checkered board, the classic false positive."""
    frame = np.full((360, 640), 40, np.uint8)
    for row in range(8):
        for col in range(8):
            frame[20 + row * 40 : 60 + row * 40, 160 + col * 40 : 200 + col * 40] = (
                230 if (row + col) % 2 else 120
            )
    return frame


def test_logo_full_screen():
    frame = np.full((360, 640), 20, np.uint8)
    glyphs = logo_glyphs(1.0)
    frame[20 : 20 + glyphs.shape[0], 150 : 150 + glyphs.shape[1]] = glyphs

    score, scale = logo_score(frame)
    assert score >= 0.9 and scale == pytest.approx(1.0)


# 0.168 is the usual Zoom thumbnail (B482); 0.113 the smaller one of a whole-desktop share (B552, B558)
@pytest.mark.parametrize("size", [0.168, 0.113])
def test_logo_in_thumbnail_over_screen_share(size):
    frame = lichess_board()
    glyphs = logo_glyphs(size)
    frame[0:61, 532:640] = 20
    frame[10 : 10 + glyphs.shape[0], 545 : 545 + glyphs.shape[1]] = glyphs

    score, scale = logo_score(frame)
    assert score >= 0.9 and scale == pytest.approx(size, rel=0.05)


def test_chessboard_is_not_the_logo():
    assert logo_score(lichess_board())[0] < settings.logo_threshold


@pytest.mark.parametrize(
    "skin, lit",
    [(None, None), ((90, 120, 170), True), ((25, 35, 55), False)],
    ids=["nobody", "well-lit tutor", "dark tutor"],
)
def test_tutor_presence_and_lighting_on_8x8_background(skin, lit):
    """The background is colourless (black, grey and white logo parts), the tutor is not."""
    view = cv2.cvtColor(np.full((244, 436), 20, np.uint8), cv2.COLOR_GRAY2BGR)
    view[20:120, 60:200] = (128, 128, 128)
    view[130:160, 80:360] = (255, 255, 255)
    if skin:
        cv2.ellipse(view, (218, 200), (70, 90), 0, 0, 360, skin, -1)

    brightness = _tutor_region_brightness(view)

    if skin is None:
        assert brightness is None
    else:
        assert (brightness >= settings.tutor_region_min_brightness) == lit


@pytest.mark.parametrize(
    "face, lit, uncertain",
    [(85.0, True, False), (68.0, False, True), (73.0, True, True), (50.0, False, False)],
    ids=["bright", "just below", "just above", "dark"],
)
def test_lighting_close_to_the_threshold_is_uncertain(face, lit, uncertain):
    summary = _tutor_summary([(second, face, 70.0) for second in range(0, 600, 15)])

    assert (summary["lighting_ok"], summary["lighting_uncertain"]) == (lit, uncertain)


def name_card(name: str) -> np.ndarray:
    frame = np.full((360, 640), ZOOM_GREY, np.uint8)
    (w, h), _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.putText(frame, name, ((640 - w) // 2, (360 + h) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2)
    return frame


def test_tutor_name_card_is_read_and_matched():
    frame = name_card("Sample Teacher")

    assert is_name_card(frame)
    name = read_name_card(frame)
    assert is_tutor(name, "Sample Teacher")
    assert not is_tutor(name, "Other Person")


def screen_share_with_tile(name: str) -> np.ndarray:
    """A shared board with the active speaker's camera-off tile in the top-right thumbnail."""
    frame = lichess_board()
    frame[0:61, 532:640] = ZOOM_GREY
    (w, h), _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.32, 1)
    cv2.putText(frame, name, (586 - w // 2, 30 + h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.32, 255, 1)
    return frame


def test_tutor_camera_off_tile_during_screen_share():
    assert shows_tutor_off(screen_share_with_tile("Sample Teacher"), "Sample Teacher")
    assert not shows_tutor_off(screen_share_with_tile("Sam Example"), "Sample Teacher")


def test_black_corner_of_full_screen_logo_is_not_a_tile():
    frame = np.full((360, 640), 20, np.uint8)
    glyphs = logo_glyphs(1.0)
    frame[20 : 20 + glyphs.shape[0], 150 : 150 + glyphs.shape[1]] = glyphs

    assert not shows_tutor_off(frame, "Sample Teacher")


def test_dark_screen_share_is_not_a_name_card():
    assert not is_name_card(np.full((360, 640), 45, np.uint8))
    assert not is_name_card(lichess_board())


def test_missing_tesseract_fails_loudly(monkeypatch):
    monkeypatch.setattr(settings, "tesseract_cmd", "no-such-tesseract")
    with pytest.raises(RuntimeError, match="TESSERACT_CMD"):
        check_tesseract()


def talk(*starts: int) -> list[dict]:
    return [{"start": s, "end": s + 3, "text": "..."} for s in starts]


def speech_of(segments: list[dict]) -> list[tuple[float, float]]:
    return [(s["start"], s["end"]) for s in segments]


def test_class_start_is_after_the_waiting_room_announcement():
    # B482: "we start in one or two minutes" at 04:13, 2.5 min of silence, class from 06:51; Whisper
    # stretched one stray word over the whole silence, so only the VAD chunks show the gap
    announcement, lesson = talk(240, 245, 250, 253), talk(*range(411, 500, 10))
    stray_word = [{"start": 263, "end": 411, "text": "..."}]

    assert find_class_start(announcement + stray_word + lesson, speech_of(announcement + lesson)) == 411


def test_class_start_without_early_silence_is_the_first_steady_talk():
    # waiting-room hellos under a minute apart: no long silence, so the steady-talk rule decides
    segments = talk(10, 70, 125) + talk(*range(180, 260, 10))
    assert find_class_start(segments, speech_of(segments)) == 180
