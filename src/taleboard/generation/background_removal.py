"""
Isolates a character cutout from its generated background.

Uses rembg to remove the generated background, using a paid image background removal model on AWS Bedrock as a fallback.

Attributes:
    BEDROCK_MODEL_ID: str - Model ID from AWS Bedrock.
    _rembg_session: BaseSession - A rembg session created at runtime.
"""

import base64
import io
import json

import boto3
from PIL import Image
from rembg import new_session, remove

BEDROCK_MODEL_ID = "stability.stable-image-remove-background-v1:0"
_rembg_session = new_session("isnet-anime", providers=["CPUExecutionProvider"]) # "isnet-anime" is trained on anime-style illustrations -- presumably, this works better with the line art style in our generated images

def remove_background(image_bytes: bytes) -> bytes:
    """
    Isolates the subject from its background.
    
    This function is free and local, with no network call.

    Arguments:
        image_bytes: bytes - Image file to be processed in bytes.

    Returns:
        bytes - Character cutout image file in bytes.
    """
    input_image = Image.open(io.BytesIO(image_bytes))
    output_image = remove(input_image,session=_rembg_session)

    buffer = io.BytesIO()
    output_image.save(buffer, format="PNG") # PNG for transparency
    return buffer.getvalue()


def remove_background_via_bedrock(image_bytes: bytes, region_name: str = "us-east-1") -> bytes:
    """
    Last-resort fallback for when remove_background visibly fails on a specific image.
    
    Uses AWS Bedrock to call the Stability AI background removal model.
    
    Arguments:
        image_bytes: bytes - Image file to be processed in bytes.
        region_name: str - AWS Region (some models are only available on specific regions).
    
    Returns:
        bytes - Character cutout image file in bytes.
    """
    client = boto3.client("bedrock-runtime", region_name=region_name)

    body = {"image": base64.b64encode(image_bytes).decode("utf-8")}
    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body),
    )
    response_body = json.loads(response["body"].read())
    return base64.b64decode(response_body["images"][0])