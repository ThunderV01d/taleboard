"""
Routes for sharing a project: list who it's shared with, share it with a user, and stop sharing it.

Only the project's owner can use them. For now a project can only be shared to view (role viewer) -- editor is
reserved for collaboration, which isn't built. There's no sharing UI: these are used by scripts/share_project.py, to
share seeded projects with the guest user.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from taleboard.api.deps import get_boards, get_owned_project, get_user_id
from taleboard.schema.sharing import Share, ShareRole
from taleboard.schema.storyboard import Project
from taleboard.storage.storyboard_store import StoryboardStore

router = APIRouter(prefix="/projects/{project_id}/shares", tags=["shares"])

# The roles that can be granted today
GRANTABLE_ROLES = frozenset({ShareRole.VIEWER})


class ShareIn(BaseModel):
    """
    Request body for sharing a project.

    Attributes:
        role: ShareRole - What the user may do with it. Only "viewer" is accepted for now.
    """
    role: ShareRole = ShareRole.VIEWER


@router.get("", response_model=list[Share])
def list_shares(project: Project = Depends(get_owned_project), boards: StoryboardStore = Depends(get_boards)) -> list[Share]:
    """
    Lists who the project is shared with.
    """
    return boards.list_shares(project.project_id)

@router.put("/{grantee_id}", response_model=Share)
def share_project(grantee_id: str, body: ShareIn, project: Project = Depends(get_owned_project), user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> Share:
    """
    Shares the project with a user (by their user ID), or changes their role if it's already shared with them.
    """
    if body.role not in GRANTABLE_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project can only be shared to view, for now")
    if grantee_id == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already own this project")
    return boards.share_project(project.project_id, grantee_id, body.role, granted_by=user_id)

@router.delete("/{grantee_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_project(grantee_id: str, project: Project = Depends(get_owned_project), boards: StoryboardStore = Depends(get_boards)) -> Response:
    """
    Stops sharing the project with a user. Nothing happens if it wasn't shared with them.
    """
    boards.unshare_project(project.project_id, grantee_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
