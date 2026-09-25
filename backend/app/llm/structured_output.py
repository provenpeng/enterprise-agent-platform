"""Provider-specific structured output without changing the domain contracts."""

import json
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

StructuredOutputMethod = Literal["json_schema", "json_mode"]


def structured_chain(
    chat: ChatOpenAI,
    schema: type[BaseModel],
    *,
    method: StructuredOutputMethod,
    include_raw: bool = False,
):
    if method == "json_schema":
        return chat.with_structured_output(
            schema, method="json_schema", strict=True, include_raw=include_raw
        )
    return chat.with_structured_output(
        schema, method="json_mode", include_raw=include_raw
    )


def json_mode_instruction(
    schema: type[BaseModel], method: StructuredOutputMethod
) -> str:
    if method != "json_mode":
        return ""
    return (
        " Return only one JSON object matching this schema; do not wrap it in Markdown: "
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
