from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserAdminView(BaseModel):
    """Summary view of a user as seen by an admin."""

    user_id: str
    username: str
    is_admin: bool
    is_active: bool
    totp_enrolled: bool
    created_at: datetime
    active_sessions_count: int


class UserListResponse(BaseModel):
    """Response body for GET /admin/users."""

    users: list[UserAdminView]


class SessionAdminView(BaseModel):
    """Summary view of a VPN session as seen by an admin."""

    session_id: str
    user_id: str
    username: str
    device_name: str
    assigned_ip: str
    status: str
    created_at: datetime
    expires_at: datetime


class SessionListResponse(BaseModel):
    """Response body for GET /admin/sessions."""

    sessions: list[SessionAdminView]


class SessionRevokeResponse(BaseModel):
    """Response body for DELETE /admin/sessions/{session_id}."""

    session_id: str
    status: str = "revoked"


class SystemSettingsResponse(BaseModel):
    """Response body for GET /admin/settings and PUT /admin/settings."""

    max_sessions_per_user: int
    session_ttl_hours: int


class SystemSettingsUpdateRequest(BaseModel):
    """
    Request body for PUT /admin/settings.

    All fields are optional — only provided fields are updated.
    """

    max_sessions_per_user: int | None = Field(
        default=None, ge=1, description="Maximum concurrent VPN sessions per user"
    )
    session_ttl_hours: int | None = Field(
        default=None, ge=1, description="Session lifetime in hours"
    )
