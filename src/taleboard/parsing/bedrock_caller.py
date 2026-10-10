"""
Manages Converse API calls to AWS Bedrock.

Used extensively in the parsing pipeline.

Attributes:
    CallLLM: Callable[[str],str] - LLM call function model.
    MakeCaller: Callable[[type[BaseModel]],CallLLM] - LLM caller builder function model.
"""
import json
import boto3
from pydantic import BaseModel
from typing import Callable

CallLLM = Callable[[str],str]
MakeCaller = Callable[[type[BaseModel]],CallLLM]

def make_bedrock_caller(schema_model: type[BaseModel], model_id: str = "eu.anthropic.claude-haiku-4-5-20251001-v1:0", region_name: str = "eu-west-2") -> CallLLM:
    """
    Constructs an AWS boto3 client dynamically, and returns an LLM call function that can be used in the parsing pipeline.

    Arguments:
        schema_model: type[BaseModel] - Output schema.
        model_id: str - Bedrock model ID (copied from the Bedrock dashboard).
        region_name: str - AWS Region (some models are only available on specific regions).
    
    Returns:
        CallLLM - LLM calling function, as defined at the top of this module.
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
        # Standard Converse API response shape
        # The model's text sits here regardless of whether structured output is on.
        return response["output"]["message"]["content"][0]["text"]

    return call_llm