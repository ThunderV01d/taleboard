"""
Unit tests for turning raw generations into cutouts: monochrome conversion, the checks that something solid was cut out, and trimming and fitting to a standard size.

Image generation and background removal are faked, so nothing here costs anything.
"""
import io

import pytest
from PIL import Image

from taleboard.generation.cutouts import (
    CHARACTER_HEIGHT, MAX_CUTOUT_ATTEMPTS, MAX_PARTIAL_FRACTION, MIN_OPAQUE_FRACTION, PROP_SIZE, CutoutRejectedError,
    fit_character, fit_prop, generate_cutout, opaque_fraction, partial_fraction, remove_white_background, to_monochrome,
)
from PIL import ImageDraw


def _png(colour: tuple, mode: str = "RGB") -> bytes:
    """
    A small solid image, as PNG bytes.

    Arguments:
        colour: tuple - Its colour (with alpha, for "RGBA").
        mode: str - PIL image mode. Defaults to "RGB".

    Returns:
        bytes - The PNG.
    """
    buffer = io.BytesIO()
    Image.new(mode, (10, 10), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_to_monochrome_strips_colour_and_keeps_transparency():
    """
    Verifies that monochrome conversion turns colour grey, leaves grey alone, and keeps a cutout's alpha.
    """
    red = Image.open(io.BytesIO(to_monochrome(_png((200, 30, 30))))).convert("RGB").getpixel((5, 5))
    grey = Image.open(io.BytesIO(to_monochrome(_png((128, 128, 128))))).convert("RGB").getpixel((5, 5))
    cutout = Image.open(io.BytesIO(to_monochrome(_png((200, 30, 30, 0), "RGBA"))))

    assert red[0] == red[1] == red[2]
    assert grey == (128, 128, 128)
    assert cutout.mode == "RGBA" and cutout.getpixel((5, 5))[3] == 0


def test_opaque_and_partial_fractions_measure_how_solid_a_cutout_is():
    """
    Verifies the two measures: an empty cutout has nothing opaque; a see-through one is all partly opaque; faint edge noise doesn't count; no alpha counts as solid.
    """
    assert opaque_fraction(_png((0, 0, 0, 0), "RGBA")) == 0.0
    assert opaque_fraction(_png((1, 2, 3))) == 1.0
    assert partial_fraction(_png((255, 0, 0, 255), "RGBA")) == 0.0
    assert partial_fraction(_png((255, 0, 0, 140), "RGBA")) == 1.0
    assert partial_fraction(_png((255, 0, 0, 8), "RGBA")) == 0.0


@pytest.mark.parametrize("bad", [(0, 0, 0, 0), (255, 0, 0, 140)])  # Empty, then see-through
def test_a_bad_cutout_is_tried_again_and_then_given_up_on(bad):
    """
    Verifies that an empty or see-through cutout is generated again, and raises CutoutRejectedError once every attempt is used.

    Arguments:
        bad: tuple - The colour (with alpha) every cutout comes out as.
    """
    calls = []

    def generate(text, negative_text, **kwargs):
        calls.append(kwargs)
        return _png((255, 255, 255))

    with pytest.raises(CutoutRejectedError):
        generate_cutout("a lantern", "", generate, lambda image: _png(bad, "RGBA"), reference_images=[b"ref"])
    assert len(calls) == MAX_CUTOUT_ATTEMPTS
    assert all(call == {"reference_images": [b"ref"]} for call in calls)


def test_a_cutout_that_comes_out_solid_the_second_time_is_kept():
    """
    Verifies that a bad first cutout is retried, and a solid second one returned.
    """
    cutouts = iter([_png((0, 0, 0, 0), "RGBA"), _png((255, 0, 0, 255), "RGBA")])

    result = generate_cutout("a lantern", "", lambda text, negative_text, **kwargs: _png((255, 255, 255)), lambda image: next(cutouts))

    assert partial_fraction(result) == 0.0 and opaque_fraction(result) == 1.0


def _padded(size: tuple[int, int], box: tuple[int, int, int, int]) -> bytes:
    """
    A transparent cutout with a solid figure in one box, faint edge noise in its corner, and padding all round -- as background removal leaves it.

    Arguments:
        size: tuple[int,int] - The whole image's width and height.
        box: tuple[int,int,int,int] - The figure's left, top, right and bottom.

    Returns:
        bytes - The PNG.
    """
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((90, 90, 90, 255), box)
    image.putpixel((0, 0), (90, 90, 90, 8))  # Too faint to count
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _size(image: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(image)).size


def test_a_character_is_trimmed_to_the_figure_and_fitted_to_the_standard_height():
    """
    Verifies that the padding (and faint noise) round a figure is cut away, and the figure scaled -- keeping its shape -- to CHARACTER_HEIGHT tall.
    """
    fitted = fit_character(_padded((640, 2048), (220, 240, 420, 1940)))  # A 200x1700 figure

    assert _size(fitted) == (round(200 * CHARACTER_HEIGHT / 1700), CHARACTER_HEIGHT)
    assert Image.open(io.BytesIO(fitted)).getpixel((0, CHARACTER_HEIGHT - 1))[3] == 255  # Feet on the bottom edge


@pytest.mark.parametrize("box, expected", [
    ((100, 300, 500, 500), (PROP_SIZE, PROP_SIZE // 2)),  # Wide: 400x200
    ((300, 100, 400, 500), (PROP_SIZE // 4, PROP_SIZE)),  # Tall: 100x400
])
def test_a_prop_is_trimmed_and_fitted_by_its_longer_side(box, expected):
    """
    Verifies that a prop's longer side is fitted to PROP_SIZE, whichever way round it is.

    Arguments:
        box: tuple - The object's box in a 640x640 cutout.
        expected: tuple[int,int] - Its fitted size.
    """
    assert _size(fit_prop(_padded((640, 640), box))) == expected


def test_an_image_with_nothing_to_trim_to_is_only_scaled():
    """
    Verifies that an image with no transparency, or nothing visible, is scaled whole.
    """
    assert _size(fit_character(_png((1, 2, 3)))) == (CHARACTER_HEIGHT, CHARACTER_HEIGHT)
    assert _size(fit_prop(_png((0, 0, 0, 0), "RGBA"))) == (PROP_SIZE, PROP_SIZE)


def _drawn_on_white(box: tuple[int, int, int, int]) -> bytes:
    """
    A phone-like drawing on white: a dark outline round a white "screen", in a 100x100 image.
    """
    image = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(image).rectangle(box, outline=(20, 20, 20), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_prop_on_white_loses_its_background_but_keeps_the_white_inside_its_outline():
    """
    Verifies the flood fill: the white round the object goes, the white its outline encloses stays solid -- and the cutout passes the checks the model's see-through cutouts failed.
    """
    cutout = Image.open(io.BytesIO(remove_white_background(_drawn_on_white((30, 20, 70, 80)))))

    assert cutout.mode == "RGBA"
    assert cutout.getpixel((5, 5))[3] == 0  # Background
    assert cutout.getpixel((50, 50))[3] == 255  # The "screen", inside the outline
    assert cutout.getpixel((31, 50))[3] >= 224  # The outline -- solid, if softened a little where it meets the background
    data = remove_white_background(_drawn_on_white((30, 20, 70, 80)))
    assert opaque_fraction(data) >= MIN_OPAQUE_FRACTION and partial_fraction(data) <= MAX_PARTIAL_FRACTION


def test_an_object_touching_the_edge_still_loses_the_white_round_it():
    """
    Verifies that the background is every white region reaching any edge -- not only one seeded from a corner.
    """
    cutout = Image.open(io.BytesIO(remove_white_background(_drawn_on_white((0, 0, 60, 60)))))

    assert cutout.getpixel((90, 90))[3] == 0
    assert cutout.getpixel((30, 30))[3] == 255


def test_an_image_with_no_white_round_it_is_kept_whole():
    """
    Verifies that an image with no white background (eg:- a solid colour) is left fully opaque.
    """
    cutout = Image.open(io.BytesIO(remove_white_background(_png((200, 40, 40)))))

    assert cutout.getpixel((5, 5))[3] == 255
