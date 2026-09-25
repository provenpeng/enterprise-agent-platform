"""A fixed, auditable LangGraph route from question to tenant-scoped evidence."""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from typing import TypedDict

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.model import DiagnosticModel
from app.agent.trace import RunRecorder
from app.business.orders import OrderLookupTool
from app.schemas.business import OrderSnapshot
from app.schemas.diagnostic import DiagnoseResponse
from app.schemas.retrieval import SearchHit
from app.services.citations import attach_verified_citations
from app.services.errors import UpstreamUnavailable
from app.services.retrieval import search_knowledge_base

logger = logging.getLogger(__name__)
ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class DiagnosticState(TypedDict, total=False):
    question: str
    order_id: str
    search_policy: bool
    order: OrderSnapshot
    hits: list[SearchHit]
    response: DiagnoseResponse


@dataclass(frozen=True, kw_only=True)
class DiagnosticOptions:
    tenant_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    embedding_space_id: str
    explicit_order_id: str | None
    planning_timeout_seconds: float
    embedding_timeout_seconds: float
    generation_timeout_seconds: float


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


def _after_plan(state: DiagnosticState) -> str:
    return END if "response" in state else "lookup_order"


def _after_lookup(state: DiagnosticState) -> str:
    if "response" in state:
        return END
    return "retrieve_policy" if state["search_policy"] else "compose"


class DiagnosticWorkflow:
    """Own one request's dependencies while the graph topology stays fixed."""

    def __init__(
        self,
        db: AsyncSession,
        embeddings: Embeddings,
        model: DiagnosticModel,
        recorder: RunRecorder,
        options: DiagnosticOptions,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._model = model
        self._recorder = recorder
        self._options = options

    async def _plan(self, state: DiagnosticState) -> DiagnosticState:
        async with self._recorder.step(
            "plan", {"question": state["question"]}
        ) as trace:
            try:
                async with asyncio.timeout(self._options.planning_timeout_seconds):
                    call = await self._model.plan(state["question"])
            except Exception as exc:
                logger.warning("Diagnostic planning failed", exc_info=True)
                raise UpstreamUnavailable("Diagnostic planning is unavailable") from exc
            trace.usage = call.usage
            proposal = call.value
            order_id = self._options.explicit_order_id or proposal.order_id
            if order_id is None or not ORDER_ID_PATTERN.fullmatch(order_id):
                trace.output = {"status": "NEEDS_ORDER_ID"}
                return {
                    "response": DiagnoseResponse(
                        knowledge_base_id=self._options.knowledge_base_id,
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

    async def _lookup(self, state: DiagnosticState) -> DiagnosticState:
        async with self._recorder.step(
            "lookup_order", {"order_id": state["order_id"]}
        ) as trace:
            try:
                order = await OrderLookupTool(self._db, self._options.tenant_id).lookup(
                    state["order_id"]
                )
            except SQLAlchemyError as exc:
                logger.warning("Diagnostic order lookup failed", exc_info=True)
                raise UpstreamUnavailable("Order lookup is unavailable") from exc
            if order is None:
                trace.output = {"status": "ORDER_NOT_FOUND"}
                return {
                    "response": DiagnoseResponse(
                        knowledge_base_id=self._options.knowledge_base_id,
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

    async def _retrieve(self, state: DiagnosticState) -> DiagnosticState:
        order = state["order"]
        latest_reason = (
            order.refund_attempts[-1].reason_code if order.refund_attempts else None
        )
        query = f"{state['question']} {latest_reason or ''}".strip()
        async with self._recorder.step("retrieve_policy", {"query": query}) as trace:
            hits = await search_knowledge_base(
                self._db,
                self._embeddings,
                tenant_id=self._options.tenant_id,
                knowledge_base_id=self._options.knowledge_base_id,
                embedding_space_id=self._options.embedding_space_id,
                query=query,
                top_k=5,
                min_score=0.5,
                timeout_seconds=self._options.embedding_timeout_seconds,
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

    async def _compose(self, state: DiagnosticState) -> DiagnosticState:
        order = state["order"]
        hits = state.get("hits", [])
        async with self._recorder.step(
            "compose", {"candidate_chunk_ids": [str(hit.chunk_id) for hit in hits]}
        ) as trace:
            if not hits:
                response = self._business_only(order)
            else:
                try:
                    async with asyncio.timeout(
                        self._options.generation_timeout_seconds
                    ):
                        call = await self._model.explain(state["question"], order, hits)
                except Exception as exc:
                    logger.warning("Diagnostic explanation failed", exc_info=True)
                    raise UpstreamUnavailable(
                        "Diagnostic explanation is unavailable"
                    ) from exc
                trace.usage = call.usage
                draft = call.value
                cited = attach_verified_citations(
                    draft.answer, draft.cited_chunk_ids, hits
                )
                if cited is None:
                    logger.info("Diagnostic explanation lacked valid policy citations")
                    response = self._business_only(order)
                else:
                    answer, citations = cited
                    response = DiagnoseResponse(
                        knowledge_base_id=self._options.knowledge_base_id,
                        status="ANSWERED",
                        answer=answer,
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

    def _business_only(self, order: OrderSnapshot) -> DiagnoseResponse:
        return DiagnoseResponse(
            knowledge_base_id=self._options.knowledge_base_id,
            status="BUSINESS_FACTS_ONLY",
            answer=_business_facts(order),
            order=order,
            citations=[],
        )

    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(DiagnosticState)
        graph.add_node("plan", self._plan)
        graph.add_node("lookup_order", self._lookup)
        graph.add_node("retrieve_policy", self._retrieve)
        graph.add_node("compose", self._compose)
        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", _after_plan)
        graph.add_conditional_edges("lookup_order", _after_lookup)
        graph.add_edge("retrieve_policy", "compose")
        graph.add_edge("compose", END)
        return graph.compile()

    async def run(self, question: str) -> DiagnoseResponse:
        """Run at most four graph nodes, with no model-selected tool execution."""
        await self._recorder.start()
        try:
            result = await self._build_graph().ainvoke(
                {"question": question}, config={"recursion_limit": 8}
            )
            response = result["response"].model_copy(
                update={"run_id": self._recorder.run_id}
            )
        except Exception as exc:
            await self._recorder.finish(error=exc)
            raise
        await self._recorder.finish(response=response)
        return response
