import json
import boto3
from pydantic import BaseModel


def make_bedrock_caller(schema_model: type[BaseModel], model_id: str = "eu.anthropic.claude-haiku-4-5-20251001-v1:0", region_name: str = "eu-west-2"):
    """Returns a function matching the CallLLM signature from shot_breakdown.py
    (prompt in, raw text out)
    """
    client = boto3.client("bedrock-runtime", region_name=region_name)
    schema_json = json.dumps(schema_model.model_json_schema())

    def call_llm(prompt: str) -> str:
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            # Requires model access to be granted for this model_id in this region first
            outputConfig={
                "textFormat": {
                    "type": "json_schema",
                    "structure": {
                        "jsonSchema": {
                            "schema": schema_json,
                            "name": schema_model.__name__,
                            "description": f"Structured output for {schema_model.__name__}",
                        }
                    }
                }
            },
        )
        # Standard Converse API response shape — the model's text sits here
        # regardless of whether structured output is on.
        return response["output"]["message"]["content"][0]["text"]

    return call_llm