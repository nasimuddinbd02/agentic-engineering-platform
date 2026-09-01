# AI Software Engineering Agent

An **engineering control plane around a coding-capable LLM**, implemented from
[docs/Requirements.md](docs/Requirements.md).

The model reasons. The platform decides what the model is allowed to do, runs
the things whose answers must be trustworthy, records everything, and stops the
agent when it is no longer making progress.

```
Issue → Plan → Repository intelligence → Risk/Policy → Implementation
      → Tests → (fail → bounded debugging → retest) → Policy gate
      → Commit → CI → PR → Human approval
```

---

## What is actually built

| Capability | Where | Status |
|---|---|---|
| Agent orchestration (LangGraph) | [graph/workflow.py](graph/workflow.py) | working |
| Stateful execution + checkpointing | [graph/state.py](graph/state.py), [agents/supervisor.py](agents/supervisor.py) | working |
| Tool calling with three gates | [agents/base.py](agents/base.py) | working |
| Repository search (lexical/symbol/dependency) | [tools/repository/](tools/repository/) | working |
| Codebase RAG (chunking, BM25, hybrid, rerank) | [retrieval/](retrieval/) | working; vectors off by default |
| Controlled code modification | [tools/filesystem/apply_patch.py](tools/filesystem/apply_patch.py) | working |
| Git worktrees | [tools/workspace.py](tools/workspace.py) | working |
| Automated testing | [tools/testing/test.py](tools/testing/test.py) | working (`dotnet test`) |
| Bounded debugging loop | [graph/routing.py](graph/routing.py), [graph/fingerprint.py](graph/fingerprint.py) | working |
| CI/CD integration | [providers/ci/](providers/ci/) | GitHub Actions adapter; `none` by default |
| Human-in-the-loop approval | [apps/api/routes/tasks.py](apps/api/routes/tasks.py) | working |
| Redis-backed coordination | [infrastructure/](infrastructure/) | working (+ in-process fallback) |
| PostgreSQL persistence & audit | [persistence/](persistence/) | working (+ SQLite fallback) |
| Horizontal worker scaling | [apps/worker/consumer.py](apps/worker/consumer.py) | working |
| Docker / Kubernetes | [infrastructure/docker/](infrastructure/docker/), [infrastructure/kubernetes/](infrastructure/kubernetes/) | manifests written, not deployed here |
| Evaluation benchmark | [tests/evaluation/](tests/evaluation/) | 2 fixtures + scorer |

---

## Quick start (no Docker required)

```bash
make install                 # venv + dependencies
cp .env.example .env         # then set LLM_API_KEY
make bootstrap               # schema + a sandbox copy of the sample repo
```

`.env.example` defaults to PostgreSQL and Redis. To run with neither:

```
DATABASE_URL=sqlite+aiosqlite:///./data/agent.db
REDIS_URL=memory://
```

Then, in three terminals:

```bash
make worker      # the agent worker
make api         # http://localhost:8000/docs
make web         # http://localhost:3000
```

> With `REDIS_URL=memory://` the queue lives inside one process, so run
> `make run-local` instead of `make api` + `make worker`. Everything else is
> identical; only Redis makes the two halves independently deployable.

Submit the sample issue and follow the live event stream:

```bash
make demo
```

**No API key?** Set `LLM_PROVIDER=scripted` and
`LLM_SCRIPT_PATH=./scripts/demo_script.yaml`. That replays a fixed set of agent
turns - including a *deliberately wrong* first fix - so you can watch the real
worktree, the real `dotnet test`, the debugging loop, the policy gate, the
commit and the approval without calling a model. It is a stand-in for the
model, not a simulation of the platform: every other component is the real one.

---

## The sample scenario (§43)

`sample-repo/order-service` is a .NET service with a **seeded defect**:
`OrderManagementService.CancelOrder` refunds unconditionally, so cancelling an
already-cancelled order asks the payment gateway to refund twice, throws, and
surfaces as **HTTP 500**.

The agent is told only the symptom. It has to find
[OrderService.cs](sample-repo/order-service/src/OrderService/Services/OrderService.cs)
on its own, work out that
[PaymentService.cs](sample-repo/order-service/src/OrderService/Services/PaymentService.cs)
is what actually throws, add the guard clause, write the regression test, and
prove it with a real `dotnet test` run.

The repository ships with 7 passing tests and **no** duplicate-cancellation
test — writing it is part of the task.

---

## How the control plane holds the model

**Three gates before any tool runs** ([agents/base.py](agents/base.py)):

1. **Allowlist** — the planner has *no* tools; the repository agent has no write
   tools; only implementation, testing, debugging and CI can modify files
   ([tools/registry.py](tools/registry.py)).
2. **Policy** — a deterministic rule set evaluated *before* the write
   ([policies/rules.yaml](policies/rules.yaml)). A write to `.env` is refused;
   it does not happen and then get reverted.
3. **Workspace boundary** — every path is resolved back inside the task's Git
   worktree ([tools/workspace.py](tools/workspace.py)). `../../../` fails.

**No shell.** There is no `run_any_shell_command`. Commands are argument
vectors whose executable must be on a fixed allowlist, spawned without a shell,
with every invocation recorded ([tools/runner.py](tools/runner.py)).

**The platform runs the tests, not the agent.** Pass/fail comes from the
process exit code and parsed output, so it cannot be hallucinated.

**The loop is bounded three ways** (§22–23): a hard iteration cap, failure
fingerprinting that detects two identical failures in a row, and a scope guard
that stops a change which keeps growing. Hitting any of them routes to
`HUMAN_REVIEW_REQUIRED` — and a failing change is **never committed**.

**Everything is auditable** (§58). `tasks`, `agent_runs`, `tool_calls`,
`task_events`, `file_changes`, `approvals`, `ci_runs` answer: who started it,
what the agent read, what it changed, which tools it called, how many
iterations it took, which tests failed, and who approved.

---

## Configuration

Every knob is an environment variable ([core/config.py](core/config.py)); see
[.env.example](.env.example). The ones that change behaviour most:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | PostgreSQL | `sqlite+aiosqlite:///./data/agent.db` for laptop use |
| `REDIS_URL` | `redis://…` | `memory://` runs single-process, no scaling |
| `LLM_PROVIDER` | `anthropic` | `scripted` replays fixtures offline |
| `LLM_MODEL` | `claude-opus-5` | adaptive thinking + `effort` |
| `SCM_PROVIDER` | `local` | `github`, `azure_devops` |
| `CI_PROVIDER` | `none` | `github_actions` |
| `MAX_AGENT_ITERATIONS` | `3` | debugging budget |
| `MAX_CI_ITERATIONS` | `2` | separate CI budget |

---

## Tests

```bash
make test        # fast suite
make test-all    # + real dotnet build/test runs
make evaluate    # the benchmark
```

The end-to-end tests in [tests/graph/](tests/graph/) run the **real** workflow
against a **real** Git worktree with a **real** `dotnet test`; only the model is
scripted. They assert the three behaviours that matter:

- a correct fix reaches `READY_FOR_REVIEW` with 9 passing tests and a PR;
- a *wrong* first fix fails the tests, the debugger diagnoses it, and the retest
  passes — in exactly one iteration;
- a debugger that never fixes anything is **stopped** by the bounds, escalated
  to a human, and leaves no commit behind.

---

## Deployment modes (§36)

```bash
make dev-infra && make api && make worker   # A: debug locally
make compose-up                             # B: everything in Docker
make compose-scale                          # B with 3 workers
make k8s-apply                              # C: Kubernetes
```

Scaling out is a replica count, not a code change: workers pull from the queue,
API pods hold no state, and a task's durable state lives in PostgreSQL.

---

## Deliberate departures from the design document

Each of these resolves a conflict *within* the document, or adapts it to the
machine this was built on. They are the decisions worth arguing with.

1. **`security_policy` runs before `git_commit`.** §8's diagram puts CI before
   the commit, but §26 requires a pushed branch for CI to run at all. Order is
   now: policy gate → commit → CI → PR. A blocked change never enters git
   history.
2. **PR creation before approval.** §24 says approval precedes protected
   operations; §44/§45 show a PR at `READY_FOR_REVIEW`. A PR *is* the review
   surface, so it is created first — but **merging is never automated** (§54).
3. **The sample repo targets `net10.0`, not `net8.0`.** Only the .NET 10 SDK is
   installed here, and `dotnet test` needs a matching runtime. The TFM is a
   single property in
   [Directory.Build.props](sample-repo/order-service/Directory.Build.props).
4. **SQLite and in-process adapters exist alongside PostgreSQL and Redis.**
   Docker is not installed on this machine. Both sit behind the same interfaces,
   so this is adapter selection, not a second architecture — but `memory://`
   gives up multi-process scaling and is dev-only.
5. **Embeddings are stored as JSON, not `vector`.** §12 says not to start with
   vector search. Levels 1–3 work with no index; level 4 turns on by applying
   [0002_pgvector.sql](persistence/migrations/0002_pgvector.sql) and configuring
   an embedder, with no change above `retrieval/search/`.
6. **`core/` and `llm/` exist**, which §5's tree does not list — configuration,
   logging, domain vocabulary, and the provider adapter needed a home that was
   not an agent.
7. **No `tools/ci/`.** §5 lists it, but CI already has a provider abstraction
   (§28) that the `ci_validation` node calls directly. A tool wrapper over it
   would be indirection with no caller, so it was left out rather than shipped
   empty.

## Not built (deliberately out of POC scope, §54)

Authentication/SSO on the API, object storage for large artifacts,
OpenTelemetry/Prometheus (§59 says not to add it until the core works), a real
embedder implementation, and anything that touches production.
