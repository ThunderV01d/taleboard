"""
Integration tests for shot rendering against real Together AI.

Makes real (paid) generation calls and needs a Together AI API key. Run with: pytest -m integration

Each test renders a shot twice -- the second render confirms the caches work against the real API, not just against fakes.

Attributes:
    OUTPUT_DIR: Path - Folder the rendered shots are written to, for inspection by eye.
"""
from pathlib import Path

import pytest

from taleboard.rendering import together_caller
from taleboard.rendering.shot_renderer import BackgroundCache, CutoutCache, ReferenceImageCache, render_characters, render_shot
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region, Shot

OUTPUT_DIR = Path(__file__).parent / "output"

def _test_characters() -> dict[str, Character]:
    """
    Builds a two-character cast (Alice and Bob), with visual descriptions.

    Returns:
        dict[str,Character] - Mapping of character IDs ("alice", "bob") to characters.
    """
    return {
        "alice": Character(
            name="Alice",
            description="A young woman with short red hair, wearing a green coat."
        ),
        "bob": Character(
            name="Bob",
            description="A tall man with a beard, wearing a jacket."
        ),
    }


def _test_regions() -> list[Region]:
    """
    Builds two large, standing regions, with Alice and Bob facing each other at the bottom of the frame.

    Returns:
        list[Region] - Alice's region, then Bob's.
    """
    return [
        Region(
            character_id="alice",
            position=PositionCell.BOTTOM_LEFT,
            size=SizeInFrame.LARGE,
            orientation=Orientation.RIGHT,  # Facing right, ie:- towards Bob
            action="standing",
        ),
        Region(
            character_id="bob",
            position=PositionCell.BOTTOM_RIGHT,
            size=SizeInFrame.LARGE,
            orientation=Orientation.LEFT,  # Facing left, ie:- towards Alice
            action="standing",
        ),
    ]


@pytest.mark.integration
def test_render_shot_end_to_end_and_cache_reuse_against_real_services():
    """
    Verifies that a real two-character shot renders through generation, background removal and compositing, and that a repeat render is served entirely from the caches.

    The first render (2 references + 2 poses) is written to disk for inspection by eye. The second render, with the same regions and caches, must make no further generation calls.
    """
    call_count = 0
    real_generate = together_caller.generate_character_image

    def counting_generate(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Counts the call and passes it through to the real character generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.
            reference_images: list[bytes] - Reference images. Defaults to None.

        Returns:
            bytes - Generated character image file (in bytes).
        """
        nonlocal call_count
        call_count += 1
        return real_generate(text, negative_text, reference_images=reference_images)

    characters = _test_characters()
    regions = _test_regions()
    cache: CutoutCache = {}
    reference_cache: ReferenceImageCache = {}

    first_result = render_characters(
        regions=regions,
        characters=characters,
        cache=cache,
        reference_cache=reference_cache,
        generate_image=counting_generate,
    )
    assert len(first_result) > 0
    assert call_count == 4

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "composited_shot.png").write_bytes(first_result)

    second_result = render_characters(
        regions=regions,
        characters=characters,
        cache=cache,
        reference_cache=reference_cache,
        generate_image=counting_generate,
    )
    assert call_count == 4
    assert second_result == first_result

@pytest.mark.integration
def test_render_shot_background_only_end_to_end_and_cache_reuse_against_real_services(monkeypatch):
    """
    Verifies that a shot with no regions renders as a real background only, and that a repeat render is served from the background cache.

    This is the establishing or object-insert shot case -- nothing to composite. WIDE and LOW are deliberately not the defaults, so this also confirms the shot size and angle actually reach the background prompt for real.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the call-counting background generation.
    """
    call_count = 0
    real_generate_background = together_caller.generate_background_image

    def counting_generate_background(text: str, negative_text: str) -> bytes:
        """
        Counts the call and passes it through to the real background generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.

        Returns:
            bytes - Generated background image file (in bytes).
        """
        nonlocal call_count
        call_count += 1
        return real_generate_background(text, negative_text)

    monkeypatch.setattr(together_caller, "generate_background_image", counting_generate_background)

    shot = Shot(
        description="An empty alley at night.",
        setting="a narrow city alley at night, wet cobblestones, a single flickering streetlamp",
        regions=[],
        paragraph_index=0,
        shot_size=ShotSize.WIDE,
        angle=CameraAngle.LOW,
        duration_s=2.0,
    )
    background_cache: BackgroundCache = {}

    first_result = render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache=background_cache,
        reference_cache={},
    )
    assert len(first_result) > 0
    assert call_count == 1  # One background render, no character calls at all

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "background_only_shot.png").write_bytes(first_result)

    second_result = render_shot(
        shot=shot,
        characters={},
        character_cache={},
        background_cache=background_cache,
        reference_cache={},
    )
    assert call_count == 1  # Unchanged: reused from the background cache
    assert second_result == first_result

@pytest.mark.integration
def test_render_shot_with_regions_composites_over_a_real_background_end_to_end(monkeypatch):
    """
    Verifies that a shot with regions, rendered through render_shot, comes back as real characters composited over a real background.

    The first render costs 1 background + 2 references + 2 poses, and the repeat render must be served entirely from the caches.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the call-counting character and background generation.
    """
    call_count = 0
    real_generate_character = together_caller.generate_character_image
    real_generate_background = together_caller.generate_background_image

    def counting_generate_character(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Counts the call and passes it through to the real character generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.
            reference_images: list[bytes] - Reference images. Defaults to None.

        Returns:
            bytes - Generated character image file (in bytes).
        """
        nonlocal call_count
        call_count += 1
        return real_generate_character(text, negative_text, reference_images=reference_images)

    def counting_generate_background(text: str, negative_text: str) -> bytes:
        """
        Counts the call and passes it through to the real background generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.

        Returns:
            bytes - Generated background image file (in bytes).
        """
        nonlocal call_count
        call_count += 1
        return real_generate_background(text, negative_text)

    monkeypatch.setattr(together_caller, "generate_character_image", counting_generate_character)
    monkeypatch.setattr(together_caller, "generate_background_image", counting_generate_background)

    shot = Shot(
        description="Alice and Bob talking in a dim hallway.",
        setting="a dim narrow hallway with peeling wallpaper and a single overhead bulb",
        regions=_test_regions(),
        paragraph_index=0,
        shot_size=ShotSize.CLOSE_UP,
        angle=CameraAngle.HIGH,
        duration_s=2.0,
    )
    characters = _test_characters()
    character_cache: CutoutCache = {}
    background_cache: BackgroundCache = {}
    reference_cache: ReferenceImageCache = {}

    first_result = render_shot(
        shot=shot,
        characters=characters,
        character_cache=character_cache,
        background_cache=background_cache,
        reference_cache=reference_cache,
    )
    assert len(first_result) > 0
    assert call_count == 5

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "composited_shot_with_background.png").write_bytes(first_result)

    second_result = render_shot(
        shot=shot,
        characters=characters,
        character_cache=character_cache,
        background_cache=background_cache,
        reference_cache=reference_cache,
    )
    assert call_count == 5
    assert second_result == first_result
