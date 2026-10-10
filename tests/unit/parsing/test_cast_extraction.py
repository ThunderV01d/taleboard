"""
Unit tests for cast_extraction.

Covers character ID assignment, conversion to domain characters and the empty-story guard. No LLM calls are made.
"""
import pytest
from taleboard.parsing.cast_extraction import assign_char_ids, to_domain_character, extract_cast
from taleboard.parsing.llm_schemas import LLMCharacterDraft

def test_assign_char_ids_no_duplicates():
    """
    Verifies that characters with distinct names get their plain slugified names as IDs.
    """
    characters = [
        LLMCharacterDraft(name="Alice", description="..."),
        LLMCharacterDraft(name="Bob", description="..."),
    ]
    result = assign_char_ids(characters)

    assert set(result.keys()) == {"alice", "bob"}
    assert result["alice"].name == "Alice"
    assert result["bob"].name == "Bob"


def test_assign_char_ids_duplicate_names_get_retroactive_suffixes():
    """
    Verifies that characters sharing a name all get numeric suffixes, including the first one.
    """
    characters = [
        LLMCharacterDraft(name="Sam", description="first sam"),
        LLMCharacterDraft(name="Sam", description="second sam"),
    ]
    result = assign_char_ids(characters)

    assert set(result.keys()) == {"sam_1", "sam_2"}
    assert result["sam_1"].description == "first sam"
    assert result["sam_2"].description == "second sam"


def test_assign_char_ids_impersonator_collision_does_not_lose_characters():
    """
    Verifies that no character is overwritten when a literal name collides with a suffixed ID.

    Here, "Sam 1" and "Sam 2" slugify to the same IDs as the suffixed duplicate Sams.
    """
    characters = [
        LLMCharacterDraft(name="Sam", description="the real sam, first mention"),
        LLMCharacterDraft(name="Sam", description="the real sam, second mention"),
        LLMCharacterDraft(name="Sam 1", description="an impersonator"),
        LLMCharacterDraft(name="Sam 2", description="another impersonator"),
    ]
    result = assign_char_ids(characters)

    # Checks that nobody got overwritten
    assert len(result) == len(characters)


def test_assign_char_ids_empty_list():
    """
    Verifies that an empty list of characters produces an empty mapping.
    """
    assert assign_char_ids([]) == {}

def test_to_domain_character_maps_fields():
    """
    Verifies that every field of the draft, plus the appearance reference, carries over to the domain Character.
    """
    draft = LLMCharacterDraft(name="Alice", description="A woman with red hair.")
    character = to_domain_character(draft, appearance_reference="alice_ref.png")
    assert character.name == "Alice"
    assert character.description == "A woman with red hair."
    assert character.appearance_reference == "alice_ref.png"


def test_to_domain_character_defaults_appearance_reference_to_none():
    """
    Verifies that the appearance reference defaults to None when none is given.
    """
    draft = LLMCharacterDraft(name="Bob", description="A man with a beard.")
    character = to_domain_character(draft)
    assert character.appearance_reference is None

@pytest.mark.parametrize("story", ["", "   \n\n  \n"])
def test_extract_cast_rejects_empty_story_before_calling_the_llm(story):
    """
    Verifies that an empty or whitespace-only story raises a ValueError before the (paid) LLM is ever called.

    Arguments:
        story: str - Empty or whitespace-only story (parametrized).
    """
    def call_llm(prompt: str) -> str:
        """
        Fails the test if called -- the LLM must never be reached for an empty story.

        Arguments:
            prompt: str - Prompt that would have been sent to the LLM.

        Returns:
            str - Never returns; always raises an AssertionError.
        """
        raise AssertionError("the LLM must not be called for an empty story")

    with pytest.raises(ValueError, match="empty"):
        extract_cast(story, call_llm)
