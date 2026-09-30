from taleboard.parsing.cast_extraction import assign_char_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft


def test_assign_char_ids_no_duplicates():
    characters = [
        LLMCharacterDraft(name="Alice", description="..."),
        LLMCharacterDraft(name="Bob", description="..."),
    ]
    result = assign_char_ids(characters)

    assert set(result.keys()) == {"alice", "bob"}
    assert result["alice"].name == "Alice"
    assert result["bob"].name == "Bob"


def test_assign_char_ids_duplicate_names_get_retroactive_suffixes():
    characters = [
        LLMCharacterDraft(name="Sam", description="first sam"),
        LLMCharacterDraft(name="Sam", description="second sam"),
    ]
    result = assign_char_ids(characters)

    assert set(result.keys()) == {"sam_1", "sam_2"}
    assert result["sam_1"].description == "first sam"
    assert result["sam_2"].description == "second sam"


def test_assign_char_ids_impersonator_collision_does_not_lose_characters():
    characters = [
        LLMCharacterDraft(name="Sam", description="the real sam, first mention"),
        LLMCharacterDraft(name="Sam", description="the real sam, second mention"),
        LLMCharacterDraft(name="Sam 1", description="an impersonator"),
        LLMCharacterDraft(name="Sam 2", description="another impersonator"),
    ]
    result = assign_char_ids(characters)

    #check that nobody got overwritten
    assert len(result) == len(characters)


def test_assign_char_ids_empty_list():
    assert assign_char_ids([]) == {}