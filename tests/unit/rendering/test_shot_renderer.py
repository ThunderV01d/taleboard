"""
Unit tests for shot_renderer.

Uses fake image generation and background removal functions, so no images are generated and no API calls are made.

Covers monochrome conversion, the cutout, background and reference image caches, cutout rejection, and how render_shot dispatches to background and character rendering.
"""
import io

import pytest
from PIL import Image

from taleboard.rendering import compositor
from taleboard.rendering.prompts import CAMERA_ANGLE_PHRASES, STYLE_PREFIX
from taleboard.rendering.shot_renderer import BackgroundCache, CutoutCache, CutoutRejectedError, ReferenceImageCache, _background_cache_key, _opaque_fraction, _to_monochrome, render_background, render_characters, render_shot
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region, Shot


def _character(char_id: str = "alice") -> dict[str, Character]:
    """
    Builds a one-character mapping.

    Arguments:
        char_id: str - Character ID (also used, title-cased, as the name). Defaults to "alice".

    Returns:
        dict[str,Character] - Mapping of the character ID to a Character object.
    """
    return {char_id: Character(name=char_id.title(), description="...")}


def _region(
    character_id: str = "alice",
    position: PositionCell = PositionCell.MID_CENTER,
    action: str = "standing",
    orientation: Orientation = Orientation.TOWARDS_CAMERA,
    size: SizeInFrame = SizeInFrame.MEDIUM,
) -> Region:
    """
    Builds a region, defaulting to Alice standing in the centre, facing the camera.

    Arguments:
        character_id: str - Character ID of the region. Defaults to "alice".
        position: PositionCell - Position of the region in the 3x3 grid. Defaults to MID_CENTER.
        action: str - Action of the region. Defaults to "standing".
        orientation: Orientation - Orientation of the region. Defaults to TOWARDS_CAMERA.
        size: SizeInFrame - Size of the region in the frame. Defaults to MEDIUM.

    Returns:
        Region - A Region object.
    """
    return Region(
        character_id=character_id,
        position=position,
        size=size,
        orientation=orientation,
        action=action,
    )

def _shot(
    regions: list[Region] | None = None,
    setting: str = "an empty hallway",
    shot_size: ShotSize = ShotSize.MEDIUM,
    angle: CameraAngle = CameraAngle.EYE_LEVEL,
) -> Shot:
    """
    Builds a shot, defaulting to a medium, eye-level shot of an empty hallway with no characters.

    Arguments:
        regions: list[Region] - Character regions of the shot. Defaults to None (no regions).
        setting: str - Setting of the shot. Defaults to "an empty hallway".
        shot_size: ShotSize - Size of the shot. Defaults to MEDIUM.
        angle: CameraAngle - Camera angle of the shot. Defaults to EYE_LEVEL.

    Returns:
        Shot - A Shot object.
    """
    return Shot(
        description="a shot",
        setting=setting,
        regions=regions if regions is not None else [],
        paragraph_index=0,
        shot_size=shot_size,
        angle=angle,
        duration_s=2.0,
    )

def _solid_color_png(color: tuple[int, int, int]) -> bytes:
    """
    Builds a small, solid-colour image with no alpha channel, standing in for a raw generation.

    Arguments:
        color: tuple[int,int,int] - Colour of the image (RGB).

    Returns:
        bytes - Image file (PNG, in bytes).
    """
    image = Image.new("RGB", (10, 10), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _fake_cutout_bytes() -> bytes:
    """
    Builds a small, fully opaque red image, standing in for a successful cutout.

    Returns:
        bytes - Cutout image file (PNG, in bytes).
    """
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _make_fakes():
    """
    Builds a fake image generation function that counts its calls, and a fake background removal function.

    Returns:
        tuple[GenerateImage,RemoveBackground,dict[str,int]] - Fake generation function, fake background removal function, and the call counter (under "generate").
    """
    calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Counts the call and returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        calls["generate"] += 1
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    return fake_generate_image, fake_remove_background, calls

def test_to_monochrome_strips_colour_from_a_coloured_image():
    """
    Verifies that monochrome conversion turns a coloured image grey.
    """
    coloured = _solid_color_png((200, 30, 30))  # Red
    result = _to_monochrome(coloured)

    image = Image.open(io.BytesIO(result)).convert("RGB")
    r, g, b = image.getpixel((5, 5))
    assert r == g == b


def test_to_monochrome_preserves_an_already_grey_image():
    """
    Verifies that monochrome conversion leaves an already grey image unchanged.
    """
    grey = _solid_color_png((128, 128, 128))
    result = _to_monochrome(grey)

    image = Image.open(io.BytesIO(result)).convert("RGB")
    assert image.getpixel((5, 5)) == (128, 128, 128)

def test_to_monochrome_preserves_alpha_channel():
    """
    Verifies that monochrome conversion keeps a cutout's transparency, for both opaque and transparent pixels.
    """
    coloured_cutout = _fake_cutout_bytes()
    result = _to_monochrome(coloured_cutout)

    image = Image.open(io.BytesIO(result))
    assert image.mode == "RGBA"
    assert image.getpixel((5, 5))[3] == 255  # Alpha preserved

    transparent = Image.new("RGBA", (10, 10), (200, 30, 30, 0))
    buffer = io.BytesIO()
    transparent.save(buffer, format="PNG")
    result = _to_monochrome(buffer.getvalue())

    image = Image.open(io.BytesIO(result))
    assert image.getpixel((5, 5))[3] == 0

def test_renders_without_error_for_a_single_region():
    """
    Verifies that a single region renders, costing one reference generation and one pose generation.
    """
    generate_image, remove_background, calls = _make_fakes()

    result = render_characters(
        regions=[_region()],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert len(result) > 0
    assert calls["generate"] == 2


def test_same_character_action_orientation_only_generates_once():
    """
    Verifies that two regions with the same character, action and orientation share one pose generation, even at different positions.
    """
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(position=PositionCell.MID_LEFT)
    region_b = _region(position=PositionCell.MID_RIGHT)

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 2


def test_different_action_triggers_a_second_generation():
    """
    Verifies that a different action needs its own pose generation.
    """
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(action="standing")
    region_b = _region(action="waving")

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 3


def test_different_orientation_triggers_a_second_generation():
    """
    Verifies that a different orientation needs its own pose generation.
    """
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(orientation=Orientation.TOWARDS_CAMERA)
    region_b = _region(orientation=Orientation.LEFT)

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 3


def test_cache_is_reused_across_separate_render_shot_calls():
    """
    Verifies that the cutout cache is reused across separate render calls, so a repeated pose costs nothing.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    region = _region()
    characters = _character()

    render_characters(regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, generate_image=generate_image, remove_background=remove_background)
    render_characters(regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, generate_image=generate_image, remove_background=remove_background)

    assert calls["generate"] == 2


def test_different_character_sharing_a_pose_still_shares_nothing():
    """
    Verifies that two characters in the same pose each get their own reference and pose generations.
    """
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(character_id="alice")
    region_b = _region(character_id="bob")
    characters = {**_character("alice"), **_character("bob")}

    render_characters(
        regions=[region_a, region_b],
        characters=characters,
        cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 4


def test_region_for_unknown_character_raises():
    """
    Verifies that a region for a character that isn't in the cast raises a KeyError.
    """
    generate_image, remove_background, _ = _make_fakes()

    with pytest.raises(KeyError):
        render_characters(
            regions=[_region(character_id="nobody")],
            characters=_character("alice"),
            cache={},
            reference_cache={},
            generate_image=generate_image,
            remove_background=remove_background,
        )

def test_remove_background_receives_the_raw_coloured_generation():
    """
    Verifies the pipeline order: generate, then remove the background, then strip colour.

    Background removal must receive the raw, coloured generation, not an already monochrome one.
    """
    received: dict[str, bytes] = {}

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        return _solid_color_png((200, 30, 30))

    def spying_remove_background(raw_bytes: bytes) -> bytes:
        """
        Records the image it was given and returns a successful cutout.

        Arguments:
            raw_bytes: bytes - Raw generated image.

        Returns:
            bytes - Cutout image file (in bytes).
        """
        received["raw_bytes"] = raw_bytes
        return _fake_cutout_bytes()

    render_characters(
        regions=[_region()],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=fake_generate_image,
        remove_background=spying_remove_background,
    )

    image = Image.open(io.BytesIO(received["raw_bytes"])).convert("RGB")
    assert image.getpixel((5, 5)) == (200, 30, 30)

def test_left_and_right_orientation_each_generate_independently():
    """
    Verifies that facing left and facing right are each their own real generation, with their own cache entries.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    characters = _character()

    render_characters(
        regions=[_region(orientation=Orientation.LEFT)],
        characters=characters,
        cache=cache,
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)],
        characters=characters,
        cache=cache,
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )

    # First call: one reference + one real LEFT pose
    # Second call: the reference is already cached (same character), but RIGHT is its own orientation -- a cutout cache miss, so a real second pose generation
    assert calls["generate"] == 3
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.RIGHT.value, CameraAngle.EYE_LEVEL.value) in cache


def test_right_orientation_alone_generates_its_own_real_pose():
    """
    Verifies that a right-facing region is generated directly, with nothing cached for the left-facing pose.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}

    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)],
        characters=_character(),
        cache=cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 2  # One reference + one real RIGHT pose
    assert ("alice", "standing", Orientation.RIGHT.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value) not in cache

def test_cached_cutout_is_monochrome():
    """
    Verifies that cutouts are stored in the cache already converted to monochrome.
    """
    generate_image, remove_background, _ = _make_fakes()
    cache: CutoutCache = {}

    render_characters(
        regions=[_region()],
        characters=_character(),
        cache=cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    cached_cutout = cache[("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value)]
    image = Image.open(io.BytesIO(cached_cutout)).convert("RGB")
    r, g, b = image.getpixel((5, 5))
    assert r == g == b

def test_render_characters_defaults_reproduce_the_pre_angle_cache_key():
    """
    Verifies that leaving out the camera angle caches the cutout under the eye-level key.
    """
    generate_image, remove_background, _ = _make_fakes()
    cache: CutoutCache = {}

    render_characters(
        regions=[_region()],
        characters=_character(),
        cache=cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in cache


def test_different_camera_angle_triggers_a_second_generation():
    """
    Verifies that the same pose at a different camera angle needs its own generation and cache entry.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    region = _region()
    characters = _character()

    render_characters(
        regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.EYE_LEVEL, generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.LOW, generate_image=generate_image, remove_background=remove_background,
    )

    assert calls["generate"] == 3
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.LOW.value) in cache


def test_same_camera_angle_reuses_the_cache():
    """
    Verifies that the same pose at the same camera angle is served from the cache.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    region = _region()
    characters = _character()

    render_characters(
        regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.HIGH, generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.HIGH, generate_image=generate_image, remove_background=remove_background,
    )

    assert calls["generate"] == 2


def test_right_orientation_still_respects_camera_angle_in_the_cache_key():
    """
    Verifies that left- and right-facing poses are cached under keys that include the camera angle.
    """
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    characters = _character()

    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.LOW, generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[_region(orientation=Orientation.LEFT)], characters=characters, cache=cache, reference_cache=reference_cache, angle=CameraAngle.LOW, generate_image=generate_image, remove_background=remove_background,
    )

    assert calls["generate"] == 3
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.LOW.value) in cache


def test_render_characters_passes_shot_size_through_to_compositing():
    """
    Verifies that the shot size reaches the compositor, so a wide shot and a close-up of the same region look different.
    """
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    region = _region()
    characters = _character()

    wide_result = render_characters(
        regions=[region], characters=characters, cache={}, reference_cache={}, shot_size=ShotSize.WIDE,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    close_up_result = render_characters(
        regions=[region], characters=characters, cache={}, reference_cache={}, shot_size=ShotSize.CLOSE_UP,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )

    assert wide_result != close_up_result

def test_render_characters_background_param_changes_the_output():
    """
    Verifies that a background passed to render_characters is actually used in the composited shot.
    """
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    background = _solid_color_png((10, 200, 10))
    region = _region()
    characters = _character()

    with_background = render_characters(
        regions=[region], characters=characters, cache={}, reference_cache={}, background=background,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    without_background = render_characters(
        regions=[region], characters=characters, cache={}, reference_cache={}, generate_image=fake_generate_image, remove_background=fake_remove_background,
    )

    assert with_background != without_background

def _make_background_fakes():
    """
    Builds a fake background generation function that counts its calls.

    There is no fake background removal here, as a background render has nothing to cut out.

    Returns:
        tuple[GenerateImage,dict[str,int]] - Fake generation function and the call counter (under "generate").
    """
    calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str) -> bytes:
        """
        Counts the call and returns a solid blue image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).

        Returns:
            bytes - Solid blue image file (in bytes).
        """
        calls["generate"] += 1
        return _solid_color_png((60, 120, 180))  # Deliberately coloured

    return fake_generate_image, calls


def test_render_background_returns_a_nonempty_image():
    """
    Verifies that a background render produces an image.
    """
    generate_image, _ = _make_background_fakes()

    result = render_background(
        setting="an empty hallway",
        shot_size=ShotSize.MEDIUM,
        angle=CameraAngle.EYE_LEVEL,
        cache={},
        generate_image=generate_image,
    )

    assert len(result) > 0


def test_render_background_does_not_take_a_remove_background_argument():
    """
    Verifies that render_background rejects a background removal argument, rather than silently ignoring it.

    A background render is the whole frame, not a subject to isolate -- there is nothing to cut out.
    """
    generate_image, _ = _make_background_fakes()

    with pytest.raises(TypeError):
        render_background(  # type: ignore[call-arg]
            setting="an empty hallway",
            shot_size=ShotSize.MEDIUM,
            angle=CameraAngle.EYE_LEVEL,
            cache={},
            generate_image=generate_image,
            remove_background=lambda raw: raw,
        )


def test_render_background_output_is_monochrome():
    """
    Verifies that a background render is converted to monochrome.
    """
    generate_image, _ = _make_background_fakes()

    result = render_background(
        setting="an empty hallway",
        shot_size=ShotSize.MEDIUM,
        angle=CameraAngle.EYE_LEVEL,
        cache={},
        generate_image=generate_image,
    )

    image = Image.open(io.BytesIO(result)).convert("RGB")
    r, g, b = image.getpixel((5, 5))
    assert r == g == b


def test_render_background_caches_on_setting_shot_size_and_angle():
    """
    Verifies that the same setting, shot size and angle are only rendered once.
    """
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}

    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)

    assert calls["generate"] == 1


def test_render_background_different_setting_triggers_a_second_generation():
    """
    Verifies that a different setting needs its own background render.
    """
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}

    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("a crowded train platform", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)

    assert calls["generate"] == 2


def test_render_background_different_shot_size_triggers_a_second_generation():
    """
    Verifies that a different shot size needs its own background render.
    """
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}

    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.WIDE, CameraAngle.EYE_LEVEL, cache, generate_image)

    assert calls["generate"] == 2


def test_render_background_different_angle_triggers_a_second_generation():
    """
    Verifies that a different camera angle needs its own background render.
    """
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}

    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW, cache, generate_image)

    assert calls["generate"] == 2


def test_background_cache_key_matches_the_stored_cache_entry():
    """
    Verifies that the background cache key is built from the setting, shot size and angle values, and matches what is stored.
    """
    generate_image, _ = _make_background_fakes()
    cache: BackgroundCache = {}

    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW, cache, generate_image)

    key = _background_cache_key("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW)
    assert key == ("an empty hallway", "medium", "low")
    assert key in cache

def test_render_shot_with_no_regions_renders_a_background():
    """
    Verifies that a shot with no character regions is rendered as a background only.

    An establishing or object-insert shot should never reach character generation or compositing.
    """
    character_calls = {"generate": 0}
    background_calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid blue image.

        Shared by both the background and character paths, so it doesn't count calls itself.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid blue image file (in bytes).
        """
        return _solid_color_png((60, 120, 180))

    def spying_remove_background(raw_bytes: bytes) -> bytes:
        """
        Counts the call and returns a successful cutout.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        character_calls["generate"] += 1
        return _fake_cutout_bytes()

    shot = _shot(regions=[], setting="an empty hallway")

    result = render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache={},
        reference_cache={},
        generate_image=fake_generate_image,
        remove_background=spying_remove_background,
    )

    assert len(result.image) > 0
    # Background removal is only ever called on the character path -- a background-only shot should never reach it
    assert character_calls["generate"] == 0


def test_render_shot_with_no_regions_uses_the_background_cache():
    """
    Verifies that rendering the same background-only shot twice only generates the background once.
    """
    generate_image, calls = _make_background_fakes()
    background_cache: BackgroundCache = {}
    shot = _shot(regions=[], setting="an empty hallway")

    render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache=background_cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=lambda raw: raw,
    )
    render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache=background_cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=lambda raw: raw,
    )

    assert calls["generate"] == 1


def test_render_shot_with_regions_renders_characters_and_background():
    """
    Verifies that a shot with regions renders its background as well as its characters.

    That costs one background generation plus the character generations (here, one reference and one pose).
    """
    generate_image, remove_background, calls = _make_fakes()
    shot = _shot(regions=[_region()], setting="an empty hallway")

    result = render_shot(
        shot=shot,
        characters=_character(),
        character_cache={},
        background_cache={},
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert len(result.image) > 0
    assert calls["generate"] == 3


def test_render_shot_with_regions_reuses_both_caches_across_repeated_calls():
    """
    Verifies that rendering the same shot twice hits both the background cache and the cutout cache.

    The second call makes no new generation calls at all, on either side.
    """
    generate_image, remove_background, calls = _make_fakes()
    character_cache: CutoutCache = {}
    background_cache: BackgroundCache = {}
    shot = _shot(regions=[_region()], setting="an empty hallway")

    render_shot(
        shot=shot,
        characters=_character(),
        character_cache=character_cache,
        background_cache=background_cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_shot(
        shot=shot,
        characters=_character(),
        character_cache=character_cache,
        background_cache=background_cache,
        reference_cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 3
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in character_cache

def test_render_shot_composites_characters_over_the_rendered_background():
    """
    Verifies that characters are composited over the rendered background, not over plain white.

    A point well outside any character's box should show the background's own (monochrome) colour.
    """
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid blue image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid blue image file (in bytes).
        """
        return _solid_color_png((60, 120, 180))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    shot = _shot(regions=[_region()], setting="an empty hallway")

    result = render_shot(
        shot=shot,
        characters=_character(),
        character_cache={},
        background_cache={},
        reference_cache={},
        generate_image=fake_generate_image,
        remove_background=fake_remove_background,
    )

    expected_background_pixel = Image.open(
        io.BytesIO(_to_monochrome(_solid_color_png((60, 120, 180))))
    ).convert("RGB").getpixel((5, 5))

    result_pixel = Image.open(io.BytesIO(result.image)).convert("RGB").getpixel((10, 10))
    assert result_pixel != (255, 255, 255)
    assert result_pixel == expected_background_pixel

def test_render_shot_passes_the_shots_angle_to_render_characters():
    """
    Verifies that render_shot passes the shot's camera angle through to character generation.
    """
    captured_prompts: list[str] = []

    def spying_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Records the prompt and returns a solid red image.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        captured_prompts.append(text)
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    shot = _shot(regions=[_region()], setting="an empty hallway", angle=CameraAngle.LOW)

    render_shot(
        shot=shot,
        characters=_character(),
        character_cache={},
        background_cache={},
        reference_cache={},
        generate_image=spying_generate_image,
        remove_background=fake_remove_background,
    )

    character_prompts = [p for p in captured_prompts if p.startswith(STYLE_PREFIX)]
    assert any(CAMERA_ANGLE_PHRASES[CameraAngle.LOW] in p for p in character_prompts)

def test_render_shot_passes_the_shots_shot_size_to_render_characters():
    """
    Verifies that render_shot passes the shot's size through to compositing.
    """
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    wide_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.WIDE)
    close_up_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.CLOSE_UP)

    wide_result = render_shot(
        shot=wide_shot, characters=_character(), character_cache={}, background_cache={}, reference_cache={}, generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    close_up_result = render_shot(
        shot=close_up_shot, characters=_character(), character_cache={}, background_cache={}, reference_cache={},  generate_image=fake_generate_image, remove_background=fake_remove_background,
    )

    assert wide_result.image != close_up_result.image


def test_reference_image_generated_once_per_character_and_reused_across_poses():
    """
    Verifies that a character's reference image is generated on their first pose, then reused for every later pose.

    That reuse is the whole point of caching references separately from poses.
    """
    generate_image, remove_background, calls = _make_fakes()
    reference_cache: ReferenceImageCache = {}
    characters = _character()

    render_characters(
        regions=[_region(action="standing")],
        characters=characters,
        cache={},
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_characters(
        regions=[_region(action="waving")],
        characters=characters,
        cache={},
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )

    # First pose: one reference + one pose generation
    # Second pose: a different action, so the pose can't come from the cache -- but the reference already can, so only one more call
    assert calls["generate"] == 3
    assert "alice" in reference_cache


def test_reference_image_passed_through_to_generate_image():
    """
    Verifies that the reference image actually reaches the pose generation call, rather than being generated and discarded.

    The reference generation itself has no reference image; the pose generation has exactly one.
    """
    received: list[list[bytes] | None] = []

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Records the reference images it was given and returns a solid red image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images. Defaults to None.

        Returns:
            bytes - Solid red image file (in bytes).
        """
        received.append(reference_images)
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        """
        Returns a successful cutout, whatever the input.

        Arguments:
            raw_bytes: bytes - Raw generated image (ignored).

        Returns:
            bytes - Cutout image file (in bytes).
        """
        return _fake_cutout_bytes()

    render_characters(
        regions=[_region()],
        characters=_character(),
        cache={},
        reference_cache={},
        generate_image=fake_generate_image,
        remove_background=fake_remove_background,
    )

    assert len(received) == 2
    assert received[0] is None
    assert received[1] is not None
    assert len(received[1]) == 1


def test_reference_cache_is_separate_from_cutout_cache():
    """
    Verifies that reference images live in their own cache, keyed only by character ID, and never appear in the pose-keyed cutout cache.
    """
    generate_image, remove_background, _ = _make_fakes()
    cutout_cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}

    render_characters(
        regions=[_region()],
        characters=_character(),
        cache=cutout_cache,
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert "alice" in reference_cache
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in cutout_cache
    # The reference cache is keyed purely by character ID; the cutout cache by the (character_id, action, orientation, angle) tuple
    # A bare "alice" key would never collide with, or appear in, the other
    assert list(reference_cache.keys()) == ["alice"]
    assert "alice" not in cutout_cache


def test_second_character_gets_its_own_reference_not_a_shared_one():
    """
    Verifies that each character gets their own reference image, even when both go through the same fake generation.
    """
    generate_image, remove_background, calls = _make_fakes()
    reference_cache: ReferenceImageCache = {}
    characters = {**_character("alice"), **_character("bob")}

    render_characters(
        regions=[_region(character_id="alice")],
        characters=characters,
        cache={},
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_characters(
        regions=[_region(character_id="bob")],
        characters=characters,
        cache={},
        reference_cache=reference_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )

    # Alice: reference + pose
    # Bob: his own reference (a cache miss on his character ID) + his own pose -- nothing shared
    assert calls["generate"] == 4
    assert set(reference_cache.keys()) == {"alice", "bob"}


def _transparent_cutout_bytes() -> bytes:
    """
    Builds a fully transparent image -- what background removal returns when it finds no subject at all.

    Returns:
        bytes - Transparent image file (PNG, in bytes).
    """
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_empty_cutout_is_regenerated_and_never_cached():
    """
    Verifies that an empty cutout is regenerated, and that only the successful attempt is cached.
    """
    generate_image, _, calls = _make_fakes()
    results = iter([_fake_cutout_bytes(),          # Reference: fine
                    _transparent_cutout_bytes(),   # Pose, attempt 1: background removal found nothing
                    _fake_cutout_bytes()])         # Pose, attempt 2: fine

    cache: CutoutCache = {}
    render_characters(regions=[_region()], characters=_character(), cache=cache, reference_cache={},
                      generate_image=generate_image, remove_background=lambda raw: next(results))

    assert calls["generate"] == 3  # Reference + two pose attempts
    assert all(_opaque_fraction(c) > 0 for c in cache.values())


def test_persistently_empty_cutout_is_skipped_and_reported_not_cached():
    """
    Verifies that a character whose cutout stays empty after every attempt is left out, reported as rejected, and never cached.
    """
    generate_image, _, _ = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    rejected: list[str] = []

    render_characters(regions=[_region()], characters=_character(), cache=cache, reference_cache=reference_cache,
                      generate_image=generate_image, remove_background=lambda raw: _transparent_cutout_bytes(),
                      rejected=rejected)

    assert rejected == ["alice"]
    assert cache == {}
    assert reference_cache == {}


def test_render_shot_reports_a_left_out_character_in_its_result():
    """
    Verifies that a character left out of a shot is reported in the render result, which then needs review.
    """
    generate_image, _, _ = _make_fakes()
    shot = _shot(regions=[_region()])

    result = render_shot(shot, _character(), character_cache={}, background_cache={}, reference_cache={},
                         generate_image=generate_image, remove_background=lambda raw: _transparent_cutout_bytes())

    assert result.rejected_character_ids == ("alice",)
    assert result.needs_review is True


def test_render_shot_never_modifies_the_shot_it_is_given():
    """
    Verifies that render_shot leaves the shot untouched, even when a character is left out -- flagging the shot is the caller's job.
    """
    generate_image, _, _ = _make_fakes()
    shot = _shot(regions=[_region()])
    before = shot.model_copy(deep=True)

    render_shot(shot, _character(), character_cache={}, background_cache={}, reference_cache={},
                generate_image=generate_image, remove_background=lambda raw: _transparent_cutout_bytes())

    assert shot == before
    assert shot.needs_review is False


def test_render_shot_with_every_character_rendered_needs_no_review():
    """
    Verifies that a shot where every character rendered reports nothing left out.
    """
    generate_image, remove_background, _ = _make_fakes()

    result = render_shot(_shot(regions=[_region()]), _character(), character_cache={}, background_cache={}, reference_cache={},
                         generate_image=generate_image, remove_background=remove_background)

    assert result.rejected_character_ids == ()
    assert result.needs_review is False
