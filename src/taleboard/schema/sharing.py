"""
Sharing a project with another user, and what each user may do with a project.

A project's owner is whoever created it (Project.owner_id) -- that is never a share. Anyone else reaches a project only
through a Share naming them, with a role. Shares are keyed by the grantee's user ID (their Cognito sub), so a later
invite-by-email feature can add pending invites alongside them without changing these.
"""
from datetime import datetime
from enum import StrEnum
from typing import Literal

from taleboard.schema.base import Model


class ShareRole(StrEnum):
    """
    What a share lets its grantee do. Only VIEWER is ever granted for now; EDITOR is reserved for collaboration.
    """
    VIEWER = "viewer"
    EDITOR = "editor"


# What a user may do with a project: own it, edit or view it through a share, or nothing (it's a 404 to them)
Access = Literal["owner", "editor", "viewer", "none"]

# Each access level includes everything below it
ACCESS_RANK: dict[Access, int] = {"none": 0, "viewer": 1, "editor": 2, "owner": 3}


class Share(Model):
    """
    One user's access to someone else's project.

    Attributes:
        project_id: str - The project shared.
        grantee_id: str - The user it's shared with (their Cognito sub).
        role: ShareRole - What they may do with it.
        granted_by: str - The user who shared it (its owner).
        created_at: datetime - When it was shared (UTC).
    """
    project_id: str
    grantee_id: str
    role: ShareRole
    granted_by: str
    created_at: datetime
