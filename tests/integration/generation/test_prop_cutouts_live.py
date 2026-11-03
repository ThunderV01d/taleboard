"""
Integration test comparing the two background removals against real Together AI: the isnet-anime model (background_removal) and flood-filling the white background (cutouts.remove_white_background).

Props first: the four from the live story whose layers the model left see-through, plus four new ones -- one with a hole in it (a mug's handle), which the flood fill can't reach. Then characters, which the model cuts out: three front references and a pose with hands on hips (white enclosed between arm and body is the flood fill's weak spot), to see whether the flood fill would serve them too.

Each subject is drawn exactly as the engine draws it, and written to a sheet -- raw | model | flood fill -- with each cutout labelled with the two measures generate_cutout rejects on. Raw images are kept on disk, so a rerun only pays for subjects it hasn't drawn yet: the first run is 8 new generations (the four story props were drawn last time), about $0.12. Needs a Together AI API key. Run with: pytest tests/integration/generation/test_prop_cutouts_live.py -m integration -s

Nothing is asserted about the cutouts -- this is for looking at.

Attributes:
    OUTPUT_DIR: Path - Folder the images and sheets are written to (git-ignored).
    PROPS: list[Prop] - Props to draw: the live story's four (with the descriptions it gave them), then four new ones.
    CHARACTERS: list[tuple[Character,str]] - Characters to draw, each with an action ("" for their front reference).
"""
import io
from pathlib import Path
from typing import Callable

import pytest
from PIL import Image, ImageDraw

from taleboard.generation import prompts
from taleboard.generation.background_removal import remove_background
from taleboard.generation.cutouts import MAX_PARTIAL_FRACTION, MIN_OPAQUE_FRACTION, opaque_fraction, partial_fraction, remove_white_background
from taleboard.generation.together_caller import generate_background_image, generate_character_image
from taleboard.schema.enums import Orientation
from taleboard.schema.storyboard import Character, Prop

OUTPUT_DIR = Path(__file__).parent / "output" / "props"

PROPS = [
    Prop(id="smartphone", name="smartphone", description="A modern black phone with a glowing screen."),
    Prop(id="hospital_clipboard", name="hospital clipboard", description="A medical clipboard with papers attached."),
    Prop(id="photograph", name="photograph", description="A color photograph with a birthday cake and handwriting on the back."),
    Prop(id="red_balloon", name="red balloon", description="A bright red inflated balloon."),
    Prop(id="letter", name="letter", description="A folded letter of cream paper."),
    Prop(id="lantern", name="lantern", description="An old brass storm lantern with a glass chimney and a wire handle."),
    Prop(id="mug", name="mug", description="A plain ceramic coffee mug with a round handle."),
    Prop(id="umbrella", name="umbrella", description="A closed black umbrella with a curved wooden handle."),
]

CHARACTERS = [
    (Character(id="marcus", name="Marcus", description="A man in his mid-forties with dark hair graying at the temples, wearing a dress shirt and slacks."), ""),
    (Character(id="mara", name="Mara", description="A woman in her mid-thirties with long dark hair tied back, wearing a practical wool sweater over sturdy trousers."), ""),
    (Character(id="nurse", name="Nurse", description="A nurse in her twenties with short fair hair, wearing a plain white uniform and white shoes."), ""),
    (Character(id="marcus", name="Marcus", description="A man in his mid-forties with dark hair graying at the temples, wearing a dress shirt and slacks."), "standing with both hands on hips, elbows out"),
]


def _raw(name: str, draw: Callable[[], bytes]) -> bytes:
    """
    A subject's raw generation -- from disk if it was drawn before, so reruns cost nothing.
    """
    path = OUTPUT_DIR / f"{name}-raw.png"
    if not path.exists():
        path.write_bytes(draw())
    return path.read_bytes()


def _verdict(cutout: bytes) -> str:
    opaque, partial = opaque_fraction(cutout), partial_fraction(cutout)
    kept = opaque >= MIN_OPAQUE_FRACTION and partial <= MAX_PARTIAL_FRACTION
    return f"{opaque:.0%} solid, {partial:.0%} partial: {'KEPT' if kept else 'REJECTED'}"


def _tile(image_bytes: bytes, label: str, size: tuple[int, int]) -> Image.Image:
    """
    An image shrunk onto a light grey tile (so a cutout's transparency shows), with a label underneath.
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    image.thumbnail(size)
    tile = Image.new("RGB", (size[0], size[1] + 24), (200, 200, 200))
    tile.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2), image)
    ImageDraw.Draw(tile).text((4, size[1] + 6), label, fill=(0, 0, 0))
    return tile


def _sheet(rows: list[tuple[str, bytes]], size: tuple[int, int], path: Path) -> None:
    """
    Writes a sheet of rows -- raw | model | flood fill -- printing each cutout's verdict.
    """
    tiles = []
    for name, raw in rows:
        model, flood = remove_background(raw), remove_white_background(raw)
        print(f"{name}:  model {_verdict(model)}  |  flood fill {_verdict(flood)}")
        tiles.append([_tile(raw, f"{name} -- raw", size), _tile(model, f"model: {_verdict(model)}", size), _tile(flood, f"flood fill: {_verdict(flood)}", size)])
    width, height = tiles[0][0].size
    sheet = Image.new("RGB", (3 * width, len(tiles) * height), (255, 255, 255))
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            sheet.paste(tile, (x * width, y * height))
    sheet.save(path)
    print(f"Sheet: {path}")


@pytest.mark.integration
def test_the_model_and_the_flood_fill_on_props_and_characters():
    """
    Draws every prop and character, and writes one sheet for each kind comparing the two background removals.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    props = [(p.id, _raw(p.id, lambda p=p: generate_background_image(prompts.prop_prompt(p, Orientation.TOWARDS_CAMERA)))) for p in PROPS]
    _sheet(props, (300, 300), OUTPUT_DIR / "props_compared.png")

    characters = []
    for character, action in CHARACTERS:
        name = f"{character.id}-{'pose' if action else 'front'}"
        characters.append((name, _raw(name, lambda c=character, a=action: generate_character_image(prompts.character_prompt(c, Orientation.TOWARDS_CAMERA, a) if a else prompts.character_prompt(c, Orientation.TOWARDS_CAMERA)))))
    _sheet(characters, (160, 512), OUTPUT_DIR / "characters_compared.png")
