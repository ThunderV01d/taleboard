import io

import pytest
from PIL import Image

from taleboard.rendering import compositor
from taleboard.rendering.prompts import CAMERA_ANGLE_PHRASES, STYLE_PREFIX
from taleboard.rendering.shot_renderer import BackgroundCache, CutoutCache, ReferenceImageCache, _background_cache_key, _to_monochrome, render_background, render_characters, render_shot
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region, Shot


def _character(char_id: str = "alice") -> dict[str, Character]:
    return {char_id: Character(name=char_id.title(), description="...", colour="#ff0000")}


def _region(
    character_id: str = "alice",
    position: PositionCell = PositionCell.MID_CENTER,
    action: str = "standing",
    orientation: Orientation = Orientation.TOWARDS_CAMERA,
    size: SizeInFrame = SizeInFrame.MEDIUM,
) -> Region:
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
    image = Image.new("RGB", (10, 10), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _fake_cutout_bytes() -> bytes:
    """A minimal real PNG."""
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _make_fakes():
    calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        calls["generate"] += 1
        return _solid_color_png((200, 30, 30))

    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()

    return fake_generate_image, fake_remove_background, calls

def test_to_monochrome_strips_colour_from_a_coloured_image():
    coloured = _solid_color_png((200, 30, 30))  #red
    result = _to_monochrome(coloured)
 
    image = Image.open(io.BytesIO(result)).convert("RGB")
    r, g, b = image.getpixel((5, 5))
    assert r == g == b


def test_to_monochrome_preserves_an_already_grey_image():
    grey = _solid_color_png((128, 128, 128))
    result = _to_monochrome(grey)
 
    image = Image.open(io.BytesIO(result)).convert("RGB")
    assert image.getpixel((5, 5)) == (128, 128, 128)

def test_to_monochrome_preserves_alpha_channel():
    coloured_cutout = _fake_cutout_bytes()
    result = _to_monochrome(coloured_cutout)
 
    image = Image.open(io.BytesIO(result))
    assert image.mode == "RGBA"
    assert image.getpixel((5, 5))[3] == 255  # alpha preserved
 
    transparent = Image.new("RGBA", (10, 10), (200, 30, 30, 0))
    buffer = io.BytesIO()
    transparent.save(buffer, format="PNG")
    result = _to_monochrome(buffer.getvalue())
 
    image = Image.open(io.BytesIO(result))
    assert image.getpixel((5, 5))[3] == 0

def test_renders_without_error_for_a_single_region():
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
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}
    region = _region()
    characters = _character()

    render_characters(regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, generate_image=generate_image, remove_background=remove_background)
    render_characters(regions=[region], characters=characters, cache=cache, reference_cache=reference_cache, generate_image=generate_image, remove_background=remove_background)

    assert calls["generate"] == 2


def test_different_character_sharing_a_pose_still_shares_nothing():
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
    """Confirms the pipeline ordering: generate -> remove_background -> strip colour, not generate -> strip colour -> remove_background."""
    received: dict[str, bytes] = {}
 
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def spying_remove_background(raw_bytes: bytes) -> bytes:
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
 
    # First call: one reference + one real LEFT pose. Second call: the
    # reference is already cached (same character), but RIGHT is its own
    # distinct orientation now -- a cutout-cache miss, so a real second
    # pose generation, not a cache hit.
    assert calls["generate"] == 3
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.RIGHT.value, CameraAngle.EYE_LEVEL.value) in cache
 
 
def test_right_orientation_alone_generates_its_own_real_pose():
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
 
    assert calls["generate"] == 2  # one reference + one real RIGHT pose
    assert ("alice", "standing", Orientation.RIGHT.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value) not in cache

def test_cached_cutout_is_monochrome():
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
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
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
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
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
    """Returns (generate_image, call_counter) for render_background tests
    -- no remove_background here, since a background render has nothing to
    cut out.
    """
    calls = {"generate": 0}
 
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        calls["generate"] += 1
        return _solid_color_png((60, 120, 180))  # deliberately coloured
 
    return fake_generate_image, calls
 
 
def test_render_background_returns_a_nonempty_image():
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
    """A background render is the whole frame, not a subject to isolate --
    there's nothing to cut out, so render_background's signature has no
    remove_background parameter at all. Calling it with one is a TypeError,
    not a silently-ignored extra argument."""
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
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}
 
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
 
    assert calls["generate"] == 1
 
 
def test_render_background_different_setting_triggers_a_second_generation():
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}
 
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("a crowded train platform", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
 
    assert calls["generate"] == 2
 
 
def test_render_background_different_shot_size_triggers_a_second_generation():
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}
 
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.WIDE, CameraAngle.EYE_LEVEL, cache, generate_image)
 
    assert calls["generate"] == 2
 
 
def test_render_background_different_angle_triggers_a_second_generation():
    generate_image, calls = _make_background_fakes()
    cache: BackgroundCache = {}
 
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, cache, generate_image)
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW, cache, generate_image)
 
    assert calls["generate"] == 2
 
 
def test_background_cache_key_matches_the_stored_cache_entry():
    generate_image, _ = _make_background_fakes()
    cache: BackgroundCache = {}
 
    render_background("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW, cache, generate_image)
 
    key = _background_cache_key("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW)
    assert key == ("an empty hallway", "medium", "low")
    assert key in cache
 
def test_render_shot_with_no_regions_renders_a_background():
    """An establishing shot / object-insert shot has no character regions
    at all -- render_shot should dispatch straight to render_background and
    never touch character generation or compositing.
    """
    character_calls = {"generate": 0}
    background_calls = {"generate": 0}
 
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        # Shared fake for both paths -- whichever one actually gets called
        # bumps its own counter via closures below instead, so keep this
        # one trivial.
        return _solid_color_png((60, 120, 180))
 
    def spying_remove_background(raw_bytes: bytes) -> bytes:
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
 
    assert len(result) > 0
    # remove_background is only ever called on the character-compositing
    # path -- a background-only shot should never reach it.
    assert character_calls["generate"] == 0
 
 
def test_render_shot_with_no_regions_uses_the_background_cache():
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
    """render_shot now always renders a background too -- a shot with regions costs one background generation plus one per distinct character pose, not just the character generations alone."""
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
 
    assert len(result) > 0
    assert calls["generate"] == 3
 
 
def test_render_shot_with_regions_reuses_both_caches_across_repeated_calls():
    """A second render_shot call with the same shot (same setting/shot_size/angle, same regions) should hit both the background cache and the character cache -- no new generation calls at all, not just the character side."""
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
    """A shot with regions no longer composites onto plain white -- a point well outside any character's box should show the rendered background's own colour.
    """
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        return _solid_color_png((60, 120, 180))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
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
    
    result_pixel = Image.open(io.BytesIO(result)).convert("RGB").getpixel((10, 10))
    assert result_pixel != (255, 255, 255)
    assert result_pixel == expected_background_pixel

def test_render_shot_passes_the_shots_angle_to_render_characters():
    """render_shot's dispatcher must forward shot.angle, not just shot.regions/characters"""
    captured_prompts: list[str] = []
 
    def spying_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        captured_prompts.append(text)
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
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
    """render_shot's dispatcher must forward shot.shot_size too."""
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()
 
    wide_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.WIDE)
    close_up_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.CLOSE_UP)
 
    wide_result = render_shot(
        shot=wide_shot, characters=_character(), character_cache={}, background_cache={}, reference_cache={}, generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    close_up_result = render_shot(
        shot=close_up_shot, characters=_character(), character_cache={}, background_cache={}, reference_cache={},  generate_image=fake_generate_image, remove_background=fake_remove_background,
    )

    assert wide_result != close_up_result


def test_reference_image_generated_once_per_character_and_reused_across_poses():
    """A character's reference image is generated on its first pose, then
    reused (not regenerated) for every later pose -- that's the entire
    point of caching it separately from the pose itself.
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
 
    # First pose: one reference + one pose generation. Second pose (a
    # different action, so the pose itself can't be cached): the
    # reference is already in reference_cache, so only one more call.
    assert calls["generate"] == 3
    assert "alice" in reference_cache
 
 
def test_reference_image_passed_through_to_generate_image():
    """The character's reference bytes should actually reach
    generate_image's reference_images kwarg on the pose-generation call,
    not just get generated and discarded.
    """
    received: list[list[bytes] | None] = []
 
    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        received.append(reference_images)
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
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
    """A character's reference image lives in its own cache, keyed only
    by character_id -- it must never show up in (and never be confused
    with) the pose-keyed CutoutCache.
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
    # The reference cache is keyed purely by character_id; the cutout
    # cache by the (character_id, action, orientation, angle) tuple -- a
    # bare "alice" key would never collide with or appear in the other.
    assert list(reference_cache.keys()) == ["alice"]
    assert "alice" not in cutout_cache
 
 
def test_second_character_gets_its_own_reference_not_a_shared_one():
    """Alice's reference image must never be reused for Bob -- each
    character_id gets its own independently-generated reference, even
    though both go through the exact same fake generate_image/remove_background.
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
 
    # Alice: reference + pose. Bob: a separate reference (cache miss on
    # his own character_id) + his own pose. Nothing shared.
    assert calls["generate"] == 4
    assert set(reference_cache.keys()) == {"alice", "bob"}