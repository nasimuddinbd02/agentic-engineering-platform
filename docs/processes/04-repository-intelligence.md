# Process 4 — Repository Intelligence

**How the agent answers: where is the code relevant to this issue?**

An LLM cannot read a large repository, and it should not try. This process
turns "orders fail to cancel" into three or four files worth reading.

---

## Retrieval is built in levels

The design document is explicit: **do not begin with vector search.** Levels 1–3
need no index, no embeddings and no model, and they solve most of the problem.

```mermaid
flowchart TD
    L1["<b>Level 1 — lexical</b><br/>ripgrep / regex<br/><i>shipped, default</i>"]
    L2["<b>Level 2 — symbols</b><br/>where is X defined, who calls it<br/><i>shipped, default</i>"]
    L3["<b>Level 3 — dependencies</b><br/>imports and dependents<br/><i>shipped, default</i>"]
    L4["<b>Level 4 — vectors</b><br/>embeddings + pgvector<br/><i>built, switched off</i>"]
    L5["<b>Level 5 — hybrid</b><br/>fuse all + rerank<br/><i>built, active where indexed</i>"]

    L1 --> L2 --> L3 --> L4 --> L5

    style L1 fill:#16a34a,color:#fff
    style L2 fill:#16a34a,color:#fff
    style L3 fill:#16a34a,color:#fff
    style L4 fill:#6b7280,color:#fff
    style L5 fill:#2563eb,color:#fff
```

Level 4 is off because it needs an embedder. Turning it on is a migration plus
configuration — no code above `retrieval/search/` changes.

---

## What the agent actually does

The repository agent has six read-only tools and drives its own investigation:

```mermaid
sequenceDiagram
    participant A as repository agent
    participant T as tools
    participant R as repo (read-only)

    A->>T: search_code("CancelOrder")
    T->>R: ripgrep
    R-->>A: OrdersController.cs:34, OrderService.cs:47, ...

    A->>T: read_file("Services/OrderService.cs")
    R-->>A: numbered source

    A->>T: read_file("Services/PaymentService.cs")
    R-->>A: RefundOrder throws on a duplicate

    Note over A: hypothesis formed
    A-->>A: return context package (JSON)
```

Note the *directory it reads*: at this stage there is no worktree yet, so the
agent reads the developer's checkout — **read-only**. Nothing can write until
the implementation node creates the isolated worktree.

The output is a deliberately small package:

```json
{
  "relevant_files": ["...OrderService.cs", "...PaymentService.cs", "...Tests.cs"],
  "findings": ["CancelOrder refunds unconditionally, so a second call throws"],
  "entry_point": "src/OrderService/Services/OrderService.cs"
}
```

The prompt asks for 3–6 files, not everything that matched: the implementation
agent pays for every file named here.

---

## The tools

| Tool | Answers | Implementation |
|---|---|---|
| `search_code` | where does this text appear? | ripgrep, falling back to a bounded Python walk |
| `read_file` | what does this code do? | line-numbered, range-selectable |
| `list_directory` | how is this laid out? | build output filtered |
| `find_symbol` | where is `X` **defined**? | regex symbol index |
| `find_references` | who **calls** `X`? | word-boundary search minus definitions |
| `get_dependencies` | what does this file import, and who imports it? | usings / imports + type references |

`search_code` never hard-depends on ripgrep: if `rg` is absent it uses a pure
Python scan, so the platform has no invisible external requirement.

---

## Symbols without a language server

A regex symbol index, shared by the search tools *and* the RAG chunker, so
"what is a symbol" has exactly one definition
([retrieval/ingestion/parser.py](../../retrieval/ingestion/parser.py)).

```mermaid
flowchart LR
    F["OrderService.cs"] --> P["parse_symbols()"]
    P --> C["class OrderManagementService<br/>lines 30-78"]
    P --> M["method CancelOrder<br/>lines 47-70"]
    P --> I["interface IOrderService<br/>lines 20-28"]
```

Supported: C#, Python, TypeScript/JavaScript. It brace-matches to find where a
symbol ends and filters out control-flow keywords, so `if (...)` never appears
as a method. Approximate by design — a language server per language would be a
large dependency for a marginal gain at this scale.

---

## The RAG pipeline (levels 4–5)

```bash
python -m scripts.index_repository --path ./.sandbox/order-service --query "cancel order"
```

```mermaid
flowchart LR
    S["scan<br/><i>skip bin/obj/node_modules</i>"] --> P["parse symbols"]
    P --> CH["chunk<br/><i>symbol-aligned</i>"]
    CH --> E{"embedder<br/>configured?"}
    E -->|no| DB[("code_chunks<br/>embedding = NULL")]
    E -->|yes| V["embed"] --> DB
```

**Chunks are symbol-aligned, not fixed windows.** A chunk is a class or a
method, so a retrieved chunk is something a reviewer recognises and the citation
`OrderService.cs:47-70 (CancelOrder)` means something. Files with no extractable
symbols fall back to overlapping line windows.

### Hybrid retrieval and reranking

```mermaid
flowchart TD
    Q["issue text"] --> L["BM25 lexical"]
    Q --> SY["symbol match"]
    Q --> VE["vector<br/><i>if enabled</i>"]
    L --> RRF["reciprocal rank fusion"]
    SY --> RRF
    VE --> RRF
    RRF --> RR["reranker"]
    RR --> OUT["final context"]

    style RRF fill:#2563eb,color:#fff
    style RR fill:#7c3aed,color:#fff
```

Fusion is **reciprocal rank fusion**, which combines rankings rather than
scores — so BM25 and cosine similarity can be merged without tuning weights per
corpus.

The reranker then applies what actually matters when ranking code for a bug fix:

| Signal | Weight |
|---|---|
| symbol name matches the query | **+2.0** |
| path contains a query term | +1.0 |
| service / controller / handler / repository | +0.5 |
| method or function | +0.3 |
| looks like a test file | **−0.4** |
| chunk under 3 lines | −0.3 |

That test-file penalty is load-bearing. BM25 favours short documents, so a
four-line test method routinely outranks the service it exercises. A unit test
pins both behaviours: lexical *recalls* both, the reranker *orders* production
code first.

---

## Where the code lives

| Concern | File |
|---|---|
| search tools | `tools/repository/` |
| symbol parsing | `retrieval/ingestion/parser.py` |
| scan / chunk / index | `retrieval/ingestion/` |
| BM25 | `retrieval/search/lexical.py` |
| vectors | `retrieval/search/vector.py` |
| fusion | `retrieval/search/hybrid.py` |
| reranking | `retrieval/search/reranker.py` |
| enabling pgvector | `persistence/migrations/0002_pgvector.sql` |

**Tests:** `tests/unit/test_retrieval.py`
