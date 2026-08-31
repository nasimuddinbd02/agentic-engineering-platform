"""Retrieval tests (section 12) - the progressive levels, on real C# source."""

from __future__ import annotations

from pathlib import Path

import pytest

from persistence.models import CodeChunk
from retrieval.ingestion.chunker import chunk_file
from retrieval.ingestion.parser import language_of, parse_symbols
from retrieval.ingestion.scanner import ScannedFile, detect_languages, scan_repository
from retrieval.search.hybrid import HybridRetriever
from retrieval.search.lexical import LexicalIndex, tokenize
from retrieval.search.vector import cosine_similarity

SAMPLE = Path(__file__).resolve().parents[2] / "sample-repo" / "order-service"

CSHARP = """namespace OrderService.Services;

public interface IOrderService
{
    CancellationResult CancelOrder(Guid id);
}

public class OrderManagementService : IOrderService
{
    private readonly IOrderRepository _repository;

    public CancellationResult CancelOrder(Guid id)
    {
        var order = _repository.GetById(id);
        return CancellationResult.Cancelled(id);
    }
}
"""


# ---------------------------------------------------------------------- parser


def test_language_detection() -> None:
    assert language_of("src/A.cs") == "csharp"
    assert language_of("app/main.py") == "python"
    assert language_of("web/page.tsx") == "typescript"
    assert language_of("notes.rst") == "text"


def test_csharp_symbols_are_extracted() -> None:
    symbols = parse_symbols("Services/OrderService.cs", CSHARP)
    names = {symbol.name for symbol in symbols}
    assert {"IOrderService", "OrderManagementService", "CancelOrder"} <= names

    service = next(s for s in symbols if s.name == "OrderManagementService")
    assert service.kind == "class"
    assert service.end_line > service.start_line


def test_control_flow_keywords_are_not_symbols() -> None:
    source = "public class A\n{\n    void M()\n    {\n        if (x)\n        {\n        }\n    }\n}\n"
    names = {symbol.name for symbol in parse_symbols("A.cs", source)}
    assert "if" not in names


def test_python_symbols_are_extracted() -> None:
    source = "class Thing:\n    def method(self):\n        return 1\n\n\ndef free():\n    pass\n"
    symbols = parse_symbols("a.py", source)
    assert {s.name for s in symbols} == {"Thing", "method", "free"}


# --------------------------------------------------------------------- chunker


def test_chunks_align_to_symbols() -> None:
    file = ScannedFile(
        path=Path("Services/OrderService.cs"),
        relative_path="Services/OrderService.cs",
        language="csharp",
        content=CSHARP,
    )
    chunks = chunk_file(file)
    assert chunks
    assert any(chunk.symbol_name == "CancelOrder" for chunk in chunks)
    assert all(chunk.content.strip() for chunk in chunks)
    assert all(chunk.end_line >= chunk.start_line for chunk in chunks)


def test_files_without_symbols_fall_back_to_windows() -> None:
    file = ScannedFile(
        path=Path("notes.md"),
        relative_path="notes.md",
        language="markdown",
        content="\n".join(f"line {index}" for index in range(200)),
    )
    chunks = chunk_file(file)
    assert len(chunks) > 1
    assert all(chunk.symbol_name is None for chunk in chunks)


# --------------------------------------------------------------------- scanner


def test_scanner_skips_build_output() -> None:
    files = scan_repository(SAMPLE)
    assert files, "the sample repository should contain indexable files"
    assert all("obj" not in file.relative_path.split("/") for file in files)
    assert all("bin" not in file.relative_path.split("/") for file in files)
    assert "csharp" in detect_languages(files)


# --------------------------------------------------------------------- lexical


def test_tokenizer_splits_camel_case() -> None:
    tokens = tokenize("CancelOrder")
    assert "cancelorder" in tokens
    assert "cancel" in tokens
    assert "order" in tokens


def make_chunk(identifier: str, path: str, symbol: str | None, content: str) -> CodeChunk:
    return CodeChunk(
        id=identifier,
        repository_id="repo-1",
        file_path=path,
        symbol_name=symbol,
        symbol_kind="method" if symbol else None,
        language="csharp",
        start_line=1,
        end_line=20,
        content=content,
    )


@pytest.fixture
def chunks() -> list[CodeChunk]:
    return [
        make_chunk("c1", "Services/OrderService.cs", "CancelOrder", CSHARP),
        make_chunk("c2", "Services/PaymentService.cs", "RefundOrder", "public void RefundOrder() { }"),
        make_chunk("c3", "Controllers/HomeController.cs", "Index", "public IActionResult Index() { }"),
        make_chunk(
            "c4",
            "Tests/OrderServiceTests.cs",
            "CancelOrder_Works",
            "public void CancelOrder_Works() { }",
        ),
    ]


def test_lexical_search_recalls_the_relevant_chunks(chunks: list[CodeChunk]) -> None:
    """BM25 is a recall layer.

    It favours short documents, so the small test chunk can outrank the service
    it exercises. Ordering production code above tests is the reranker's job -
    see ``test_hybrid_ranks_production_code_above_tests``.
    """
    results = LexicalIndex(chunks).search("cancel order", limit=3)
    paths = [result.chunk.file_path for result in results]
    assert "Services/OrderService.cs" in paths
    assert "Tests/OrderServiceTests.cs" in paths


def test_lexical_search_returns_nothing_for_an_unrelated_query(chunks: list[CodeChunk]) -> None:
    assert LexicalIndex(chunks).search("kubernetes ingress zzzz") == []


# ---------------------------------------------------------------------- hybrid


async def test_hybrid_ranks_production_code_above_tests(chunks: list[CodeChunk]) -> None:
    results = await HybridRetriever(chunks).search("cancel order", limit=4)
    assert results
    paths = [result.chunk.file_path for result in results]
    assert paths[0].endswith("OrderService.cs")
    assert paths.index("Services/OrderService.cs") < paths.index("Tests/OrderServiceTests.cs")


async def test_hybrid_result_has_a_citation(chunks: list[CodeChunk]) -> None:
    results = await HybridRetriever(chunks).search("refund", limit=1)
    assert ":" in results[0].citation


async def test_symbol_match_contributes_a_source(chunks: list[CodeChunk]) -> None:
    results = await HybridRetriever(chunks).search("CancelOrder", limit=4)
    assert "symbol" in results[0].sources


# ---------------------------------------------------------------------- vector


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_vector_index_is_disabled_without_embeddings(chunks: list[CodeChunk]) -> None:
    from retrieval.search.vector import VectorIndex

    assert not VectorIndex(chunks).enabled
