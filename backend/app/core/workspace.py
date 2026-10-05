"""Anonymous workspaces: per-browser isolation of documents and chats without accounts.

The frontend generates a random UUID once, stores it in localStorage and sends it
as the `X-Workspace-Id` header. Every document, vector and chat session belongs
to exactly one workspace, and all queries are filtered by it. The UUID acts as a
bearer secret: unguessable, but anyone holding it can see that workspace. This
gives privacy between visitors of a public demo; it is not authentication.

Requests without the header (curl, scripts) use a shared default workspace.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header

from app.core.errors import AppError

DEFAULT_WORKSPACE_ID = uuid.UUID(int=0)
WORKSPACE_HEADER = "X-Workspace-Id"


class InvalidWorkspaceError(AppError):
    code = "invalid_workspace"


def get_workspace_id(
    x_workspace_id: Annotated[str | None, Header(alias=WORKSPACE_HEADER)] = None,
) -> uuid.UUID:
    if not x_workspace_id:
        return DEFAULT_WORKSPACE_ID
    try:
        return uuid.UUID(x_workspace_id)
    except ValueError as exc:
        raise InvalidWorkspaceError(f"{WORKSPACE_HEADER} must be a UUID.") from exc


WorkspaceDep = Annotated[uuid.UUID, Depends(get_workspace_id)]
