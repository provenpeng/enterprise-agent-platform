"""Authenticated identity exposed to first-party clients."""

import uuid
from typing import Literal

from pydantic import BaseModel


class IdentityRead(BaseModel):
    subject: str
    tenant_id: uuid.UUID
    role: Literal["admin", "viewer"]
