"""
Integration tests for the v0.2.0 generation engine against real Together AI.

The first test generates one location in all four facings plus a night-and-rain lighting edit, one character (front and left references and a pose), and one prop -- 9 real (paid) generations, about $0.14. The second tries candidate rewordings of the prompts the first showed need work, beside the current ones -- 8 more, about $0.12. The third tries facings drawn from a description of each side (a common description plus one wall) on an office, a harbour quay and a kitchen, then runs one reverse view through the rest of the background chain, and lights an interior and an exterior with wording that knows which it is -- 13 more, about $0.20. Needs a Together AI API key. Run with: pytest tests/integration/generation -m integration -s

Images are kept on disk under their content-addressed keys, so a rerun reuses every image already made and costs nothing; delete the output folder to generate them again. The real point of these tests is the labelled contact sheets they write, for judging the prompts by eye -- the asserts only check that each step produced an image.

Attributes:
    OUTPUT_DIR: Path - Folder the images and contact sheets are written to (git-ignored).
    COST_PER_IMAGE: float - Together AI's price for one FLUX.2-dev image, in US dollars.
"""
import io
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from taleboard.generation import prompts
from taleboard.generation.engine import Generator
from taleboard.generation.cutouts import to_monochrome
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.storyboard import Character, Location, Prop

OUTPUT_DIR = Path(__file__).parent / "output" / "engine"
COST_PER_IMAGE = 0.0154


class DiskStore:
    """
    The engine's store on local disk: each S3 key becomes a file path under a folder. Counts the images it has to generate.

    Attributes:
        root: Path - The folder.
        generated: int - Images generated (not found) so far -- monochrome copies aren't counted, as they cost nothing.
    """
    def __init__(self, root: Path):
        self.root = root
        self.generated = 0

    def get_image(self, s3_key: str) -> bytes | None:
        path = self.root / s3_key
        return path.read_bytes() if path.exists() else None

    def put_image(self, s3_key: str, image: bytes) -> None:
        path = self.root / s3_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
        if "/monochrome/" not in s3_key:
            self.generated += 1

    def save_entry_image(self, project_id: str, entry, slot: str) -> None:
        pass  # The entries only live for each test


def _lighthouse() -> Location:
    return Location(
        id="lighthouse", name="Lamp room",
        description="the round lamp room at the top of a lighthouse: a huge glass lens in the middle on a brass pedestal, "
                    "tall windows all the way round, an iron railing, a narrow spiral staircase coming up through the floor",
    )


def _office() -> Location:
    return Location(
        id="office", name="Office",
        description="a small wood-panelled office: a large desk with a black telephone, a leather chair behind the desk, a filing "
                    "cabinet, a corkboard on the left wall, a two-pane window in the back wall, and a door with a coat stand beside "
                    "it in the front wall",
    )


def _mara() -> Character:
    return Character(id="mara", name="Mara", description="a woman in her sixties, short grey hair, heavy oilskin coat, rubber boots")


def _contact_sheet(images: list[tuple[str, bytes | None]], cell: int = 360, columns: int = 3) -> Image.Image:
    """
    Lays images out in a labelled grid, each fitted into a square cell on grey (so cutouts' transparency shows). A cell with no image is left empty.

    Arguments:
        images: list[tuple[str,bytes|None]] - Each image's label and PNG bytes.
        cell: int - Width and height of each cell (in pixels). Defaults to 360.
        columns: int - Cells per row. Defaults to 3.

    Returns:
        Image.Image - The contact sheet.
    """
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell, rows * (cell + 24)), (150, 150, 150))
    draw = ImageDraw.Draw(sheet)
    for i, (label, data) in enumerate(images):
        if data is None:
            continue
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        image.thumbnail((cell - 8, cell - 8))
        x, y = (i % columns) * cell, (i // columns) * (cell + 24)
        sheet.paste(image, (x + (cell - image.width) // 2, y + 24 + (cell - image.height) // 2), image)
        draw.text((x + 6, y + 6), label, fill=(0, 0, 0))
    return sheet


def _run(store: DiskStore, steps: list, sheet_name: str) -> list[tuple[str, bytes | None]]:
    """
    Runs each step -- a label, and a function returning an S3 key (or None, for an empty cell) -- printing how long each took, then writes the contact sheet.

    Arguments:
        store: DiskStore - Where the images are.
        steps: list - The steps, in contact sheet order.
        sheet_name: str - File name of the contact sheet, in OUTPUT_DIR.

    Returns:
        list[tuple[str,bytes|None]] - Each step's label and image.
    """
    results = []
    for label, make in steps:
        if make is None:
            results.append((label, None))
            continue
        started = time.monotonic()
        key = make()
        print(f"{label:32} {time.monotonic() - started:5.1f}s  {key}")
        results.append((label, store.get_image(key)))
    sheet = OUTPUT_DIR / sheet_name
    _contact_sheet(results).save(sheet)
    print(f"\nNew generations: {store.generated} (about ${store.generated * COST_PER_IMAGE:.2f}). Contact sheet: {sheet}")
    return results


@pytest.mark.integration
def test_the_engine_draws_facings_lighting_characters_and_props():
    """
    Runs every new kind of generation once against real Together AI, and writes a contact sheet to judge them by:

    - the east, south and west plates turn the camera from the north one, and still show the same room;
    - the night-and-rain edit keeps the view, adding hatching and rain only through the windows (the room is indoors);
    - the left reference is still recognisably the front one's character;
    - the gripping pose has the hand shaped around a handle, but empty;
    - the lantern is drawn alone, with no hand holding it.
    """
    store = DiskStore(OUTPUT_DIR)
    generator = Generator("trial", store)
    lighthouse, mara = _lighthouse(), _mara()
    lantern = Prop(id="lantern", name="Lantern", description="an old brass storm lantern with a glass chimney and a wire handle")

    steps = [
        ("north plate", lambda: generator.plate(lighthouse, Facing.NORTH)),
        ("east plate", lambda: generator.plate(lighthouse, Facing.EAST)),
        ("south plate", lambda: generator.plate(lighthouse, Facing.SOUTH)),
        ("west plate", lambda: generator.plate(lighthouse, Facing.WEST)),
        ("north, night + rain", lambda: generator.background(
            lighthouse, Facing.NORTH, ShotSize.WIDE, CameraAngle.EYE_LEVEL, "", TimeOfDay.NIGHT, Atmosphere.RAINY,
        )),
        ("Mara front reference", lambda: generator.character_reference(mara, Orientation.TOWARDS_CAMERA)),
        ("Mara left reference", lambda: generator.character_reference(mara, Orientation.LEFT)),
        ("Mara pose: gripping", lambda: generator.character(
            mara, Orientation.LEFT, "one arm raised, hand held up at shoulder height as if gripping a handle",
        )),
        ("lantern", lambda: generator.prop(lantern, Orientation.TOWARDS_CAMERA)),
    ]

    results = _run(store, steps, "contact_sheet.png")

    assert all(image for _, image in results)


# --- Candidate rewordings (round 2) ---------------------------------------------------------------------------------

# Facing, variant A: no image 1 at all -- the camera is free to move, but the room may not match
TURN_AROUND_TEXT_ONLY = "wide shot at eye level, the view from the opposite side of the place, looking back the other way, empty, with nobody in it, "

# Facing, variant B: image 1 kept, but only for what the place is made of -- with the new camera position spelled out
TURN_AROUND_FROM_REFERENCE = (
    "a completely different view of the place in image 1: the camera now stands at the far side of the place and looks back "
    "towards where image 1 was taken from, so the side of the place that was behind the camera in image 1 fills the frame, and "
    "what was at the back of image 1 is now behind the camera, out of view. Use image 1 only for the place's materials, "
    "furnishings and drawing style -- do not copy its composition. Wide shot at eye level, empty, with nobody in it, "
)

LIGHTING_EDIT = (
    "the same view of the place in image 1, from the same camera position and with the same framing, with everything in it "
    "unchanged, changed only in its light and weather. Weather happens only outdoors: rain or snow is seen only in the sky and "
    "outside, and never falls inside a room, where everything stays dry: "
)
NIGHT = "at night, a dark night sky, the whole scene in deep cross-hatched shadow, "
RAIN = "rain falling outside, fine diagonal rain streaks in the sky"

NEUTRAL_POSE = "standing, arms relaxed at the sides, both hands open and empty, holding nothing"
GRIPPING_POSE = "one arm raised to shoulder height with the fingers curled closed around nothing, the other hand open and empty at the side"


@pytest.mark.integration
def test_candidate_prompts_beside_the_current_ones():
    """
    Tries rewordings of the prompts the first test showed need work, each beside the current version (reused from the first test's images, so free):

    - the south plate of a round room and of a rectangular office, drawn from text alone (A) and from the north plate with the new camera position spelled out (B) -- in the office, south should show the door and coat stand, not the window;
    - night and rain, with no rain indoors and a dark sky rather than white windows;
    - a left reference with both hands open and empty (the first one held a phone), and a grip with the fingers curled around nothing.
    """
    store = DiskStore(OUTPUT_DIR)
    generator = Generator("trial", store)
    lighthouse, office, mara = _lighthouse(), _office(), _mara()

    def south(location: Location, variant: str) -> str:
        if variant == "A":
            return generator._background("plate", prompts.BACKGROUND_STYLE + TURN_AROUND_TEXT_ONLY + location.description, [])
        return generator._background(
            "plate", prompts.BACKGROUND_STYLE + TURN_AROUND_FROM_REFERENCE + location.description,
            [generator.plate(location, Facing.NORTH)],
        )

    def left_reference() -> str:
        text = prompts.CHARACTER_STYLE + prompts.ORIENTATION_PHRASES[Orientation.LEFT] + f"{mara.description}, {NEUTRAL_POSE}"
        front = generator.character_reference(mara, Orientation.TOWARDS_CAMERA)
        return generator._derive("reference", text, [front], lambda images: generator._cutout(text, generator._generate_character, images))

    def gripping() -> str:
        text = prompts.CHARACTER_STYLE + prompts.ORIENTATION_PHRASES[Orientation.LEFT] + f"{mara.description}, {GRIPPING_POSE}"
        return generator._derive(
            "pose", text, [left_reference()],
            lambda images: to_monochrome(generator._cutout(text, generator._generate_character, images)),
        )

    steps = [
        ("lighthouse north (current)", lambda: generator.plate(lighthouse, Facing.NORTH)),
        ("lighthouse south A: text only", lambda: south(lighthouse, "A")),
        ("lighthouse south B: from north", lambda: south(lighthouse, "B")),
        ("office north", lambda: generator.plate(office, Facing.NORTH)),
        ("office south A: text only", lambda: south(office, "A")),
        ("office south B: from north", lambda: south(office, "B")),
        ("night + rain (current)", lambda: generator.background(
            lighthouse, Facing.NORTH, ShotSize.WIDE, CameraAngle.EYE_LEVEL, "", TimeOfDay.NIGHT, Atmosphere.RAINY,
        )),
        ("night + rain (new)", lambda: generator._background(
            "lighting", "Storyboard panel, " + prompts.STYLE + "filling full frame, " + LIGHTING_EDIT + NIGHT + RAIN,
            [generator.plate(lighthouse, Facing.NORTH)],
        )),
        ("", None),
        ("left reference (current)", lambda: generator.character_reference(mara, Orientation.LEFT)),
        ("left reference (new)", left_reference),
        ("gripping (new)", gripping),
    ]

    results = _run(store, steps, "candidates_sheet.png")

    assert all(image for label, image in results if label)


# --- Facings from their own descriptions (round 4) -------------------------------------------------------------------

# Each place is a description of what's common to all of it (materials, size), plus one line per side saying only what's on that side
OFFICE_COMMON = "a small wood-panelled office about four metres across, plain wooden floorboards, quiet and plain"
OFFICE_SIDES = {
    Facing.NORTH: "the back wall of the office: a two-pane window, with a large desk in front of it holding a black telephone, and a leather chair behind the desk",
    Facing.EAST: "a side wall of the office: a metal filing cabinet and a tall bookcase full of box files",
    Facing.SOUTH: "the front wall of the office: a door with a coat stand beside it",
    Facing.WEST: "the other side wall of the office: a corkboard covered in pinned notes, above a small side table",
}
QUAY_COMMON = "a small stone harbour quay in a fishing village, cobbled ground, iron bollards along the quay"
QUAY_SIDES = {
    Facing.NORTH: "the harbour: the edge of the quay, with small fishing boats moored in the water and the open sea beyond",
    Facing.SOUTH: "the row of small whitewashed fishermen's cottages facing the quay, with nets drying outside their doors",
}
KITCHEN_COMMON = "a small farmhouse cottage kitchen with whitewashed stone walls, low ceiling beams and a flagstone floor"
KITCHEN_SIDES = {
    Facing.NORTH: "one end of the kitchen: a cast-iron range in a wide hearth, with a scrubbed wooden table in front of it",
    Facing.SOUTH: "the other end of the kitchen: a tall wooden dresser with plates on its shelves, and a back door beside it",
}


def _side_prompt(common: str, side: str, indoors: bool, from_image_1: bool) -> str:
    """
    The prompt for one side of a place: only what's common to it and what's on that side -- for a facing other than north, with the north plate as image 1 for materials and style only.
    """
    text = prompts.BACKGROUND_STYLE + f"wide shot at eye level, empty, with nobody in it, {'inside' if indoors else 'at'} {common}, looking straight at {side}."
    if from_image_1:
        what = "the room's materials, wall panelling, proportions" if indoors else "the place's materials, buildings, ground"
        text += f" Use image 1 only for {what} and drawing style -- do not copy its composition or anything in it."
    return text


# Lighting that knows whether a place is inside or out: indoors names no sky and no weather (FLUX draws whatever a prompt
# names, "not" or "only" notwithstanding), just the light and mood it brings; outdoors gets the sky and the weather itself
LIGHTING_TIME = {
    "interior": {
        TimeOfDay.DAWN: "at dawn, low pale light from one side, long soft shadows drawn with light hatching, ",
        TimeOfDay.DAY: "",
        TimeOfDay.DUSK: "at dusk, fading warm light, long shadows drawn with hatching, ",
        TimeOfDay.NIGHT: "at night, dim lamplight, everything in deep cross-hatched shadow, ",
    },
    "exterior": {
        TimeOfDay.DAWN: "at dawn, a pale sky low on one side, long soft shadows drawn with light hatching, ",
        TimeOfDay.DAY: "",
        TimeOfDay.DUSK: "at dusk, a fading sky, long shadows drawn with hatching, ",
        TimeOfDay.NIGHT: "at night, a dark night sky, everything in deep cross-hatched shadow, ",
    },
}
LIGHTING_WEATHER = {
    "interior": {
        Atmosphere.CLEAR: "",
        Atmosphere.OVERCAST: "flat, grey light, no hard shadows, ",
        Atmosphere.RAINY: "dim, grey light, ",
        Atmosphere.FOGGY: "hazy, pale light, ",
        Atmosphere.STORMY: "dark, grey light, ",
        Atmosphere.SNOWY: "cold, pale light, ",
    },
    "exterior": {
        Atmosphere.CLEAR: "",
        Atmosphere.OVERCAST: "under a flat overcast sky, no hard shadows, ",
        Atmosphere.RAINY: "in the rain, fine diagonal rain streaks, wet ground, ",
        Atmosphere.FOGGY: "in thick fog, the far distance fading to blank paper, ",
        Atmosphere.STORMY: "in a storm, heavy slanting rain, wind-blown trees and debris, ",
        Atmosphere.SNOWY: "in falling snow, snow lying on the ground and every ledge, ",
    },
}


def _lighting_prompt(setting: str, time_of_day: TimeOfDay, atmosphere: Atmosphere) -> str:
    """
    The lighting edit for an interior or exterior place -- an interior's edit changes only its light; an exterior's, its light and weather.
    """
    change = LIGHTING_TIME[setting][time_of_day] + LIGHTING_WEATHER[setting][atmosphere]
    edit = (
        "the same view of the place in image 1, from the same camera position and with the same framing, with everything in it "
        f"unchanged, changed only in its {'light' if setting == 'interior' else 'light and weather'}: "
    )
    return "Storyboard panel, " + prompts.STYLE + "filling full frame, " + edit + change.rstrip(", ")


@pytest.mark.integration
def test_facings_with_their_own_descriptions():
    """
    Tries each facing drawn from its own description -- a common description of the place plus one line for that side -- with the north plate as image 1 for every other facing. Checks, by eye:

    - the office: each of its four walls shows only its own contents (north has no door or coat stand any more), the side walls are continuous with north and south, and it is one office from every side;
    - an outdoor harbour quay: whether "sides" still work without walls and a ceiling to keep it the same place;
    - a cluttered cottage kitchen, north and south: that the office wasn't a one-off;
    - office south through the rest of the chain (medium framing, then "the door ajar", then night): that a reverse view survives it like a north one does;
    - night with interior wording (no sky, no weather) beside the current wording, which drew a starry sky and rain inside the windowless office; and the quay at night in the rain with exterior wording.
    """
    store = DiskStore(OUTPUT_DIR)
    generator = Generator("trial", store)

    def side(common: str, sides: dict, facing: Facing, indoors: bool = True) -> str:
        if facing == Facing.NORTH:
            return generator._background("plate", _side_prompt(common, sides[facing], indoors, False), [])
        north = side(common, sides, Facing.NORTH, indoors)
        return generator._background("plate", _side_prompt(common, sides[facing], indoors, True), [north])

    def lit(source: str, setting: str, time_of_day: TimeOfDay, atmosphere: Atmosphere) -> str:
        return generator._background("lighting", _lighting_prompt(setting, time_of_day, atmosphere), [source])

    def office_chain(details: str = "", time_of_day: TimeOfDay = TimeOfDay.DAY) -> str:
        # The real chain from here on, starting from the south plate (recorded on the entry, as the engine would)
        office = Location(id="office-views", name="Office", description=OFFICE_COMMON, plates={Facing.SOUTH: side(OFFICE_COMMON, OFFICE_SIDES, Facing.SOUTH)})
        return generator.background(office, Facing.SOUTH, ShotSize.MEDIUM, CameraAngle.EYE_LEVEL, details, time_of_day, Atmosphere.CLEAR)

    steps = [
        ("office north", lambda: side(OFFICE_COMMON, OFFICE_SIDES, Facing.NORTH)),
        ("office east", lambda: side(OFFICE_COMMON, OFFICE_SIDES, Facing.EAST)),
        ("office south", lambda: side(OFFICE_COMMON, OFFICE_SIDES, Facing.SOUTH)),
        ("office west", lambda: side(OFFICE_COMMON, OFFICE_SIDES, Facing.WEST)),
        ("quay north (outdoors)", lambda: side(QUAY_COMMON, QUAY_SIDES, Facing.NORTH, indoors=False)),
        ("quay south (outdoors)", lambda: side(QUAY_COMMON, QUAY_SIDES, Facing.SOUTH, indoors=False)),
        ("kitchen north", lambda: side(KITCHEN_COMMON, KITCHEN_SIDES, Facing.NORTH)),
        ("kitchen south", lambda: side(KITCHEN_COMMON, KITCHEN_SIDES, Facing.SOUTH)),
        ("", None),
        ("office south, medium", lambda: office_chain()),
        ("+ the door ajar", lambda: office_chain("the door ajar")),
        ("+ at night (current wording)", lambda: office_chain("the door ajar", TimeOfDay.NIGHT)),
        ("+ at night (interior wording)", lambda: lit(office_chain("the door ajar"), "interior", TimeOfDay.NIGHT, Atmosphere.CLEAR)),
        ("quay north, night + rain (exterior)", lambda: lit(
            side(QUAY_COMMON, QUAY_SIDES, Facing.NORTH, indoors=False), "exterior", TimeOfDay.NIGHT, Atmosphere.RAINY,
        )),
    ]

    results = _run(store, steps, "facings_sheet.png")

    assert all(image for label, image in results if label)
