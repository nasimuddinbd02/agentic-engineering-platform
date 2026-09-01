# Process 1 — Task Lifecycle

**What happens between `POST /api/v1/tasks` and a reviewer seeing a diff.**

This is the outer loop. The [agent workflow](02-agent-workflow.md) is the inner
loop that runs inside step 4.

---

## The one rule that shapes everything

> The API never executes an agent.

A request handler that ran a workflow would hold an HTTP connection open for
minutes, die with the process, and make the API impossible to scale separately
from the work. So the API does three cheap things — persist, enqueue, respond —
and a worker does the slow part.

```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI
    participant P as PostgreSQL
    participant Q as Redis queue
    participant W as Worker

    C->>A: POST /api/v1/tasks
    A->>P: INSERT task (QUEUED)
    P-->>A: task_id
    A-->>C: 202 {task_id, QUEUED}
    Note over A,Q: enqueued only after the transaction commits
    A->>Q: publish(task_id)

    Q->>W: claim
    W->>P: load task + checkpoint
    W->>W: run the agent workflow
    W->>P: checkpoint after every node
    W-->>C: events (via Redis -> SSE)
    W->>P: final status
```

---

## Step by step

### 1. Persist, then enqueue

The queue carries **task ids only**, never payloads. A worker always reloads
the task from PostgreSQL, so the database is the single source of truth and the
queue is just a doorbell.

Order matters. The id is published *after* the request transaction commits
(via a FastAPI background task), otherwise a fast worker could claim a task
that is not yet visible to it.

`apps/api/routes/tasks.py` → `apps/api/services.py`

### 2. Idempotency

Sending `Idempotency-Key: abc` twice returns the **same** task, not two.

```mermaid
flowchart TD
    R["POST + Idempotency-Key"] --> K{"key seen<br/>before?"}
    K -->|no| N["create task<br/>202"]
    K -->|yes| F{"same request<br/>fingerprint?"}
    F -->|yes| S["return original task<br/>200"]
    F -->|no| C["409 Conflict"]

    style N fill:#16a34a,color:#fff
    style S fill:#2563eb,color:#fff
    style C fill:#dc2626,color:#fff
```

The fingerprint is a hash of repository + issue. Reusing a key for a *different*
request is a client bug, so it is rejected rather than silently ignored.

### 3. Claiming — two locks, not one

A task must never run twice at once. Two independent guards:

```mermaid
flowchart LR
    W["Worker"] --> L{"Redis lock<br/>SET NX PX"}
    L -->|"lost"| Skip["skip"]
    L -->|"won"| D{"conditional UPDATE<br/>lease free or expired?"}
    D -->|"0 rows"| Skip
    D -->|"1 row"| Run["execute"]

    style Run fill:#16a34a,color:#fff
    style Skip fill:#6b7280,color:#fff
```

The Redis lock is fast; the database lease is durable. If Redis loses its state,
the `UPDATE ... WHERE locked_by IS NULL OR lease_expires_at < now` still refuses
the second worker. Detail in
[08-coordination-and-scaling.md](08-coordination-and-scaling.md).

### 4. Execution

The worker builds a `WorkflowContext` (model, tools, workspaces, policy, SCM,
CI, event bus) and runs the LangGraph workflow. After **every node** it writes
the full state back to `tasks.state`, so another worker can resume.

`apps/worker/execution.py`

### 5. Settling

```mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> PLANNING
    PLANNING --> REPOSITORY_ANALYSIS
    REPOSITORY_ANALYSIS --> RISK_ASSESSMENT
    RISK_ASSESSMENT --> IMPLEMENTING
    IMPLEMENTING --> TESTING
    TESTING --> DEBUGGING: tests failed
    DEBUGGING --> TESTING: retry
    TESTING --> POLICY_CHECK: tests passed
    POLICY_CHECK --> TEST_PASSED: allowed
    TEST_PASSED --> CI_RUNNING
    CI_RUNNING --> CI_DEBUGGING: failed
    CI_DEBUGGING --> TESTING
    CI_RUNNING --> PR_CREATED: passed
    PR_CREATED --> READY_FOR_REVIEW

    READY_FOR_REVIEW --> COMPLETED: approved
    READY_FOR_REVIEW --> REJECTED: rejected

    DEBUGGING --> HUMAN_REVIEW_REQUIRED: budget spent
    POLICY_CHECK --> HUMAN_REVIEW_REQUIRED: blocked
    CI_DEBUGGING --> HUMAN_REVIEW_REQUIRED: budget spent

    COMPLETED --> [*]
    REJECTED --> [*]
    HUMAN_REVIEW_REQUIRED --> [*]
```

Two ways to finish:

- **`READY_FOR_REVIEW`** — it worked. A person decides.
- **`HUMAN_REVIEW_REQUIRED`** — it stopped itself. Also a person decides, but
  nothing was committed.

Both are *settled*: no worker will touch them again. That distinction matters
for the event stream, which closes on settled, not just on terminal.

---

## Live progress

Workers publish events to Redis; every API instance subscribes. A browser can
reconnect through a load balancer to a **different** API pod and lose nothing,
because the stream replays from PostgreSQL first and only then follows the live
channel.

```mermaid
flowchart LR
    W["Worker"] -->|"publish"| R[("Redis pub/sub")]
    W -->|"append"| P[("task_events")]
    R --> A1["API-1"]
    R --> A2["API-2"]
    P -.->|"replay on connect"| A1
    A1 -->|"SSE"| B["Browser"]
```

Reconnect with `?after=<sequence>` to resume exactly where you left off.

---

## Where the code lives

| Step | File |
|---|---|
| endpoints | `apps/api/routes/tasks.py` |
| service layer | `apps/api/services.py` |
| task storage, leases | `persistence/repositories/tasks.py` |
| queue adapters | `infrastructure/queue/` |
| worker loop | `apps/worker/consumer.py` |
| one task's execution | `apps/worker/execution.py` |
| SSE | `apps/api/routes/events.py` |

**Tests:** `tests/integration/test_api.py`,
`tests/integration/test_worker_coordination.py`
