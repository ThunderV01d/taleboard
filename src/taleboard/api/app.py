"""
TaleBoard's HTTP API -- the editor's projects, registries, scenes and shots. Each resource's routes live in taleboard.api.routes; this module adds the sign-in check and the error handling every route shares.

Imports nothing that loads the image models (background removal) or the story breakdown -- either would add seconds to every cold start of the API Lambda.

Every endpoint needs a signed-in user. API Gateway's JWT authorizer checks the Cognito access token before the Lambda runs; get_user_id then refuses any request that arrives without one.

Attributes:
    app: FastAPI - The FastAPI application.
    handler: Mangum - API Lambda entry point -- adapts API Gateway (HTTP API, payload v2.0) events to the app.
"""
import hmac
import os
from functools import lru_cache

import boto3
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from mangum import Mangum

from taleboard.api.deps import get_user_id
from taleboard.api.routes import projects, registries, scenes, shots, uploads, generation, imports
from taleboard.storage.storyboard_store import ShotConflictError

app = FastAPI(title="TaleBoard API", dependencies=[Depends(get_user_id)])

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
app.include_router(generation.router)
app.include_router(imports.router)

# lifespan="off": startup/shutdown hooks don't map onto Lambda's invoke model, and the store is already cached per container by get_boards
handler = Mangum(app, lifespan="off")