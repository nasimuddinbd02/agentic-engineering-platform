# Running the Application

Everything you need to get the platform running, from a clean checkout to
watching an agent fix a bug.

> **New here?** Read this page top to bottom once. Then
> [processes/01-task-lifecycle.md](processes/01-task-lifecycle.md) explains what
> you just watched happen.

---

## 1. What you are about to run

Five moving parts. Only the first two are code we wrote:

```mermaid
flowchart LR
    Browser["Browser<br/>:3000"] --> API["FastAPI<br/>:8000"]
    CLI["submit_task.py"] --> API
    API -->|"1 . persist"| DB[("PostgreSQL<br/>:5432")]
    API -->|"2 . enqueue id"| Q[("Redis<br/>:6379")]
    Q -->|"3 . claim"| W["Agent Worker"]
    W --> DB
    W --> Git["Git worktree<br/>+ dotnet test"]
    W --> LLM["LLM provider"]
    API -.->|"live events"| Browser

    style API fill:#2563eb,color:#fff
    style W fill:#7c3aed,color:#fff
```

The API never runs an agent. It writes the task to the database, puts the id on
a queue, and returns `202`. A worker picks it up. That separation is the whole
reason the system scales — see
[processes/08-coordination-and-scaling.md](processes/08-coordination-and-scaling.md).

---

## 2. Prerequisites

| Tool | Needed for | Check |
|---|---|---|
| **Python 3.11+** | the platform | `python --version` |
| **Git** | worktrees — not optional | `git --version` |
| **.NET SDK 10** | building/testing the sample repo | `dotnet --version` |
| Node.js 20+ | the web UI only | `node --version` |
| Docker | PostgreSQL + Redis only | `docker --version` |
| ripgrep | faster search (falls back to Python) | `rg --version` |

**Docker and Node are optional.** The platform runs on SQLite and an in-process
queue without them. Git and the .NET SDK are not optional: the agent creates
real worktrees and runs real tests.

---

## 3. First run (five minutes, no Docker, no API key)

```bash
make install                    # venv + dependencies
cp .env.example .env
make bootstrap                  # database schema + sandbox copy of the sample repo
```

Now edit `.env` for the zero-dependency path:

```ini
DATABASE_URL=sqlite+aiosqlite:///./data/agent.db
REDIS_URL=memory://
LLM_PROVIDER=scripted
LLM_SCRIPT_PATH=./scripts/demo_script.yaml
```

Start it and submit the sample issue:

```bash
make run-local                  # terminal 1: API + worker in one process
make demo                       # terminal 2: submit and follow the live stream
```

You should see the timeline stream past, ending in something like:

```
            status: READY_FOR_REVIEW
         iteration: 1
      tests_passed: 9
     files_changed: src/OrderService/Services/OrderService.cs,
                    tests/OrderService.Tests/OrderCancellationIdempotencyTests.cs
```

Then approve it:

```bash
curl -X POST http://localhost:8000/api/v1/tasks/<TASK-ID>/approve \
  -H "Content-Type: application/json" -d '{"decided_by":"you"}'
```

### What just happened

`iteration: 1` is the interesting part. The scripted run applies a
**deliberately wrong** first fix, the real `dotnet test` run fails, and the
debugging agent diagnoses and corrects it. You watched the bounded recovery loop
work — see [processes/05-debugging-loop.md](processes/05-debugging-loop.md).

> **`LLM_PROVIDER=scripted` is a stand-in for the model, not a simulation of the
> platform.** The worktree, the tools, the policy engine, `dotnet test`, git and
> the approval flow are all real. Only the reasoning is canned.

---

## 4. Running with a real model

```ini
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-opus-5
```

Leave `LLM_SCRIPT_PATH` empty or remove it. Now the agent genuinely has to find
the defect from the issue text alone. Everything else is unchanged.

---

## 5. The three deployment modes

```mermaid
flowchart TD
    A["Mode A - Developer<br/>API + worker on the host<br/>Postgres + Redis in Docker"]
    B["Mode B - Docker Compose<br/>everything containerised"]
    C["Mode C - Kubernetes<br/>independent deployments + autoscaling"]
    A -->|"same code"| B -->|"same code"| C

    style A fill:#16a34a,color:#fff
    style B fill:#2563eb,color:#fff
    style C fill:#7c3aed,color:#fff
```

### Mode A — developer (best for debugging)

```bash
make dev-infra                  # Postgres + Redis in Docker
```

```ini
DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5432/agent
REDIS_URL=redis://localhost:6379/0
```

```bash
make api            # terminal 1
make worker         # terminal 2  (repeat in more terminals to scale out)
make web            # terminal 3  -> http://localhost:3000
```

With real Redis the API and worker are genuinely independent — run three
workers and watch them share the queue.

### Mode B — Docker Compose (best for integration)

```bash
make compose-up                 # everything in containers
make compose-scale              # same, with 3 workers
make compose-logs
```

Mount the repository you want the agent to work on into the worker. The compose
file maps `./.sandbox` to `/repositories`, so submit tasks with
`repository_path=/repositories/order-service`.

### Mode C — Kubernetes (best for scalability)

```bash
make k8s-apply
```

Create the secret properly first — never from the checked-in template:

```bash
kubectl create secret generic agent-secrets \
  --from-literal=LLM_API_KEY=... \
  --from-literal=GITHUB_TOKEN=...
```

---

## 6. Configuration reference

Everything is an environment variable, read in exactly one place
([core/config.py](../core/config.py)).

### Infrastructure

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/agent.db` | Postgres for anything real |
| `REDIS_URL` | `memory://` | `memory://` is single-process, dev only |
| `API_PORT` | `8000` | |
| `LOG_LEVEL` | `INFO` | structured logs, bound to `task_id` |

### Model

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `scripted` | `anthropic` for a real model |
| `LLM_API_KEY` | — | also read from `ANTHROPIC_API_KEY` |
| `LLM_MODEL` | `claude-opus-5` | |
| `LLM_EFFORT` | `high` | `low`…`max` |
| `LLM_MAX_TOKENS` | `16000` | |
| `LLM_SCRIPT_PATH` | — | offline script, `scripted` only |

### Source control and CI

| Variable | Default | Notes |
|---|---|---|
| `SCM_PROVIDER` | `local` | `github`, `azure_devops` |
| `CI_PROVIDER` | `none` | `github_actions` |
| `GITHUB_TOKEN` | — | needs `repo` scope |
| `GITHUB_REPOSITORY` | — | `owner/name` |

### Limits — the autonomy budget

| Variable | Default | What it bounds |
|---|---|---|
| `MAX_AGENT_ITERATIONS` | `3` | debugging attempts before escalating |
| `MAX_CI_ITERATIONS` | `2` | CI fix attempts (separate budget) |
| `MAX_FILES_PER_TASK` | `25` | scope guard |
| `COMMAND_TIMEOUT_SECONDS` | `600` | any one build or test run |
| `TASK_LEASE_SECONDS` | `900` | how long before a dead worker's task is reclaimed |
| `QUEUE_SWEEP_SECONDS` | `15` | how often a worker reconciles against the database |
| `WORKER_CONCURRENCY` | `2` | tasks in flight per worker |

---

## 7. Submitting work

### From the CLI

```bash
python -m scripts.submit_task --watch \
  --repository-path ./.sandbox/order-service \
  --issue "Cancelling an already cancelled order returns HTTP 500."
```

### From the API

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-key-1" \
  -d '{
        "repository": "file:///order-service",
        "repository_path": "/absolute/path/to/order-service",
        "issue": "Cancelling an already cancelled order returns HTTP 500."
      }'
```

`repository_path` must be a path **on the worker**, and an actual git
repository. Re-sending the same `Idempotency-Key` returns the original task
instead of starting a second one.

### From the browser

`http://localhost:3000` — submit, watch the live timeline, read the diff,
approve or reject.

### Key endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/tasks` | submit (returns `202`) |
| `GET` | `/api/v1/tasks/{id}` | full detail + audit trail |
| `GET` | `/api/v1/tasks/{id}/events` | live SSE stream |
| `GET` | `/api/v1/tasks/{id}/diff` | unified diff |
| `POST` | `/api/v1/tasks/{id}/approve` | approve |
| `POST` | `/api/v1/tasks/{id}/reject` | reject |
| `GET` | `/api/v1/approvals` | review queue |
| `GET` | `/api/v1/policies` | the active rules |
| `GET` | `/health/ready` | dependency check |

Interactive docs: `http://localhost:8000/docs`.

---

## 8. Tests

```bash
make test          # fast suite (~8s)
make test-all      # + real dotnet build/test runs (~50s)
make evaluate      # the benchmark
make lint
```

`tests/graph/` runs the real workflow against a real worktree with a real
`dotnet test`. Those are the ones that prove the system works.

---

## 9. Troubleshooting

**Worker never picks up the task.**
With `REDIS_URL=memory://` the queue lives inside one process — use
`make run-local`, not separate `make api` + `make worker`. A worker also sweeps
the database every `QUEUE_SWEEP_SECONDS`, so it recovers within ~15s either way.

**`repository_path does not exist on this worker`.**
The path must be absolute, exist on the worker, and be a git repository. In
Docker it must be a path *inside* the container.

**`git worktree add` fails.**
Stale worktrees from a killed run. `make reset` prunes them.

**`dotnet test` fails to restore.**
A private NuGet feed on your machine returning 401. The sample repo ships a
`NuGet.config` pinning it to nuget.org.

**`Access is denied` when resetting on Windows.**
A worker still holds a file handle. Stop the processes, then `make reset`.

**Nothing changed and the task stopped.**
Correct behaviour: an empty change halts before CI and never reaches a
reviewer. Check `error` on the task.

**Live timeline stops updating.**
The stream ends deliberately once the task settles (`READY_FOR_REVIEW` or
terminal). Reconnect with `?after=<sequence>` to resume without gaps.

---

## 10. Where to go next

| To understand… | Read |
|---|---|
| what happens after `POST /tasks` | [01-task-lifecycle.md](processes/01-task-lifecycle.md) |
| the agent graph itself | [02-agent-workflow.md](processes/02-agent-workflow.md) |
| why the agent cannot escape | [03-tool-execution-and-safety.md](processes/03-tool-execution-and-safety.md) |
| how it finds the right code | [04-repository-intelligence.md](processes/04-repository-intelligence.md) |
| how it recovers from failure | [05-debugging-loop.md](processes/05-debugging-loop.md) |
| what it is not allowed to do | [06-policy-and-risk.md](processes/06-policy-and-risk.md) |
| the human gate | [07-human-approval.md](processes/07-human-approval.md) |
| scaling and crash recovery | [08-coordination-and-scaling.md](processes/08-coordination-and-scaling.md) |
| CI integration | [09-cicd-integration.md](processes/09-cicd-integration.md) |
| the audit tables | [10-persistence-and-audit.md](processes/10-persistence-and-audit.md) |
