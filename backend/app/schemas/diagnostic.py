"""Bounded order diagnostic request and response."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.answer import AnswerCitation
from app.schemas.business import OrderSnapshot


OrderId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$"
    ),
]


class DiagnoseRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    order_id: OrderId | None = None


class DiagnoseResponse(BaseModel):
    knowledge_base_id: uuid.UUID
    status: Literal[
        "ANSWERED", "BUSINESS_FACTS_ONLY", "NEEDS_ORDER_ID", "ORDER_NOT_FOUND"
    ]
    answer: str
    order: OrderSnapshot | None
    citations: list[AnswerCitation]
