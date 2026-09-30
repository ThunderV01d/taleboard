import json
from unittest.mock import MagicMock, patch

from taleboard.parsing.bedrock_caller import make_bedrock_caller
from taleboard.parsing.llm_schemas import build_shot_draft_model


def test_call_llm_builds_correct_request_and_parses_response():
    ShotModel = build_shot_draft_model(["alice", "bob"])

    fake_client = MagicMock()
    fake_client.converse.return_value = {
        "output": {
            "message": {
                "content": [{"text": '{"description": "test"}'}],
            }
        }
    }

    with patch("boto3.client", return_value=fake_client) as mock_boto_client:
        call_llm = make_bedrock_caller(
            model_id="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            schema_model=ShotModel,
            region_name="eu-west-2",
        )
        response = call_llm("a test prompt")

    mock_boto_client.assert_called_once_with("bedrock-runtime", region_name="eu-west-2")
    assert response == '{"description": "test"}'

    _, kwargs = fake_client.converse.call_args
    assert kwargs["modelId"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "a test prompt"}]}]

    schema_sent = json.loads(
        kwargs["outputConfig"]["textFormat"]["structure"]["jsonSchema"]["schema"]
    )
    assert schema_sent == ShotModel.model_json_schema()


def test_schema_has_additional_properties_false_everywhere():
    ShotModel = build_shot_draft_model(["alice", "bob"])
    schema = ShotModel.model_json_schema()

    assert schema.get("additionalProperties") is False
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False


def test_schema_has_no_unsupported_numeric_keywords():
    ShotModel = build_shot_draft_model(["alice", "bob"])
    schema = ShotModel.model_json_schema()

    duration_schema = schema["properties"]["duration_s"]
    assert "exclusiveMinimum" not in duration_schema
    assert "maximum" not in duration_schema