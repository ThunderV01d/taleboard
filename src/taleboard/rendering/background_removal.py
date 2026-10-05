"""Isolating a character cutout from its generated background."""

import base64
import io
import json

import boto3
from PIL import Image
from rembg import new_session, remove

BEDROCK_MODEL_ID = "stability.stable-image-remove-background-v1:0"
_rembg_session = new_session("isnet-anime") #Trained on illustration or line-art content

def remove_background(image_bytes: bytes) -> bytes:
    """Isolate the subject from its background. Free, local, no network call.
    """
    input_image = Image.open(io.BytesIO(image_bytes))
    output_image = remove(input_image,session=_rembg_session)

    buffer = io.BytesIO()
    output_image.save(buffer, format="PNG")
    return buffer.getvalue()


def remove_background_via_bedrock(image_bytes: bytes, region_name: str = "us-east-1") -> bytes:
    """Last-resort fallback for when remove_background() visibly fails on
    a specific image. Uses AWS Bedrock to call the Stability AI background removal model."""
    client = boto3.client("bedrock-runtime", region_name=region_name)

    body = {"image": base64.b64encode(image_bytes).decode("utf-8")}
    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body),
    )
    response_body = json.loads(response["body"].read())
    return base64.b64decode(response_body["images"][0])