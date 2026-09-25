"""A fixed, auditable LangGraph route from question to tenant-scoped evidence."""

import asyncio
import logging
import re
import uuid
from typing import TypedDict

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, StateGraph
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model import DiagnosticModel
from app.agent.trace import RunRecorder
from app.business.orders import OrderLookupTool
from app.schemas.answer import AnswerCitation
from app.schemas.business import OrderSnapshot
from app.schemas.diagnostic import DiagnoseResponse
from app.schemas.retrieval import SearchHit
from app.services.errors import UpstreamUnavailable
from app.services.retrieval import search_knowledge_base

logger = logging.getLogger(__name__)
ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class DiagnosticState(TypedDict, total=False):
    question: str
    order_id: str | None
    search_policy: bool
    order: OrderSnapshot | None
    hits: list[SearchHit]
    response: DiagnoseResponse


def _business_facts(order: OrderSnapshot) -> str:
    if not order.refund_attempts:
        return f"订单 {order.order_id} 尚无退款尝试记录。"
    latest = order.refund_attempts[-1]
    if latest.reason_code:
        return (
            f"订单 {order.order_id} 最近一次退款状态为 {latest.status.value}，"
            f"业务原因代码为 {latest.reason_code}。当前未提供可验证的规则解释。"
        )
    return f"订单 {order.order_id} 最近一次退款状态为 {latest.status.value}。"


async def diagnose_order(
    db: AsyncSession,
    embeddings: Embeddings,
    model: DiagnosticModel,
    recorder: RunRecorder,
    *,
    tenant_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    embedding_model: str,
    question: str,
    explicit_order_id: str | None,
    planning_timeout_seconds: float,
    embedding_timeout_seconds: float,
    generation_timeout_seconds: float,
) -> DiagnoseResponse:
    """Run at most four graph nodes, with no arbitrary model-selected tool execution."""

    async def plan(state: DiagnosticState) -> dict:
        async with recorder.step("plan", {"question": state["question"]}) as trace:
            try:
                async with asyncio.timeout(planning_timeout_seconds):
                    call = await model.plan(state["question"])
            except Exception as exc:
                logger.warning("Diagnostic planning failed", exc_info=True)
                raise UpstreamUnavailable("Diagnostic planning is unavailable") from exc
            trace.usage = call.usage
            proposal = call.value
            order_id = explicit_order_id or proposal.order_id
            if order_id is None or not ORDER_ID_PATTERN.fullmatch(order_id):
                trace.output = {"status": "NEEDS_ORDER_ID"}
                return {
                    "response": DiagnoseResponse(
                        knowledge_base_id=knowledge_base_id,
                        status="NEEDS_ORDER_ID",
                        answer="请提供有效的订单编号。",
                        order=None,
                        citations=[],
                    )
                }
            trace.output = {
                "order_id": order_id,
                "search_policy": proposal.search_policy,
            }
            return {"order_id": order_id, "search_policy": proposal.search_policy}

    async def lookup(state: DiagnosticState) -> dict:
        async with recorder.step(
            "lookup_order", {"order_id": state["order_id"]}
        ) as trace:
            try:
                order = await OrderLookupTool(db, tenant_id).lookup(state["order_id"])
            except SQLAlchemyError as exc:
                logger.warning("Diagnostic order lookup failed", exc_info=True)
                raise UpstreamUnavailable("Order lookup is unavailable") from exc
            if order is None:
                trace.output = {"status": "ORDER_NOT_FOUND"}
                return {
                    "response": DiagnoseResponse(
                        knowledge_base_id=knowledge_base_id,
                        status="ORDER_NOT_FOUND",
                        answer="未找到该订单。",
                        order=None,
                        citations=[],
                    )
                }
            latest_attempt = (
                order.refund_attempts[-1] if order.refund_attempts else None
            )
            trace.output = {
                "order_id": order.order_id,
                "refund_attempt_count": len(order.refund_attempts),
                "latest_reason_code": latest_attempt.reason_code
                if latest_attempt
                else None,
            }
            return {"order": order}

    async def retrieve(state: DiagnosticState) -> dict:
        order = state["order"]
        latest_reason = (
            order.refund_attempts[-1].reason_code if order.refund_attempts else None
        )
        query = f"{state['question']} {latest_reason or ''}".strip()
        async with recorder.step("retrieve_policy", {"query": query}) as trace:
            hits = await search_knowledge_base(
                db,
                embeddings,
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                embedding_model=embedding_model,
                query=query,
                top_k=5,
                min_score=0.5,
                timeout_seconds=embedding_timeout_seconds,
            )
            trace.output = {
                "hits": [
                    {
                        "chunk_id": str(hit.chunk_id),
                        "document_id": str(hit.document_id),
                        "index_version": hit.index_version,
                        "score": hit.score,
                    }
                    for hit in hits
                ]
            }
            return {"hits": hits}

    async def compose(state: DiagnosticState) -> dict:
        order = state["order"]
        hits = state.get("hits", [])
        async with recorder.step(
            "compose", {"candidate_chunk_ids": [str(hit.chunk_id) for hit in hits]}
        ) as trace:
            if not hits:
                response = DiagnoseResponse(
                    knowledge_base_id=knowledge_base_id,
                    status="BUSINESS_FACTS_ONLY",
                    answer=_business_facts(order),
                    order=order,
                    citations=[],
                )
            else:
                try:
                    async with asyncio.timeout(generation_timeout_seconds):
                        call = await model.explain(state["question"], order, hits)
                except Exception as exc:
                    logger.warning("Diagnostic explanation failed", exc_info=True)
                    raise UpstreamUnavailable(
                        "Diagnostic explanation is unavailable"
                    ) from exc
                trace.usage = call.usage
                draft = call.value
                authorized = {str(hit.chunk_id): hit for hit in hits}
                cited_ids = list(dict.fromkeys(draft.cited_chunk_ids))
                if (
                    not draft.answer.strip()
                    or not cited_ids
                    or any(chunk_id not in authorized for chunk_id in cited_ids)
                ):
                    logger.info("Diagnostic explanation lacked valid policy citations")
                    response = DiagnoseResponse(
                        knowledge_base_id=knowledge_base_id,
                        status="BUSINESS_FACTS_ONLY",
                        answer=_business_facts(order),
                        order=order,
                        citations=[],
                    )
                else:
                    citations = [
                        AnswerCitation(number=index, source=authorized[chunk_id])
                        for index, chunk_id in enumerate(cited_ids, start=1)
                    ]
                    markers = " ".join(f"[{citation.number}]" for citation in citations)
                    response = DiagnoseResponse(
                        knowledge_base_id=knowledge_base_id,
                        status="ANSWERED",
                        answer=f"{draft.answer.strip()}\n\n来源：{markers}",
                        order=order,
                        citations=citations,
                    )
            trace.output = {
                "status": response.status,
                "cited_chunk_ids": [
                    str(item.source.chunk_id) for item in response.citations
                ],
            }
            return {"response": response}

    graph = StateGraph(DiagnosticState)
    graph.add_node("plan", plan)
    graph.add_node("lookup_order", lookup)
    graph.add_node("retrieve_policy", retrieve)
    graph.add_node("compose", compose)
    graph.set_entry_point("plan")
    graph.add_conditional_edges(
        "plan", lambda state: END if "response" in state else "lookup_order"
    )
    graph.add_conditional_edges(
        "lookup_order",
        lambda state: (
            END
            if "response" in state
            else "retrieve_policy"
            if state["search_policy"]
            else "compose"
        ),
    )
    graph.add_edge("retrieve_policy", "compose")
    graph.add_edge("compose", END)
    await recorder.start()
    try:
        result = await graph.compile().ainvoke(
            {"question": question}, config={"recursion_limit": 8}
        )
        response = result["response"].model_copy(update={"run_id": recorder.run_id})
    except Exception as exc:
        await recorder.finish(error=exc)
        raise
    await recorder.finish(response=response)
    return response
