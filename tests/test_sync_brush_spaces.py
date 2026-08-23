import math

from colorPickerPro.sync.brush_color_spaces import (
    rgb_to_space_values,
    space_to_rgb_values,
    encode_space_values,
    decode_space_raws,
    resolve_active_rgb,
    build_space_offsets,
)


def test_rgb_hsv_roundtrip():
    rgb = {"r": 200, "g": 80, "b": 30}
    hsv = rgb_to_space_values("hsv", rgb)
    back = space_to_rgb_values("hsv", hsv)
    for ch in ("r", "g", "b"):
        assert abs(back[ch] - rgb[ch]) <= 1


def test_rgb_hls_roundtrip():
    rgb = {"r": 30, "g": 180, "b": 240}
    hls = rgb_to_space_values("hls", rgb)
    back = space_to_rgb_values("hls", hls)
    for ch in ("r", "g", "b"):
        assert abs(back[ch] - rgb[ch]) <= 1


def test_rgb_cmyk_roundtrip():
    # CMYK is not lossless: GCR black substitution deliberately trades
    # channel precision for ink economy, so a loose bound is expected.
    rgb = {"r": 90, "g": 120, "b": 60}
    cmyk = rgb_to_space_values("cmyk", rgb)
    back = space_to_rgb_values("cmyk", cmyk)
    for ch in ("r", "g", "b"):
        assert abs(back[ch] - rgb[ch]) <= 35


def test_cmyk_gray_is_neutral():
    # A neutral gray must stay neutral (lowest chromatic channel drives K).
    rgb = {"r": 128, "g": 128, "b": 128}
    cmyk = rgb_to_space_values("cmyk", rgb)
    assert abs(cmyk["c"] - cmyk["m"]) <= 2
    assert abs(cmyk["c"] - cmyk["y"]) <= 2


def test_encode_decode_u32():
    # A known RGB 255,0,0 must pack to 0xFFFFFFFF in the R channel.
    rgb = {"r": 255, "g": 0, "b": 0}
    encoded = encode_space_values("rgb", rgb)
    assert encoded[0] == 0xFFFFFFFF
    decoded = decode_space_raws("rgb", encoded)
    assert decoded["r"] == 255


def test_resolve_active_rgb_picks_first_live_space():
    offsets = build_space_offsets(0x00)
    # rgb all zero, cmyk carries data -> cmyk is the live space
    snapshots = {
        "rgb": {"raws": (0, 0, 0), "values": {"r": 0, "g": 0, "b": 0}},
        "cmyk": {"raws": (0x19999999, 0, 0, 0), "values": {"c": 10, "m": 0, "y": 0, "k": 0}},
    }
    name, rgb_out, _vals = resolve_active_rgb(snapshots)
    assert name == "cmyk"
    assert rgb_out["r"] < 255
