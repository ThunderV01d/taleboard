import io

import pytest
from PIL import Image

from taleboard.rendering import compositor
from taleboard.rendering.prompts import CAMERA_ANGLE_PHRASES, STYLE_PREFIX
from taleboard.rendering.shot_renderer import BackgroundCache, CutoutCache, _background_cache_key, _canonicalize_orientation, _mirror_horizontally, _to_monochrome, render_background, render_characters, render_shot
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

def _asymmetric_cutout_bytes() -> bytes:
    """Left half red, right half blue, with real alpha -- lets a mirror
    actually be observed (a solid-colour fixture would look identical
    flipped or not).
    """
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for x in range(10):
        for y in range(10):
            color = (200, 30, 30, 255) if x < 5 else (30, 30, 200, 255)
            image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def _make_fakes():
    calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str) -> bytes:
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

def test_canonicalize_right_redirects_to_left_and_flags_mirror():
    orientation, needs_mirror = _canonicalize_orientation(Orientation.RIGHT)
    assert orientation == Orientation.LEFT
    assert needs_mirror is True

@pytest.mark.parametrize(
    "orientation",
    [Orientation.LEFT, Orientation.TOWARDS_CAMERA, Orientation.AWAY_FROM_CAMERA],
)
def test_canonicalize_leaves_other_orientations_unchanged(orientation):
    canonical, needs_mirror = _canonicalize_orientation(orientation)
    assert canonical == orientation
    assert needs_mirror is False
 
 
def test_mirror_horizontally_flips_left_and_right_halves():
    asymmetric = _asymmetric_cutout_bytes()
    result = _mirror_horizontally(asymmetric)
 
    image = Image.open(io.BytesIO(result))
    assert image.getpixel((2, 5)) == (30, 30, 200, 255)  # was red, now blue
    assert image.getpixel((7, 5)) == (200, 30, 30, 255)  # was blue, now red

def test_renders_without_error_for_a_single_region():
    generate_image, remove_background, calls = _make_fakes()

    result = render_characters(
        regions=[_region()],
        characters=_character(),
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert len(result) > 0
    assert calls["generate"] == 1


def test_same_character_action_orientation_only_generates_once():
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(position=PositionCell.MID_LEFT)
    region_b = _region(position=PositionCell.MID_RIGHT)

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 1


def test_different_action_triggers_a_second_generation():
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(action="standing")
    region_b = _region(action="waving")

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 2


def test_different_orientation_triggers_a_second_generation():
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(orientation=Orientation.TOWARDS_CAMERA)
    region_b = _region(orientation=Orientation.LEFT)

    render_characters(
        regions=[region_a, region_b],
        characters=_character(),
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 2


def test_cache_is_reused_across_separate_render_shot_calls():
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    region = _region()
    characters = _character()

    render_characters(regions=[region], characters=characters, cache=cache,
                generate_image=generate_image, remove_background=remove_background)
    render_characters(regions=[region], characters=characters, cache=cache,
                generate_image=generate_image, remove_background=remove_background)

    assert calls["generate"] == 1


def test_different_character_sharing_a_pose_still_shares_nothing():
    generate_image, remove_background, calls = _make_fakes()
    region_a = _region(character_id="alice")
    region_b = _region(character_id="bob")
    characters = {**_character("alice"), **_character("bob")}

    render_characters(
        regions=[region_a, region_b],
        characters=characters,
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )

    assert calls["generate"] == 2


def test_region_for_unknown_character_raises():
    generate_image, remove_background, _ = _make_fakes()

    with pytest.raises(KeyError):
        render_characters(
            regions=[_region(character_id="nobody")],
            characters=_character("alice"),
            cache={},
            generate_image=generate_image,
            remove_background=remove_background,
        )

def test_remove_background_receives_the_raw_coloured_generation():
    """Confirms the pipeline ordering: generate -> remove_background -> strip colour, not generate -> strip colour -> remove_background."""
    received: dict[str, bytes] = {}
 
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def spying_remove_background(raw_bytes: bytes) -> bytes:
        received["raw_bytes"] = raw_bytes
        return _fake_cutout_bytes()
 
    render_characters(
        regions=[_region()],
        characters=_character(),
        cache={},
        generate_image=fake_generate_image,
        remove_background=spying_remove_background,
    )
 
    image = Image.open(io.BytesIO(received["raw_bytes"])).convert("RGB")
    assert image.getpixel((5, 5)) == (200, 30, 30)
 
def test_right_orientation_reuses_a_cached_left_generation():
    """The actual point of mirroring: a RIGHT region should never trigger its own generation call if the matching LEFT pose is already cached."""
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    characters = _character()
 
    render_characters(
        regions=[_region(orientation=Orientation.LEFT)],
        characters=characters,
        cache=cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)],
        characters=characters,
        cache=cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert calls["generate"] == 1
 
 
def test_right_orientation_alone_still_only_generates_once():
    """A RIGHT region with nothing cached yet should generate the LEFT pose (not a real RIGHT generation) and derive its own cutout by mirroring -- still exactly one generation call.
    """
    generate_image, remove_background, calls = _make_fakes()
 
    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)],
        characters=_character(),
        cache={},
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert calls["generate"] == 1
 
 
def test_right_orientation_is_never_used_as_a_cache_key():
    """Whatever gets cached, it's always under the canonical LEFT key -- nothing should ever be stored keyed by RIGHT."""
    generate_image, remove_background, _ = _make_fakes()
    cache: CutoutCache = {}
 
    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)],
        characters=_character(),
        cache=cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.RIGHT.value, CameraAngle.EYE_LEVEL.value) not in cache
 
 
def test_right_orientation_output_is_the_mirror_of_left():
    """Black-box confirmation that render_shot actually flips the cutout for a RIGHT region: its output should be byte-for-byte what you'd get from manually mirroring the cached LEFT cutout and compositing that -- using an asymmetric fake so a mirror is actually observable (a solid-colour fake would pass even with no mirroring at all)."""
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _asymmetric_cutout_bytes()
 
    cache: CutoutCache = {}
 
    render_characters(
        regions=[_region(character_id="alice", orientation=Orientation.LEFT)],
        characters=_character("alice"),
        cache=cache,
        generate_image=fake_generate_image,
        remove_background=fake_remove_background,
    )
    left_cutout = cache[("alice", "standing", Orientation.LEFT.value, CameraAngle.EYE_LEVEL.value)]
 
    bob_region = _region(character_id="bob", orientation=Orientation.RIGHT)
    right_result = render_characters(
        regions=[bob_region],
        characters=_character("bob"),
        cache=cache,
        generate_image=fake_generate_image,
        remove_background=fake_remove_background,
    )
 
    expected_mirrored_cutout = _mirror_horizontally(left_cutout)
    expected_composite = compositor.compose_shot([bob_region], {"bob": expected_mirrored_cutout})
 
    assert right_result == expected_composite


def test_cached_cutout_is_monochrome():
    generate_image, remove_background, _ = _make_fakes()
    cache: CutoutCache = {}
 
    render_characters(
        regions=[_region()],
        characters=_character(),
        cache=cache,
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
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in cache
 
 
def test_different_camera_angle_triggers_a_second_generation():
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    region = _region()
    characters = _character()
 
    render_characters(
        regions=[region], characters=characters, cache=cache, angle=CameraAngle.EYE_LEVEL,
        generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[region], characters=characters, cache=cache, angle=CameraAngle.LOW,
        generate_image=generate_image, remove_background=remove_background,
    )
 
    assert calls["generate"] == 2
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in cache
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.LOW.value) in cache
 
 
def test_same_camera_angle_reuses_the_cache():
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    region = _region()
    characters = _character()
 
    render_characters(
        regions=[region], characters=characters, cache=cache, angle=CameraAngle.HIGH,
        generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[region], characters=characters, cache=cache, angle=CameraAngle.HIGH,
        generate_image=generate_image, remove_background=remove_background,
    )
 
    assert calls["generate"] == 1
 
 
def test_mirrored_left_orientation_still_respects_camera_angle_in_the_cache_key():
    generate_image, remove_background, calls = _make_fakes()
    cache: CutoutCache = {}
    characters = _character()
 
    render_characters(
        regions=[_region(orientation=Orientation.RIGHT)], characters=characters, cache=cache,
        angle=CameraAngle.LOW, generate_image=generate_image, remove_background=remove_background,
    )
    render_characters(
        regions=[_region(orientation=Orientation.LEFT)], characters=characters, cache=cache,
        angle=CameraAngle.LOW, generate_image=generate_image, remove_background=remove_background,
    )
 
    assert calls["generate"] == 1
    assert ("alice", "standing", Orientation.LEFT.value, CameraAngle.LOW.value) in cache

 
def test_render_characters_passes_shot_size_through_to_compositing():
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()
 
    region = _region()
    characters = _character()
 
    wide_result = render_characters(
        regions=[region], characters=characters, cache={}, shot_size=ShotSize.WIDE,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    close_up_result = render_characters(
        regions=[region], characters=characters, cache={}, shot_size=ShotSize.CLOSE_UP,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
 
    assert wide_result != close_up_result

def test_render_characters_background_param_changes_the_output():
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()
 
    background = _solid_color_png((10, 200, 10))
    region = _region()
    characters = _character()
 
    with_background = render_characters(
        regions=[region], characters=characters, cache={}, background=background,
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    without_background = render_characters(
        regions=[region], characters=characters, cache={},
        generate_image=fake_generate_image, remove_background=fake_remove_background,
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
 
    def fake_generate_image(text: str, negative_text: str) -> bytes:
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
        generate_image=generate_image,
        remove_background=lambda raw: raw,
    )
    render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache=background_cache,
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
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert len(result) > 0
    assert calls["generate"] == 2
 
 
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
        generate_image=generate_image,
        remove_background=remove_background,
    )
    render_shot(
        shot=shot,
        characters=_character(),
        character_cache=character_cache,
        background_cache=background_cache,
        generate_image=generate_image,
        remove_background=remove_background,
    )
 
    assert calls["generate"] == 2
    assert ("alice", "standing", Orientation.TOWARDS_CAMERA.value, CameraAngle.EYE_LEVEL.value) in character_cache

def test_render_shot_composites_characters_over_the_rendered_background():
    """A shot with regions no longer composites onto plain white -- a point well outside any character's box should show the rendered background's own colour.
    """
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((60, 120, 180))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()
 
    shot = _shot(regions=[_region()], setting="an empty hallway")
 
    result = render_shot(
        shot=shot,
        characters=_character(),
        character_cache={},
        background_cache={},
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
 
    def spying_generate_image(text: str, negative_text: str) -> bytes:
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
        generate_image=spying_generate_image,
        remove_background=fake_remove_background,
    )

    character_prompt = next(p for p in captured_prompts if p.startswith(STYLE_PREFIX))
    assert CAMERA_ANGLE_PHRASES[CameraAngle.LOW] in character_prompt

def test_render_shot_passes_the_shots_shot_size_to_render_characters():
    """render_shot's dispatcher must forward shot.shot_size too."""
    def fake_generate_image(text: str, negative_text: str) -> bytes:
        return _solid_color_png((200, 30, 30))
 
    def fake_remove_background(raw_bytes: bytes) -> bytes:
        return _fake_cutout_bytes()
 
    wide_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.WIDE)
    close_up_shot = _shot(regions=[_region()], setting="an empty hallway", shot_size=ShotSize.CLOSE_UP)
 
    wide_result = render_shot(
        shot=wide_shot, characters=_character(), character_cache={}, background_cache={},
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )
    close_up_result = render_shot(
        shot=close_up_shot, characters=_character(), character_cache={}, background_cache={},
        generate_image=fake_generate_image, remove_background=fake_remove_background,
    )

    assert wide_result != close_up_result