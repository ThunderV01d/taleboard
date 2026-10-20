"""
TaleBoard's HTTP API -- the editor's projects, registries, scenes and shots. Each resource's routes live in taleboard.api.routes; this module adds the API key check and the error handling every route shares.

Imports nothing from taleboard.rendering -- loading the image models would add seconds to every cold start of the API Lambda.

Every endpoint requires the shared X-API-Key header (see verify_api_key). It's a cost guard against stray visitors and bots, not real authentication -- the frontend ships the key in its JavaScript.

Attributes:
    API_KEY_HEADER: str - Header clients send the shared API key in.
    API_KEY_PARAMETER_ENV: str - Environment variable naming the SSM parameter that holds the key.
    app: FastAPI - The FastAPI application.
    handler: Mangum - API Lambda entry point -- adapts API Gateway (HTTP API, payload v2.0) events to the app.
"""
import hmac
import os
from functools import lru_cache

import boto3
from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from mangum import Mangum

from taleboard.api.routes import projects, registries, scenes, shots, uploads
from taleboard.storage.storyboard_store import ShotConflictError

API_KEY_HEADER = "X-API-Key"
API_KEY_PARAMETER_ENV = "TALEBOARD_API_KEY_PARAMETER"

@lru_cache
def get_api_key() -> str:
    """
    Reads the shared API key from SSM Parameter Store once per container, so warm invocations never call SSM.

    Fails closed: if the parameter isn't configured, every request errors rather than going through unchecked.

    Returns:
        str - The expected API key.
    """
    return boto3.client("ssm").get_parameter(Name=os.environ[API_KEY_PARAMETER_ENV], WithDecryption=True)["Parameter"]["Value"]

def verify_api_key(
    api_key: str | None = Security(APIKeyHeader(name=API_KEY_HEADER, auto_error=False)),
    expected: str = Depends(get_api_key),
) -> None:
    """
    Rejects a request unless it carries the shared API key. Applied to every endpoint.

    Arguments:
        api_key: str - The key the client sent, if any.
        expected: str - The key it must match.

    Raises:
        HTTPException - 401 if the key is missing or wrong.
    """
    if api_key is None or not hmac.compare_digest(api_key.encode(), expected.encode()):  # Constant-time, so response timing doesn't leak the key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key", headers={"WWW-Authenticate": "APIKey"})

app = FastAPI(title="TaleBoard API", dependencies=[Depends(verify_api_key)])

@app.exception_handler(ShotConflictError)
async def shot_conflict(request: Request, error: ShotConflictError) -> JSONResponse:
    """
    Answers a save from an out-of-date copy of a shot with 409 Conflict, and the shot's current version so the client can reload it.

    Arguments:
        request: Request - The request that clashed.
        error: ShotConflictError - The store's error.

    Returns:
        JSONResponse - 409, with the message and current version.
    """
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error), "current_version": error.current_version})

app.include_router(projects.router)
app.include_router(registries.characters)
app.include_router(registries.props)
app.include_router(registries.locations)
app.include_router(scenes.router)
app.include_router(shots.router)
app.include_router(uploads.router)

# lifespan="off": startup/shutdown hooks don't map onto Lambda's invoke model, and the store is already cached per container by get_boards
handler = Mangum(app, lifespan="off")