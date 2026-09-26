"""Verify benchmark labels, strict scoring and the API runner contract."""

import json
import uuid
from pathlib import Path

import httpx
import pytest
import tiktoken
from langchain_core.embeddings import Embeddings

from app.evaluation.benchmark import (
    BenchmarkDataset,
    assess_quality_gate,
    benchmark_metrics,
    citations_match,
    compare_baseline,
    corpus_files,
    load_benchmark,
    load_quality_profile,
    relevant_rank,
)
from app.evaluation.runner import inspect_corpus, prepare_corpus, run_benchmark
from app.rag.embeddings import EMBEDDING_DIMENSIONS
from app.rag.processing import create_document_processor
from app.services.indexer import process_one_index_job

DATASET = Path(__file__).resolve().parents[1] / "evals" / "benchmark_v1.json"
HOLDOUT = DATASET.with_name("benchmark_holdout_v1.json")
HOLDOUT_GATE = DATASET.with_name("holdout_quality_gate_v1.json")
SPACE_ID = "a" * 64


def test_benchmark_manifest_is_versioned_and_source_labeled() -> None:
    dataset, digest = load_benchmark(DATASET)
    assert dataset.version == "synthetic-policy-v1"
    assert len(digest) == 64
    assert len(dataset.corpus) == 3
    assert len(dataset.retrieval) == 12
    assert len(dataset.qa) == 8
    assert len(dataset.diagnostic) == 4
    assert len(dataset.authorization) == 3
    assert {case.category for case in dataset.retrieval} == {
        "direct",
        "paraphrase",
        "confusable",
        "no_answer",
    }
    assert {case.order_id for case in dataset.diagnostic} == {
        "DEMO-WINDOW",
        "DEMO-AMOUNT",
        "DEMO-GATEWAY",
        "DEMO-SUCCESS",
    }


def test_holdout_reuses_frozen_corpus_with_unseen_cases_and_explicit_gate(
    tmp_path: Path,
) -> None:
    training, _ = load_benchmark(DATASET)
    holdout, _ = load_benchmark(HOLDOUT)
    assert holdout.version != training.version
    assert holdout.corpus == training.corpus
    assert holdout.sources == training.sources
    for category in ("retrieval", "qa", "diagnostic", "authorization"):
        known = {case.id for case in getattr(training, category)}
        new = {case.id for case in getattr(holdout, category)}
        assert known.isdisjoint(new)
    profile, digest = load_quality_profile(HOLDOUT_GATE, holdout.version)
    assert len(digest) == 64
    assert all(value > 0 for value in profile.thresholds.values())
    with pytest.raises(ValueError, match="different dataset"):
        load_quality_profile(HOLDOUT_GATE, training.version)
    scores = dict.fromkeys(profile.thresholds, 1.0)
    assert assess_quality_gate(
        scores, min_score=0, regressions=[], thresholds=profile.thresholds
    )["passed"]
    scores["qa_citation_source_accuracy"] = 0.8
    gate = assess_quality_gate(
        scores, min_score=0, regressions=[], thresholds=profile.thresholds
    )
    assert gate["below_threshold"] == ["qa_citation_source_accuracy"]
    assert not gate["passed"]
    invalid = json.loads(HOLDOUT_GATE.read_text(encoding="utf-8"))
    invalid["thresholds"]["qa_citation_source_accuracy"] = 0
    path = tmp_path / "invalid-gate.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="nonzero threshold"):
        load_quality_profile(path, holdout.version)


@pytest.mark.parametrize("backend", ["manual", "langchain"])
def test_corpus_labels_survive_both_document_processors(backend: str) -> None:
    dataset, _ = load_benchmark(DATASET)
    encoding = tiktoken.get_encoding("cl100k_base")
    for document, path in corpus_files(DATASET, dataset):
        processor = create_document_processor(
            backend=backend,
            file_type="text/markdown",
            target_tokens=400,
            max_tokens=600,
            token_counter=lambda value: len(encoding.encode(value)),
        )
        chunks = processor.process(path.read_text(encoding="utf-8"))
        observed = {chunk.section_path for chunk in chunks}
        expected = {
            label.section_path
            for label in dataset.sources.values()
            if label.filename == document.filename
        }
        assert expected <= observed


def test_manifest_rejects_unlabeled_cases_and_corpus_drift(tmp_path: Path) -> None:
    dataset, _ = load_benchmark(DATASET)
    invalid = dataset.model_dump()
    invalid["retrieval"][0]["relevant_source_ids"] = ["nonexistent"]
    with pytest.raises(ValueError, match="undefined source"):
        BenchmarkDataset.model_validate(invalid)

    copied = tmp_path / "benchmark.json"
    copied.write_bytes(DATASET.read_bytes())
    with pytest.raises(FileNotFoundError):
        load_benchmark(copied)


def test_scoring_requires_ranked_and_exclusively_correct_citations() -> None:
    source_by_chunk = {"a": "refund", "b": "expense", "c": "irrelevant"}
    assert (
        relevant_rank(
            [{"chunk_id": "c"}, {"chunk_id": "a"}], ("refund",), source_by_chunk
        )
        == 2
    )
    assert relevant_rank([{"chunk_id": "c"}], ("refund",), source_by_chunk) is None
    assert citations_match(
        [{"source": {"chunk_id": "a"}}, {"source": {"chunk_id": "b"}}],
        ("refund", "expense"),
        source_by_chunk,
    )
    assert not citations_match(
        [{"source": {"chunk_id": "a"}}, {"source": {"chunk_id": "c"}}],
        ("refund",),
        source_by_chunk,
    )
    assert not citations_match(
        [{"source": {"chunk_id": "a"}}],
        ("refund", "expense"),
        source_by_chunk,
    )


def test_metrics_separate_retrieval_qa_and_diagnostic_failures() -> None:
    metrics = benchmark_metrics(
        [
            {"expect_no_hits": False, "rank": 1},
            {"expect_no_hits": False, "rank": 4},
            {"expect_no_hits": False, "rank": None},
            {"expect_no_hits": True, "no_hits": False},
        ],
        [
            {"expect_abstain": False, "citation_source": True},
            {"expect_abstain": False, "citation_source": False},
            {"expect_abstain": True, "abstained": True},
        ],
        [
            {
                "order_lookup": True,
                "reason_code": True,
                "policy_route": False,
                "status": False,
                "citation_source": False,
            }
        ],
        [{"blocked": False}, {"blocked": True}],
    )
    assert metrics["retrieval_recall_at_1"] == pytest.approx(1 / 3)
    assert metrics["retrieval_recall_at_5"] == pytest.approx(2 / 3)
    assert metrics["retrieval_mrr_at_5"] == pytest.approx(1.25 / 3)
    assert metrics["retrieval_no_hit_rate"] == 0
    assert metrics["qa_citation_source_accuracy"] == 0.5
    assert metrics["qa_abstention_accuracy"] == 1
    assert metrics["diagnostic_policy_route_accuracy"] == 0
    assert metrics["tenant_isolation_accuracy"] == 0.5


class BenchmarkAPI:
    def __init__(self, dataset: BenchmarkDataset, *, space_id: str = SPACE_ID) -> None:
        self.dataset = dataset
        self.space_id = space_id
        self.kb_id = uuid.uuid4()
        self.document_ids = {
            document.filename: str(uuid.uuid4()) for document in dataset.corpus
        }
        self.chunk_ids = {source_id: str(uuid.uuid4()) for source_id in dataset.sources}
        self.trace_cases: dict[str, object] = {}
        self.uploads = 0
        self.extra_document = False
        self.bad_citation = False
        self.search_error = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.headers.get("authorization") == "Bearer outsider":
            return httpx.Response(404)
        if request.method == "POST" and path == "/api/v1/knowledge-bases":
            return httpx.Response(201, json={"id": str(self.kb_id)})
        if request.method == "POST" and path.endswith("/documents"):
            filename = self.dataset.corpus[self.uploads].filename
            self.uploads += 1
            return httpx.Response(201, json={"id": self.document_ids[filename]})
        if request.method == "GET" and path.endswith("/documents"):
            documents = [
                {
                    "id": self.document_ids[document.filename],
                    "filename": document.filename,
                    "checksum": document.sha256,
                    "status": "READY",
                    "active_index_version": 1,
                }
                for document in self.dataset.corpus
            ]
            if self.extra_document:
                documents.append(
                    {**documents[0], "id": str(uuid.uuid4()), "filename": "extra.md"}
                )
            offset = int(request.url.params.get("offset", 0))
            return httpx.Response(200, json=documents[offset : offset + 100])
        for document in self.dataset.corpus:
            document_id = self.document_ids[document.filename]
            if path == f"/api/v1/documents/{document_id}":
                return httpx.Response(200, json={"status": "READY"})
            if path == f"/api/v1/documents/{document_id}/index-jobs":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "index_version": 1,
                            "status": "SUCCEEDED",
                            "embedding_space_id": self.space_id,
                            "embedding_model": "test-embedding",
                            "processing_backend": "manual",
                            "processing_version": "v1",
                        }
                    ],
                )
            if path == f"/api/v1/documents/{document_id}/chunks":
                chunks = [
                    {
                        "id": self.chunk_ids[source_id],
                        "section_path": list(label.section_path),
                    }
                    for source_id, label in self.dataset.sources.items()
                    if label.filename == document.filename
                ]
                offset = int(request.url.params.get("offset", 0))
                return httpx.Response(200, json=chunks[offset : offset + 100])
        if path.endswith("/search"):
            query = json.loads(request.content)["query"]
            case = next(case for case in self.dataset.retrieval if case.query == query)
            if self.search_error and case.id == "refund_window_direct":
                return httpx.Response(503)
            hits = (
                []
                if case.expect_no_hits
                else [{"chunk_id": self.chunk_ids[case.relevant_source_ids[0]]}]
            )
            return httpx.Response(200, json={"hits": hits})
        if path.endswith("/ask"):
            query = json.loads(request.content)["query"]
            case = next(case for case in self.dataset.qa if case.query == query)
            citations = [
                {
                    "source": {
                        "chunk_id": self.chunk_ids[
                            "expense_invoice"
                            if self.bad_citation and case.id == "qa_refund_window"
                            else source_id
                        ]
                    }
                }
                for source_id in case.required_source_ids
            ]
            return httpx.Response(
                200, json={"grounded": not case.expect_abstain, "citations": citations}
            )
        if path.endswith("/diagnose"):
            query = json.loads(request.content)["question"]
            case = next(
                case for case in self.dataset.diagnostic if case.question == query
            )
            run_id = str(uuid.uuid4())
            self.trace_cases[run_id] = case
            return httpx.Response(
                200,
                json={
                    "run_id": run_id,
                    "status": case.expected_status,
                    "order": {
                        "order_id": case.order_id,
                        "refund_attempts": [{"reason_code": case.expected_reason_code}],
                    },
                    "citations": [
                        {"source": {"chunk_id": self.chunk_ids[source_id]}}
                        for source_id in case.required_source_ids
                    ],
                },
            )
        if path.startswith("/api/v1/agent-runs/"):
            case = self.trace_cases[path.rsplit("/", 1)[-1]]
            return httpx.Response(
                200,
                json={
                    "model_name": "test-chat",
                    "total_tokens": 10,
                    "steps": [
                        {"name": "retrieve_policy"}
                        if case.expect_policy_search
                        else {"name": "lookup_order"}
                    ],
                },
            )
        return httpx.Response(404)


@pytest.mark.asyncio
async def test_runner_prepares_and_scores_exact_corpus_without_models() -> None:
    dataset, digest = load_benchmark(DATASET)
    api = BenchmarkAPI(dataset)
    transport = httpx.MockTransport(api)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client,
        httpx.AsyncClient(
            transport=transport,
            base_url="http://benchmark",
            headers={"Authorization": "Bearer outsider"},
        ) as outsider_client,
    ):
        knowledge_base_id = await prepare_corpus(
            client, DATASET, dataset, timeout_seconds=1
        )
        assert api.uploads == len(dataset.corpus)
        report = await run_benchmark(
            client,
            outsider_client,
            knowledge_base_id,
            dataset,
            digest,
            embedding_space_id=SPACE_ID,
            model_config={"embedding_space_id": SPACE_ID},
        )
        assert set(report["metrics"].values()) == {1.0}
        assert report["reported_diagnostic_model_tokens"] == 40
        assert report["observed_diagnostic_models"] == ["test-chat"]
        assert len(report["indexes"]) == 3

        api.bad_citation = True
        api.search_error = True
        degraded = await run_benchmark(
            client,
            outsider_client,
            knowledge_base_id,
            dataset,
            digest,
            embedding_space_id=SPACE_ID,
            model_config={"embedding_space_id": SPACE_ID},
        )
        assert degraded["metrics"]["qa_citation_source_accuracy"] == pytest.approx(
            5 / 6
        )
        assert degraded["metrics"]["retrieval_recall_at_5"] == pytest.approx(9 / 10)
        assert degraded["retrieval_cases"][0]["error"] == "HTTP_503"

        api.space_id = "b" * 64
        with pytest.raises(ValueError, match="Active index space differs"):
            await inspect_corpus(client, knowledge_base_id, dataset, SPACE_ID)
        api.space_id = SPACE_ID
        api.extra_document = True
        with pytest.raises(ValueError, match="corpus differs"):
            await inspect_corpus(client, knowledge_base_id, dataset, SPACE_ID)


def test_baseline_comparison_requires_same_dataset_and_detects_regression(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"dataset_sha256": "same", "metrics": {"retrieval_recall_at_5": 1.0}}
        ),
        encoding="utf-8",
    )
    report = {"dataset_sha256": "same", "metrics": {"retrieval_recall_at_5": 0.8}}
    assert compare_baseline(report, baseline, 0.05) == ["retrieval_recall_at_5"]
    assert report["baseline_comparison"]["metric_deltas"] == {
        "retrieval_recall_at_5": pytest.approx(-0.2)
    }
    report["dataset_sha256"] = "changed"
    with pytest.raises(ValueError, match="different dataset"):
        compare_baseline(report, baseline, 0.05)


def test_tenant_isolation_is_mandatory_even_when_quality_threshold_is_zero() -> None:
    gate = assess_quality_gate(
        {"tenant_isolation_accuracy": 2 / 3, "retrieval_recall_at_5": 1},
        min_score=0,
        regressions=[],
    )
    assert gate["passed"] is False
    assert gate["mandatory_failures"] == ["tenant_isolation_accuracy"]


class FixedIndexEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@pytest.mark.asyncio
async def test_corpus_preflight_uses_real_published_index(api_client) -> None:
    client, _, sessions, settings = api_client
    dataset, _ = load_benchmark(DATASET)
    created = await client.post(
        "/api/v1/knowledge-bases", json={"name": "Benchmark preflight"}
    )
    assert created.status_code == 201
    knowledge_base_id = uuid.UUID(created.json()["id"])
    for document, path in corpus_files(DATASET, dataset):
        uploaded = await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
            files={"file": (document.filename, path.read_bytes(), "text/markdown")},
        )
        assert uploaded.status_code == 201, uploaded.text
    for _ in dataset.corpus:
        assert await process_one_index_job(
            sessions, settings, FixedIndexEmbeddings(), len
        )

    source_by_chunk, indexes = await inspect_corpus(
        client, knowledge_base_id, dataset, settings.embedding_space_id
    )
    assert set(source_by_chunk.values()) == set(dataset.sources)
    assert len(indexes) == len(dataset.corpus)
