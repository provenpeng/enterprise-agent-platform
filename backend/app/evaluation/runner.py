"""Run the benchmark against the public API and verify its exact corpus."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, perf_counter

import httpx

from app.evaluation.benchmark import (
    BenchmarkDataset,
    benchmark_metrics,
    citations_match,
    corpus_files,
    relevant_rank,
    score_diagnostic,
)


async def _pages(client: httpx.AsyncClient, path: str) -> list[dict]:
    items: list[dict] = []
    while True:
        response = await client.get(path, params={"limit": 100, "offset": len(items)})
        response.raise_for_status()
        page = response.json()
        items.extend(page)
        if len(page) < 100:
            return items


async def inspect_corpus(
    client: httpx.AsyncClient,
    knowledge_base_id: uuid.UUID,
    dataset: BenchmarkDataset,
    expected_space_id: str,
) -> tuple[dict[str, str], list[dict]]:
    """Refuse scoring if documents, indexes, or labeled sections have drifted."""
    documents = await _pages(
        client, f"/api/v1/knowledge-bases/{knowledge_base_id}/documents"
    )
    expected = {document.filename: document.sha256 for document in dataset.corpus}
    actual = {document["filename"]: document["checksum"] for document in documents}
    if len(actual) != len(documents) or actual != expected:
        raise ValueError("Knowledge base corpus differs from the benchmark manifest")

    source_by_chunk: dict[str, str] = {}
    index_manifest: list[dict] = []
    observed_sources: set[str] = set()
    for document in documents:
        if document["status"] != "READY" or document["active_index_version"] is None:
            raise ValueError(f"Document is not indexed: {document['filename']}")
        document_id = document["id"]
        jobs_response = await client.get(f"/api/v1/documents/{document_id}/index-jobs")
        jobs_response.raise_for_status()
        active = next(
            (
                job
                for job in jobs_response.json()
                if job["index_version"] == document["active_index_version"]
            ),
            None,
        )
        if (
            active is None
            or active["status"] != "SUCCEEDED"
            or active["embedding_space_id"] != expected_space_id
        ):
            raise ValueError(f"Active index space differs: {document['filename']}")
        index_manifest.append(
            {
                "filename": document["filename"],
                "checksum": document["checksum"],
                "index_version": active["index_version"],
                "processing_backend": active["processing_backend"],
                "processing_version": active["processing_version"],
                "embedding_model": active["embedding_model"],
                "embedding_space_id": active["embedding_space_id"],
            }
        )
        chunks = await _pages(client, f"/api/v1/documents/{document_id}/chunks")
        if not chunks:
            raise ValueError(f"Active index has no chunks: {document['filename']}")
        for chunk in chunks:
            for source_id, label in dataset.sources.items():
                if (
                    label.filename == document["filename"]
                    and list(label.section_path) == chunk["section_path"]
                ):
                    source_by_chunk[chunk["id"]] = source_id
                    observed_sources.add(source_id)
    missing = dataset.sources.keys() - observed_sources
    if missing:
        raise ValueError(
            f"Labeled sections missing from active index: {sorted(missing)}"
        )
    return source_by_chunk, sorted(index_manifest, key=lambda item: item["filename"])


async def prepare_corpus(
    client: httpx.AsyncClient,
    dataset_path: Path,
    dataset: BenchmarkDataset,
    *,
    timeout_seconds: float,
) -> uuid.UUID:
    """Create a fresh isolated knowledge base and wait for worker publication."""
    response = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"Benchmark {dataset.version} {uuid.uuid4().hex[:8]}"},
    )
    response.raise_for_status()
    knowledge_base_id = uuid.UUID(response.json()["id"])
    document_ids = []
    for document, path in corpus_files(dataset_path, dataset):
        response = await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
            files={"file": (document.filename, path.read_bytes(), "text/markdown")},
        )
        response.raise_for_status()
        document_ids.append(response.json()["id"])
    deadline = monotonic() + timeout_seconds
    remaining = set(document_ids)
    while remaining:
        for document_id in tuple(remaining):
            response = await client.get(f"/api/v1/documents/{document_id}")
            response.raise_for_status()
            status = response.json()["status"]
            if status == "READY":
                remaining.remove(document_id)
            elif status == "FAILED":
                raise RuntimeError(f"Benchmark document indexing failed: {document_id}")
        if remaining:
            if monotonic() >= deadline:
                raise TimeoutError(
                    f"Benchmark indexing timed out: {len(remaining)} pending"
                )
            await asyncio.sleep(min(2, max(0, deadline - monotonic())))
    return knowledge_base_id


async def _post_case(
    client: httpx.AsyncClient, path: str, payload: dict
) -> tuple[dict | None, str | None, int]:
    start = perf_counter()
    try:
        response = await client.post(path, json=payload)
    except httpx.HTTPError as exc:
        return None, type(exc).__name__, round((perf_counter() - start) * 1000)
    duration = round((perf_counter() - start) * 1000)
    if response.status_code >= 400:
        return None, f"HTTP_{response.status_code}", duration
    return response.json(), None, duration


def _latency_summary(cases: list[dict]) -> dict[str, int]:
    times = sorted(case["latency_ms"] for case in cases)
    return {
        "p50": times[(len(times) - 1) // 2],
        "p95": times[(95 * len(times) + 99) // 100 - 1],
    }


async def run_benchmark(
    client: httpx.AsyncClient,
    outsider_client: httpx.AsyncClient,
    knowledge_base_id: uuid.UUID,
    dataset: BenchmarkDataset,
    dataset_sha256: str,
    *,
    embedding_space_id: str,
    model_config: dict,
) -> dict:
    source_by_chunk, index_manifest = await inspect_corpus(
        client, knowledge_base_id, dataset, embedding_space_id
    )
    base = f"/api/v1/knowledge-bases/{knowledge_base_id}"
    retrieval_results: list[dict] = []
    qa_results: list[dict] = []
    diagnostic_results: list[dict] = []
    authorization_results: list[dict] = []
    reported_tokens = 0
    unreported_runs = 0
    diagnostic_models: set[str] = set()

    for case in dataset.retrieval:
        body, error, latency = await _post_case(
            client,
            f"{base}/search",
            {"query": case.query, "top_k": 5, "min_score": case.min_score},
        )
        hits = body["hits"] if body else []
        retrieval_results.append(
            {
                "id": case.id,
                "category": case.category,
                "expect_no_hits": case.expect_no_hits,
                "rank": relevant_rank(hits, case.relevant_source_ids, source_by_chunk)
                if not error
                else None,
                "no_hits": body is not None and not hits,
                "hit_chunk_ids": [hit["chunk_id"] for hit in hits],
                "latency_ms": latency,
                "error": error,
            }
        )

    for case in dataset.qa:
        body, error, latency = await _post_case(
            client, f"{base}/ask", {"query": case.query}
        )
        citations = body["citations"] if body else []
        qa_results.append(
            {
                "id": case.id,
                "expect_abstain": case.expect_abstain,
                "citation_source": bool(body and body["grounded"])
                and citations_match(
                    citations, case.required_source_ids, source_by_chunk
                )
                if not case.expect_abstain
                else False,
                "abstained": bool(body and not body["grounded"] and not citations),
                "cited_chunk_ids": [item["source"]["chunk_id"] for item in citations],
                "latency_ms": latency,
                "error": error,
            }
        )

    for case in dataset.diagnostic:
        body, error, latency = await _post_case(
            client,
            f"{base}/diagnose",
            {"question": case.question, "order_id": case.order_id},
        )
        steps: list[dict] = []
        if body and not body.get("run_id"):
            error = "MISSING_RUN_ID"
        if body and body.get("run_id"):
            trace_start = perf_counter()
            try:
                trace = await client.get(f"/api/v1/agent-runs/{body['run_id']}")
            except httpx.HTTPError as exc:
                error = f"TRACE_{type(exc).__name__}"
            else:
                if trace.status_code >= 400:
                    error = f"TRACE_HTTP_{trace.status_code}"
                else:
                    run = trace.json()
                    steps = run["steps"]
                    diagnostic_models.add(run["model_name"])
                    if run["total_tokens"] is None:
                        unreported_runs += 1
                    else:
                        reported_tokens += run["total_tokens"]
            latency += round((perf_counter() - trace_start) * 1000)
        scores = (
            score_diagnostic(case, body, steps, source_by_chunk)
            if body and not error
            else dict.fromkeys(
                (
                    "order_lookup",
                    "reason_code",
                    "policy_route",
                    "status",
                    "citation_source",
                ),
                False,
            )
        )
        diagnostic_results.append(
            {"id": case.id, **scores, "latency_ms": latency, "error": error}
        )

    for case in dataset.authorization:
        payload = (
            {"question": case.query, "order_id": case.order_id}
            if case.endpoint == "diagnose"
            else {"query": case.query}
        )
        start = perf_counter()
        try:
            response = await outsider_client.post(
                f"{base}/{case.endpoint}", json=payload
            )
        except httpx.HTTPError as exc:
            status_code = None
            error = type(exc).__name__
        else:
            status_code = response.status_code
            error = None
        authorization_results.append(
            {
                "id": case.id,
                "endpoint": case.endpoint,
                "blocked": status_code == 404,
                "status_code": status_code,
                "latency_ms": round((perf_counter() - start) * 1000),
                "error": error,
            }
        )

    return {
        "dataset_version": dataset.version,
        "dataset_sha256": dataset_sha256,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_base_id": str(knowledge_base_id),
        "expected_model_config": model_config,
        "indexes": index_manifest,
        "case_counts": {
            "retrieval_positive": sum(
                not case.expect_no_hits for case in dataset.retrieval
            ),
            "retrieval_no_answer": sum(
                case.expect_no_hits for case in dataset.retrieval
            ),
            "qa_positive": sum(not case.expect_abstain for case in dataset.qa),
            "qa_abstention": sum(case.expect_abstain for case in dataset.qa),
            "diagnostic": len(dataset.diagnostic),
            "authorization": len(dataset.authorization),
        },
        "metrics": benchmark_metrics(
            retrieval_results, qa_results, diagnostic_results, authorization_results
        ),
        "latency_ms": {
            "retrieval": _latency_summary(retrieval_results),
            "qa": _latency_summary(qa_results),
            "diagnostic": _latency_summary(diagnostic_results),
            "authorization": _latency_summary(authorization_results),
        },
        "reported_diagnostic_model_tokens": reported_tokens,
        "unreported_diagnostic_runs": unreported_runs,
        "observed_diagnostic_models": sorted(diagnostic_models),
        "retrieval_cases": retrieval_results,
        "qa_cases": qa_results,
        "diagnostic_cases": diagnostic_results,
        "authorization_cases": authorization_results,
    }
