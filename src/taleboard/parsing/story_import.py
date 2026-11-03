"""
Turns a story breakdown into a project: its registries, then its scenes, then each scene's shots -- every shot laid out as layers (see placement), none of them drawn yet.

The breakdown's IDs are its own; the registries give each entry an ID of their own when it's saved (usually the same slug), so every reference is mapped across as it's written.
"""
from taleboard.parsing.placement import Figure, place_layers
from taleboard.parsing.story_breakdown import StoryBreakdown
from taleboard.parsing.llm_schemas import LLMShotDraft
from taleboard.schema.enums import Facing
from taleboard.schema.storyboard import Character, Location, Prop, Scene, Shot
from taleboard.storage.storyboard_store import StoryboardStore


def write_breakdown(boards: StoryboardStore, project_id: str, breakdown: StoryBreakdown) -> list[tuple[Scene, Shot]]:
    """
    Writes a breakdown into a project: every character, prop and location, then each scene in story order with its shots.

    Arguments:
        boards: StoryboardStore - Store to write to.
        project_id: str - Unique project ID (an empty project -- nothing in it is replaced).
        breakdown: StoryBreakdown - The story's breakdown.

    Returns:
        list[tuple[Scene,Shot]] - Every shot written, with its scene, in story order.
    """
    characters = {
        draft_id: boards.create_entry(project_id, Character, draft.name, description=draft.description, aliases=list(draft.aliases))
        for draft_id, draft in breakdown.cast.items()
    }
    props = {
        draft_id: boards.create_entry(project_id, Prop, draft.name, description=draft.description)
        for draft_id, draft in breakdown.props.items()
    }
    locations = {
        draft_id: boards.create_entry(
            project_id, Location, draft.name, description=draft.description, setting=draft.setting,
            views={Facing(side): view for side, view in draft.views.model_dump().items()},
        )
        for draft_id, draft in breakdown.locations.items()
    }

    written = []
    for order, part in enumerate(breakdown.scenes):
        scene = Scene(
            name=part.scene.name, description=part.scene.description, order=order,
            location_id=locations[part.scene.location_id].id, time_of_day=part.scene.time_of_day, atmosphere=part.scene.atmosphere,
        )
        boards.create_scene(project_id, scene)
        for shot_order, (_, result) in enumerate(part.shots):
            shot = to_shot(scene.id, shot_order, result.shot, characters, props)
            boards.create_shot(project_id, shot)
            written.append((scene, shot))
    return written


def to_shot(scene_id: str, order: int, draft: LLMShotDraft, characters: dict[str, Character], props: dict[str, Prop]) -> Shot:
    """
    Turns one drafted shot into a shot of the project, its characters and props placed as layers.

    Arguments:
        scene_id: str - The scene it's in.
        order: int - Its position in the scene.
        draft: LLMShotDraft - The drafted shot.
        characters: dict[str,Character] - The project's characters, by the breakdown's character ID.
        props: dict[str,Prop] - The project's props, by the breakdown's prop ID.

    Returns:
        Shot - The shot (not yet saved).
    """
    figures = [
        Figure("character", characters[r.character_id].id, characters[r.character_id].name, r.position, r.size, r.orientation, r.action)
        for r in draft.regions
    ]
    figures += [
        Figure(
            "prop", props[p.prop_id].id, props[p.prop_id].name, p.position, p.size, p.orientation,
            held_by=characters[p.held_by].id if p.held_by else None,
        )
        for p in draft.props
    ]
    return Shot(
        scene_id=scene_id, order=order, description=draft.description, duration_s=draft.duration_s,
        shot_size=draft.shot_size, angle=draft.angle, details=draft.details,
        layers=place_layers(draft.shot_size, draft.facing, figures),
    )
