# AI Software Engineering Agent

## Local-First POC, Scalable Architecture, and Multi-Server Deployment Design

**Version:** 1.0\
**Purpose:** Hands-on learning, POC implementation, and a clean path to
production-style deployment\
**Primary implementation language:** Python\
**Sample target application:** .NET 8 Order Service\
**Frontend:** Next.js\
**API:** FastAPI\
**Agent orchestration:** LangGraph\
**State/cache:** Redis\
**Persistent data:** PostgreSQL\
**Code intelligence:** lexical search → symbol/dependency analysis →
pgvector RAG\
**Source control:** Git + GitHub/Azure DevOps\
**CI/CD:** GitHub Actions or Azure DevOps\
**Containerization:** Docker\
**Production orchestration:** Kubernetes

------------------------------------------------------------------------

# 1. Purpose

This document is the implementation blueprint for building an **AI
Software Engineering Agent** locally first, while keeping the
architecture ready for deployment across multiple application servers
and agent workers.

The system is intentionally designed **not** to compete directly with
general-purpose coding assistants such as Claude Code, GitHub Copilot,
or Gemini.

Instead, the system demonstrates an **engineering control plane around a
coding-capable LLM**:

``` text
Engineering Issue
       |
       v
Planning
       |
       v
Repository Intelligence
       |
       v
Risk / Policy
       |
       v
Implementation
       |
       v
Testing
       |
   +---+---+
   |       |
 PASS     FAIL
   |       |
   |       v
   |   Debugging
   |       |
   +--- Retest
       |
       v
CI/CD Validation
       |
       v
Git Branch / Commit / PR
       |
       v
Human Approval
```

The POC must demonstrate:

-   Agent orchestration
-   Stateful execution
-   Tool calling
-   Repository search
-   Codebase RAG
-   Controlled code modification
-   Git worktrees
-   Automated testing
-   Bounded debugging loops
-   CI/CD integration
-   Human-in-the-loop approval
-   Redis-backed coordination
-   PostgreSQL persistence
-   Horizontal worker scaling
-   Docker deployment
-   Kubernetes-ready architecture

------------------------------------------------------------------------

# 2. Architectural Principles

## 2.1 Local-first

The first implementation must run on a developer laptop:

``` text
Windows / Linux / macOS
        |
        +-- FastAPI
        +-- Agent Worker
        +-- PostgreSQL
        +-- Redis
        +-- Git
        +-- Docker
        +-- Sample .NET Repository
```

Do not require Kubernetes to understand the first version.

------------------------------------------------------------------------

## 2.2 API and Agent Worker Must Be Separate

Do not execute long-running agent workflows directly inside FastAPI
request handlers.

Use:

``` text
Browser / CLI
     |
     v
FastAPI
     |
     v
Task Queue
     |
     v
Agent Worker
```

This makes horizontal scaling possible.

For example:

``` text
             Load Balancer
                   |
          +--------+--------+
          |        |        |
          v        v        v
      API-1     API-2     API-3
          \        |        /
           +-------+-------+
                   |
                Redis
                   |
             Task Queue
                   |
        +----------+----------+
        |          |          |
        v          v          v
    Worker-1   Worker-2   Worker-3
```

------------------------------------------------------------------------

## 2.3 Stateless API Servers

FastAPI instances must not depend on local in-memory state.

Do not do:

``` python
active_tasks = {}
connections = {}
```

for durable application state.

Instead:

``` text
PostgreSQL -> durable task state
Redis      -> queue/cache/events/locks
Object storage or shared storage -> large artifacts if needed
```

This allows:

``` text
API-1
API-2
API-3
```

to handle the same user's task without knowing which server handled the
previous request.

------------------------------------------------------------------------

## 2.4 Agent Workers Can Be Stateful During One Execution

An individual agent worker can maintain in-memory execution state during
a single workflow, but the canonical task state must be persisted.

Use:

``` text
LangGraph execution
       |
       +-- current state
       |
       +-- checkpoint/state persistence
       |
       +-- PostgreSQL
```

If Worker-1 crashes, another worker should be able to resume or safely
restart the task.

------------------------------------------------------------------------

## 2.5 Never Modify the Developer's Main Working Directory

Every task should use an isolated Git worktree or cloned workspace:

``` text
Target Repository
       |
       +-- main
       |
       +-- agent workspace
              |
              +-- implementation
              +-- tests
              +-- build
              +-- diff
```

The agent must never casually modify the developer's active working
directory.

------------------------------------------------------------------------

# 3. Target Local Architecture

The local environment should look like:

``` text
                         Browser
                            |
                            v
                     Next.js :3000
                            |
                            v
                     FastAPI :8000
                            |
                            v
                    Redis :6379
                     /           \
                    /             \
             task queue          events
                  |
                  v
             Agent Worker
                  |
       +----------+-----------+
       |          |           |
       v          v           v
 PostgreSQL    Git Repo    LLM Provider
    :5432          |
       |           v
       |      Git Worktree
       |
       +---- pgvector
```

The sample target repository is separate:

``` text
C:\Projects\order-service
```

or:

``` text
D:\Projects\order-service
```

The agent itself lives in a different repository:

``` text
D:\Projects\ai-engineering-agent
```

------------------------------------------------------------------------

# 4. Production / Multi-Server Architecture

The same logical architecture should later become:

``` text
                         Internet / Corporate Network
                                   |
                                   v
                             Load Balancer
                                   |
                 +-----------------+-----------------+
                 |                 |                 |
                 v                 v                 v
              API Pod           API Pod           API Pod
                 |                 |                 |
                 +-----------------+-----------------+
                                   |
                              Redis / Queue
                                   |
                 +-----------------+-----------------+
                 |                 |                 |
                 v                 v                 v
             Worker Pod        Worker Pod        Worker Pod
                 |                 |                 |
                 +-----------------+-----------------+
                                   |
                     +-------------+-------------+
                     |             |             |
                     v             v             v
                 PostgreSQL      Git         Artifact Store
                     |
                     v
                  pgvector
```

Important rule:

**Workers must not depend on local filesystem state for durable
application state.**

The agent workspace itself can be local to a worker because it is
temporary.

------------------------------------------------------------------------

# 5. Repository Layout

Use a monorepo for the POC:

``` text
ai-engineering-agent/
│
├── apps/
│   │
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   │       ├── tasks.py
│   │       ├── approvals.py
│   │       ├── events.py
│   │       └── health.py
│   │
│   ├── worker/
│   │   ├── main.py
│   │   ├── consumer.py
│   │   └── execution.py
│   │
│   └── web/
│       └── Next.js application
│
├── agents/
│   ├── supervisor.py
│   ├── planner.py
│   ├── repository_agent.py
│   ├── implementation_agent.py
│   ├── testing_agent.py
│   ├── debugging_agent.py
│   ├── ci_agent.py
│   └── git_agent.py
│
├── graph/
│   ├── workflow.py
│   ├── routing.py
│   └── state.py
│
├── tools/
│   ├── filesystem/
│   │   ├── read_file.py
│   │   ├── list_directory.py
│   │   └── apply_patch.py
│   │
│   ├── repository/
│   │   ├── search_code.py
│   │   ├── symbol_search.py
│   │   └── dependency_search.py
│   │
│   ├── git/
│   │   ├── branch.py
│   │   ├── worktree.py
│   │   ├── diff.py
│   │   └── commit.py
│   │
│   ├── testing/
│   │   ├── build.py
│   │   ├── test.py
│   │   └── lint.py
│   │
│   └── ci/
│       ├── trigger.py
│       └── status.py
│
├── retrieval/
│   ├── ingestion/
│   │   ├── scanner.py
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   └── indexer.py
│   │
│   ├── search/
│   │   ├── lexical.py
│   │   ├── vector.py
│   │   ├── hybrid.py
│   │   └── reranker.py
│   │
│   └── models/
│
├── policies/
│   ├── rules.yaml
│   └── evaluator.py
│
├── persistence/
│   ├── models/
│   ├── repositories/
│   └── migrations/
│
├── infrastructure/
│   ├── docker/
│   │   ├── api.Dockerfile
│   │   ├── worker.Dockerfile
│   │   └── web.Dockerfile
│   │
│   ├── docker-compose.yml
│   │
│   └── kubernetes/
│       ├── api-deployment.yaml
│       ├── worker-deployment.yaml
│       ├── services.yaml
│       ├── configmap.yaml
│       └── secrets.yaml
│
├── prompts/
│   ├── planner.md
│   ├── repository.md
│   ├── implementation.md
│   ├── testing.md
│   ├── debugging.md
│   └── ci.md
│
├── sample-repo/
│   └── order-service/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── graph/
│   └── evaluation/
│
├── scripts/
│   ├── bootstrap.py
│   ├── index_repository.py
│   └── reset_poc.py
│
├── .env.example
├── pyproject.toml
├── docker-compose.yml
├── README.md
└── Makefile
```

------------------------------------------------------------------------

# 6. Domain Boundaries

Keep responsibilities separated.

``` text
API Layer
    |
Application Layer
    |
Agent / Workflow Layer
    |
Tool Layer
    |
Infrastructure Layer
    |
External Systems
```

Example:

``` text
FastAPI
  |
TaskService
  |
AgentWorkflow
  |
RepositoryTool
  |
Git / Filesystem
```

Agents should not directly contain database implementation details.

Bad:

``` python
class PlannerAgent:
    def __init__(self):
        self.db = PostgresConnection(...)
```

Better:

``` text
Planner
  |
Task Repository / State Service
```

This keeps agents testable.

------------------------------------------------------------------------

# 7. Core Agent State

Create one explicit state contract.

``` python
from typing import TypedDict

class AgentState(TypedDict, total=False):
    task_id: str

    repository_url: str
    repository_path: str
    workspace_path: str

    issue: str

    plan: list[str]
    acceptance_criteria: list[str]

    relevant_files: list[str]
    repository_context: list[str]

    risk_level: str
    approval_required: bool

    modified_files: list[str]
    git_diff: str

    test_commands: list[str]
    test_results: str
    test_failures: list[str]

    debugging_analysis: str
    previous_failures: list[str]

    iteration: int
    max_iterations: int

    ci_status: str
    ci_logs: str

    git_branch: str
    commit_sha: str
    pull_request_url: str

    final_summary: str
```

The state is the contract between workflow nodes.

------------------------------------------------------------------------

# 8. Agent Workflow

The first implementation should use this graph:

``` text
START
  |
  v
plan
  |
  v
repository_analysis
  |
  v
risk_assessment
  |
  v
implementation
  |
  v
test_generation
  |
  v
run_tests
  |
  +--------------------+
  |                    |
 PASS                 FAIL
  |                    |
  v                    v
ci_validation       debugging
  |                    |
  |                    v
  |                 run_tests
  |
  v
security_policy
  |
  v
git_commit
  |
  v
create_pr
  |
  v
human_review
  |
  v
END
```

------------------------------------------------------------------------

# 9. Supervisor Responsibility

The supervisor is not the "smartest agent."

It is the **workflow controller**.

Responsibilities:

-   Route execution
-   Maintain state
-   Enforce iteration limits
-   Enforce tool permissions
-   Stop unsafe workflows
-   Trigger human approval
-   Handle errors
-   Publish task events

The supervisor should make deterministic decisions whenever possible.

------------------------------------------------------------------------

# 10. Planner Agent

Input:

``` text
Issue:
Fix order cancellation returning HTTP 500
for already cancelled orders.
```

Output:

``` json
{
  "summary": "Make order cancellation idempotent",
  "steps": [
    "Find cancellation API",
    "Inspect order service",
    "Inspect repository",
    "Inspect existing tests",
    "Implement idempotency",
    "Add regression test",
    "Run tests"
  ],
  "acceptance_criteria": [
    "Already cancelled order does not return 500",
    "Cancellation remains idempotent",
    "Existing tests continue to pass"
  ]
}
```

Planner should not modify source code.

------------------------------------------------------------------------

# 11. Repository Agent

The Repository Agent answers:

> Where is the code relevant to this issue?

It uses tools:

``` text
search_code()
read_file()
find_symbol()
find_references()
get_dependencies()
```

Example:

``` text
Issue
 |
 v
"cancel order"
 |
 +--> OrdersController.cs
 +--> OrderService.cs
 +--> OrderRepository.cs
 +--> OrderServiceTests.cs
```

The agent then builds a compact context package for the implementation
agent.

------------------------------------------------------------------------

# 12. Codebase RAG

Do not begin with vector search.

Implement retrieval progressively.

## Level 1

``` text
ripgrep
```

## Level 2

``` text
symbol search
```

## Level 3

``` text
dependency graph
```

## Level 4

``` text
embeddings + pgvector
```

## Level 5

``` text
keyword + symbol + vector
       |
       v
    reranker
```

Recommended production-style retrieval:

``` text
User Issue
    |
    +--> Keyword Search
    |
    +--> Symbol Search
    |
    +--> Dependency Search
    |
    +--> Vector Search
              |
              v
          Candidate Set
              |
              v
           Reranker
              |
              v
        Final Context
```

------------------------------------------------------------------------

# 13. PostgreSQL Schema

Start with these tables:

``` text
tasks
agent_runs
tool_calls
task_events
file_changes
approvals
ci_runs
evaluation_results
```

Example:

``` sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    repository_url TEXT NOT NULL,
    issue TEXT NOT NULL,
    status TEXT NOT NULL,
    risk_level TEXT,
    current_node TEXT,
    iteration INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

For RAG:

``` text
code_chunks
```

with:

``` text
id
repository_id
file_path
symbol_name
language
content
embedding
metadata
```

Use pgvector for the `embedding` column.

------------------------------------------------------------------------

# 14. Redis Responsibilities

Redis should be used for fast, ephemeral coordination.

Recommended uses:

``` text
1. Task queue
2. Event streaming/pub-sub
3. Distributed locks
4. Short-lived cache
5. Worker coordination
6. Rate limiting
```

Do not make Redis the only source of truth for task history.

Use:

``` text
PostgreSQL = durable state
Redis      = fast coordination
```

------------------------------------------------------------------------

# 15. Task Execution Model

When the API receives:

``` http
POST /api/tasks
```

do not execute the agent synchronously.

Instead:

``` text
POST /api/tasks
       |
       v
Create task in PostgreSQL
       |
       v
Publish task ID to Redis
       |
       v
Return HTTP 202
```

Example response:

``` json
{
  "task_id": "TASK-1001",
  "status": "QUEUED"
}
```

Worker:

``` text
Redis queue
    |
    v
Worker claims TASK-1001
    |
    v
Load task from PostgreSQL
    |
    v
Execute LangGraph
    |
    v
Persist state/events
```

------------------------------------------------------------------------

# 16. Why This Scales

Suppose one worker can process 5 concurrent tasks.

With:

``` text
1 worker = 5 tasks
```

You can scale to:

``` text
Worker 1 -> 5
Worker 2 -> 5
Worker 3 -> 5
Worker 4 -> 5
```

Total theoretical concurrency:

``` text
20 tasks
```

The API layer can independently scale.

``` text
API servers scale based on HTTP traffic.

Workers scale based on agent workload.
```

This separation is critical.

------------------------------------------------------------------------

# 17. Task Locking

Two workers must never process the same task simultaneously.

Use a distributed lock.

Conceptually:

``` text
Worker-1
   |
   +-- acquire lock TASK-1001
   |
   +-- SUCCESS
   |
   +-- execute
```

Worker-2:

``` text
TASK-1001
    |
    +-- lock exists
    |
    +-- do not execute
```

Use Redis for the short-lived lock and PostgreSQL status transitions as
a second safety mechanism.

------------------------------------------------------------------------

# 18. Git Worktree Strategy

For each task:

``` text
repository/
    |
    +-- main
    |
    +-- agent workspace
```

Create:

``` bash
git worktree add ../workspaces/TASK-1001 -b agent/TASK-1001
```

Then:

``` text
TASK-1001
   |
   v
/workspaces/TASK-1001
```

The agent works only there.

At completion:

``` text
git diff
git status
git commit
git push
```

Then optionally delete the worktree after the task is finalized.

------------------------------------------------------------------------

# 19. Tool Security Boundary

Every tool must validate:

``` text
Who?
Which task?
Which repository?
Which workspace?
Which file?
Which command?
```

For example:

``` python
def read_file(task_id: str, path: str):
    workspace = workspace_manager.get(task_id)

    safe_path = resolve_inside_workspace(workspace, path)

    return safe_path.read_text()
```

Never allow:

``` text
../../../../Windows/System32
```

or equivalent path traversal.

------------------------------------------------------------------------

# 20. Shell Execution

Do not initially create:

``` python
run_any_shell_command(command)
```

Instead expose:

``` text
run_dotnet_build()
run_dotnet_test()
run_npm_test()
run_linter()
```

Later you can implement a controlled command executor.

Every execution should record:

``` text
task_id
command
start_time
end_time
exit_code
stdout
stderr
duration
```

------------------------------------------------------------------------

# 21. Testing Agent

The Testing Agent should understand:

``` text
Acceptance Criteria
        +
Existing Tests
        +
Changed Files
        |
        v
Targeted Test Plan
```

Example:

``` text
Test cases:

1. Cancel pending order -> success
2. Cancel already cancelled order -> success/idempotent
3. Cancel missing order -> expected error
4. Cancel completed order -> expected business rule
```

Then execute:

``` bash
dotnet test
```

------------------------------------------------------------------------

# 22. Debugging Loop

This is the most important agentic behavior in the POC.

``` text
run_tests
    |
    +-- PASS --> continue
    |
    +-- FAIL
          |
          v
      debugging_agent
          |
          v
       analyze
          |
          v
      apply_patch
          |
          v
       run_tests
```

Set:

``` text
max_iterations = 3
```

The agent must stop when:

``` text
iteration >= max_iterations
```

Also stop if:

``` text
same failure repeats
```

or:

``` text
changed file scope expands unexpectedly
```

or:

``` text
risk becomes high
```

------------------------------------------------------------------------

# 23. Failure Fingerprinting

To prevent endless loops, create a failure signature:

``` text
failure_signature =
    hash(
        test_name +
        exception_type +
        normalized_error_message
    )
```

If:

``` text
iteration 1 -> signature A
iteration 2 -> signature A
```

the agent should recognize that it is not making progress.

Route to:

``` text
HUMAN_REVIEW
```

instead of continuing.

------------------------------------------------------------------------

# 24. Human Approval

Human approval is a first-class state.

Example:

``` text
READY_FOR_REVIEW
```

The UI displays:

``` text
Files changed: 3

Risk: MEDIUM

Tests: PASS

CI: PASS

Diff:
[View Diff]

[Approve]
[Reject]
[Request Changes]
```

Only after approval can the workflow proceed to a protected operation.

------------------------------------------------------------------------

# 25. Policy Engine

Use deterministic rules.

Example:

``` yaml
rules:
  - name: block-secrets
    patterns:
      - ".env"
      - "*.pem"
      - "*credentials*"
    action: BLOCK

  - name: sensitive-auth
    paths:
      - "Authentication/"
      - "Security/"
    action: HUMAN_APPROVAL

  - name: production-infrastructure
    paths:
      - "infra/prod/"
    action: BLOCK
```

The LLM can classify intent, but policy enforcement should be
deterministic.

------------------------------------------------------------------------

# 26. CI/CD Flow

After local tests pass:

``` text
Agent
  |
  v
Git branch
  |
  v
Push GitHub
  |
  v
GitHub Actions
  |
  +-- Build
  +-- Unit tests
  +-- Integration tests
  +-- Lint
  +-- Security scan
  |
  v
Webhook / polling
  |
  v
Agent state
```

If CI fails:

``` text
CI failed
   |
   v
CI Debugging Agent
   |
   v
Analyze logs
   |
   v
Patch
   |
   v
Push
   |
   v
CI again
```

Use a separate maximum CI retry limit.

------------------------------------------------------------------------

# 27. GitHub / Azure DevOps Abstraction

Do not hard-code GitHub into every agent.

Create an interface:

``` python
class SourceControlProvider:
    def create_branch(self, name): ...
    def push_branch(self, name): ...
    def create_pull_request(self, title, body): ...
    def get_pull_request(self, id): ...
```

Then implement:

``` text
GitHubProvider
AzureDevOpsProvider
```

This keeps the platform portable.

------------------------------------------------------------------------

# 28. CI Provider Abstraction

Likewise:

``` python
class CIPipelineProvider:
    def trigger(self, branch): ...
    def get_status(self, run_id): ...
    def get_logs(self, run_id): ...
```

Implement:

``` text
GitHubActionsProvider
AzureDevOpsPipelineProvider
```

------------------------------------------------------------------------

# 29. API Contract

Recommended endpoints:

``` text
POST   /api/v1/tasks
GET    /api/v1/tasks/{task_id}
GET    /api/v1/tasks/{task_id}/events
GET    /api/v1/tasks/{task_id}/diff
GET    /api/v1/tasks/{task_id}/logs
POST   /api/v1/tasks/{task_id}/approve
POST   /api/v1/tasks/{task_id}/reject
POST   /api/v1/tasks/{task_id}/cancel

POST   /api/v1/repositories/index
GET    /api/v1/repositories/{id}

GET    /health/live
GET    /health/ready
```

Use versioning from the beginning:

``` text
/api/v1/...
```

------------------------------------------------------------------------

# 30. Task State Machine

Use explicit states.

``` text
QUEUED
  |
PLANNING
  |
REPOSITORY_ANALYSIS
  |
RISK_ASSESSMENT
  |
IMPLEMENTING
  |
TESTING
  |
  +---- TEST_FAILED
  |          |
  |      DEBUGGING
  |          |
  |       TESTING
  |
TEST_PASSED
  |
CI_RUNNING
  |
  +---- CI_FAILED
  |          |
  |      CI_DEBUGGING
  |          |
  |       CI_RUNNING
  |
CI_PASSED
  |
POLICY_CHECK
  |
READY_FOR_REVIEW
  |
HUMAN_APPROVED
  |
PR_CREATED
  |
COMPLETED
```

Terminal states:

``` text
COMPLETED
FAILED
CANCELLED
REJECTED
HUMAN_REVIEW_REQUIRED
```

------------------------------------------------------------------------

# 31. Event Model

Every important transition publishes an event.

Example:

``` json
{
  "event_id": "evt-123",
  "task_id": "TASK-1001",
  "type": "TEST_FAILED",
  "timestamp": "2026-08-31T20:00:00Z",
  "payload": {
    "failed_tests": 1,
    "iteration": 1
  }
}
```

Events allow the Next.js UI to show live progress without coupling the
UI to a particular worker.

------------------------------------------------------------------------

# 32. WebSocket / SSE Architecture

For the POC, Server-Sent Events (SSE) is simpler for one-way task
progress.

``` text
Browser
   |
   | GET /tasks/TASK-1001/events
   v
FastAPI
   |
   v
Redis event stream
   |
   v
Agent Worker
```

For bidirectional interactive controls, use WebSocket.

If WebSocket is used in multiple API servers:

``` text
Browser
   |
Load Balancer
   |
   +-- API-1
   +-- API-2
   +-- API-3
         |
         v
       Redis
```

Redis acts as the shared event/coordination layer.

Do not store WebSocket connections only in one server's memory if
clients may reconnect to another server.

------------------------------------------------------------------------

# 33. PostgreSQL vs Redis

Use this rule:

  Data                      PostgreSQL                        Redis
  ------------------- ---------------- ----------------------------
  Task record                      Yes               Cache optional
  Agent state                      Yes   Fast working copy optional
  Audit history                    Yes                           No
  Tool-call history                Yes                           No
  Task queue                        No                          Yes
  Distributed lock                  No                          Yes
  Live events                       No                          Yes
  Cache                             No                          Yes
  RAG metadata                     Yes                     Optional
  Embeddings            Yes + pgvector                           No

------------------------------------------------------------------------

# 34. Docker Local Environment

Use Docker Compose for infrastructure.

Example:

``` yaml
services:

  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  api:
    build:
      context: .
      dockerfile: infrastructure/docker/api.Dockerfile
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis

  worker:
    build:
      context: .
      dockerfile: infrastructure/docker/worker.Dockerfile
    depends_on:
      - postgres
      - redis
```

For the first local version, it is also acceptable to run FastAPI and
the worker directly from Python while PostgreSQL and Redis run through
Docker.

------------------------------------------------------------------------

# 35. Environment Configuration

Use environment variables:

``` text
DATABASE_URL=
REDIS_URL=

LLM_API_KEY=
LLM_MODEL=

GITHUB_TOKEN=
GITHUB_REPOSITORY=

WORKSPACE_ROOT=

MAX_AGENT_ITERATIONS=3
MAX_CI_ITERATIONS=2

LOG_LEVEL=INFO
```

Never commit secrets.

Provide:

``` text
.env.example
```

but not:

``` text
.env
```

------------------------------------------------------------------------

# 36. Local Development Modes

Support three modes.

## Mode A --- Developer mode

``` text
FastAPI local
Worker local
Postgres Docker
Redis Docker
```

Best for debugging.

## Mode B --- Docker Compose

``` text
API container
Worker container
Postgres container
Redis container
Next.js container
```

Best for integration testing.

## Mode C --- Kubernetes

``` text
API Deployment
Worker Deployment
Redis
PostgreSQL
Ingress
```

Best for scalability learning.

------------------------------------------------------------------------

# 37. Kubernetes Architecture

Production-style deployment:

``` text
                 Ingress / Load Balancer
                          |
                  +-------+-------+
                  |               |
               API Pods        API Pods
                  |
                  v
              Redis Queue
                  |
       +----------+----------+
       |          |          |
    Worker     Worker     Worker
       |          |          |
       +----------+----------+
                  |
             PostgreSQL
                  |
               pgvector
```

Agent workers should be horizontally scalable.

------------------------------------------------------------------------

# 38. Worker Scaling

Workers should consume tasks from Redis.

Conceptually:

``` python
while True:
    task = queue.receive()

    if task:
        execute_task(task)
```

With Kubernetes:

``` text
worker replicas = 3
```

Later:

``` text
worker replicas = 10
```

The application code should not change.

For production, consider queue depth and task duration for autoscaling.

------------------------------------------------------------------------

# 39. Workspace Scaling Problem

Agent tasks require local source code.

Therefore:

``` text
Worker-1
   |
   +-- /workspace/TASK-1001

Worker-2
   |
   +-- /workspace/TASK-1002
```

A task should remain associated with one worker during active execution.

If a worker dies:

``` text
TASK-1001
   |
   v
marked recoverable
   |
   v
Worker-3 claims task
   |
   v
recreates workspace
   |
   v
resumes/restarts workflow
```

For the POC, restarting from the last durable workflow checkpoint is
acceptable.

------------------------------------------------------------------------

# 40. Large Artifacts

Do not store large build logs, repository archives, or generated
artifacts directly in PostgreSQL.

Use object storage later:

``` text
S3 / Azure Blob / MinIO
```

Store only:

``` text
artifact_id
task_id
object_key
metadata
```

in PostgreSQL.

For local POC, a local artifact directory is acceptable.

------------------------------------------------------------------------

# 41. Observability

Every task should have:

``` text
task_id
workflow_run_id
agent_run_id
tool_call_id
```

Log:

``` text
task started
node started
node completed
tool called
tool completed
file changed
test started
test completed
debugging iteration
CI started
CI completed
approval requested
approval completed
```

Example:

``` text
TASK-1001
  |
  +-- planner: 3.2s
  +-- repository: 1.8s
  +-- implementation: 8.4s
  +-- testing: 12.1s
  +-- debugging: 6.7s
  +-- testing: 10.3s
  +-- CI: 48.2s
```

------------------------------------------------------------------------

# 42. Evaluation Metrics

Track:

``` text
Task success rate
Test pass rate
Debugging success rate
Average iterations
Average latency
Tool calls per task
Files changed per task
Token usage
Estimated cost
Human intervention rate
Retrieval Recall@K
Retrieval Precision@K
Out-of-scope modification rate
```

Create a benchmark of 10--20 known issues.

------------------------------------------------------------------------

# 43. Sample POC Scenario

Create this repository:

``` text
sample-repo/order-service
```

with:

``` text
OrdersController
OrderService
OrderRepository
Order
OrderStatus
OrderServiceTests
```

Introduce a bug:

``` text
Already cancelled order
       |
       v
PaymentService
       |
       v
Exception
       |
       v
HTTP 500
```

The expected fix is:

``` text
CancelOrder()
    |
    v
Check status
    |
    +-- already cancelled --> return success
    |
    +-- otherwise
           |
           v
      cancellation logic
```

The agent should discover this rather than being given the exact file
and line.

------------------------------------------------------------------------

# 44. Example End-to-End Task

Developer submits:

``` json
{
  "repository": "https://github.com/example/order-service",
  "issue": "Fix duplicate order cancellation HTTP 500 and add regression tests."
}
```

System:

``` text
1. Create TASK-1001
2. Queue task
3. Worker claims task
4. Planner analyzes issue
5. Repository Agent searches code
6. Risk Agent evaluates change
7. Worktree created
8. Implementation Agent patches code
9. Testing Agent generates tests
10. dotnet test
11. If failed -> Debugging Agent
12. Retest
13. Git diff
14. CI
15. Security/policy
16. Create PR
17. Human approval
```

------------------------------------------------------------------------

# 45. Expected Final Result

``` json
{
  "task_id": "TASK-1001",
  "status": "READY_FOR_REVIEW",
  "summary": "Made order cancellation idempotent.",
  "files_changed": [
    "Services/OrderService.cs",
    "Tests/OrderServiceTests.cs"
  ],
  "tests": {
    "passed": 27,
    "failed": 0
  },
  "ci": "PASS",
  "risk": "LOW",
  "iterations": 2,
  "branch": "agent/TASK-1001",
  "pull_request_url": "...",
  "approval_required": true
}
```

------------------------------------------------------------------------

# 46. Implementation Sequence

Do not build everything simultaneously.

## Phase 1 --- Basic Agent

Build:

``` text
FastAPI
   |
Planner
   |
Repository Search
```

Goal:

``` text
Issue -> Plan -> Relevant Files
```

------------------------------------------------------------------------

## Phase 2 --- Tool Calling

Add:

``` text
read_file
search_code
find_symbol
```

Goal:

``` text
Issue
 -> Search
 -> Read
 -> Reason
```

------------------------------------------------------------------------

## Phase 3 --- Code Modification

Add:

``` text
Git worktree
apply_patch
git_diff
```

Goal:

``` text
Issue
 -> Understand
 -> Modify
 -> Review diff
```

------------------------------------------------------------------------

## Phase 4 --- Testing

Add:

``` text
dotnet build
dotnet test
```

Goal:

``` text
Modify
 -> Test
 -> Result
```

------------------------------------------------------------------------

## Phase 5 --- Debugging

Add:

``` text
FAIL
 |
 v
Debugger
 |
 v
Patch
 |
 v
Retest
```

Goal:

``` text
Autonomous bounded recovery
```

------------------------------------------------------------------------

## Phase 6 --- Redis + PostgreSQL

Add:

``` text
FastAPI
 |
Postgres task
 |
Redis queue
 |
Worker
```

Goal:

``` text
Asynchronous task execution
```

------------------------------------------------------------------------

## Phase 7 --- GitHub

Add:

``` text
branch
commit
push
PR
```

Goal:

``` text
Reviewable engineering change
```

------------------------------------------------------------------------

## Phase 8 --- CI/CD

Add:

``` text
GitHub Actions / Azure DevOps
```

Goal:

``` text
External validation
```

------------------------------------------------------------------------

## Phase 9 --- RAG

Add:

``` text
pgvector
hybrid retrieval
reranking
```

Goal:

``` text
Enterprise codebase understanding
```

------------------------------------------------------------------------

## Phase 10 --- Human Approval

Add:

``` text
risk
policy
approval
```

Goal:

``` text
Controlled autonomy
```

------------------------------------------------------------------------

## Phase 11 --- Next.js

Build:

``` text
Task submission
Live task timeline
Agent reasoning summary
Diff viewer
Test results
CI status
Approval controls
```

------------------------------------------------------------------------

## Phase 12 --- Docker/Kubernetes

Move from:

``` text
localhost
```

to:

``` text
Docker Compose
```

then:

``` text
Kubernetes
```

------------------------------------------------------------------------

# 47. Recommended Testing Strategy

Use three levels.

## Unit tests

Test:

``` text
planner parser
routing
policy
tools
repositories
```

## Integration tests

Test:

``` text
FastAPI
Redis
PostgreSQL
LangGraph
Git
```

## End-to-end tests

Run:

``` text
Issue
 -> Agent
 -> Code Change
 -> Tests
 -> Debug
 -> Git
 -> CI
```

Use a disposable test repository.

------------------------------------------------------------------------

# 48. Agent Testing

The agent itself needs testing.

Example:

``` text
Given:
"Fix duplicate order cancellation"

Expected:
OrderService.cs is discovered
OrderServiceTests.cs is discovered
No unrelated files modified
Tests generated
```

Create evaluation fixtures:

``` text
evaluation/
├── issue-001.yaml
├── issue-002.yaml
├── issue-003.yaml
└── expected/
```

------------------------------------------------------------------------

# 49. Prompt Design

Prompts should be version-controlled:

``` text
prompts/
├── planner.md
├── repository.md
├── implementation.md
├── testing.md
├── debugging.md
└── ci.md
```

Do not put critical business rules only inside prompts.

Important controls belong in code/policy:

``` text
Prompt = behavior guidance
Policy = authorization
Code = deterministic enforcement
```

------------------------------------------------------------------------

# 50. Model Abstraction

Do not hard-code the entire application around one model provider.

Create:

``` python
class LLMProvider:
    def generate(self, messages, tools=None):
        ...
```

Implement a provider adapter.

This allows future:

``` text
Provider A
Provider B
Local model
Enterprise model gateway
```

without changing the agent graph.

------------------------------------------------------------------------

# 51. Retry Strategy

Not every failure should trigger an LLM retry.

Classify failures:

``` text
Transient infrastructure error
       |
       v
Retry

Tool validation error
       |
       v
Agent correction

Test failure
       |
       v
Debugging Agent

Policy violation
       |
       v
Stop / Human

Authentication failure
       |
       v
Stop

Repeated failure
       |
       v
Human Review
```

------------------------------------------------------------------------

# 52. Idempotency

API task creation should support idempotency.

Example:

``` http
Idempotency-Key: abc-123
```

If the client sends the same request twice:

``` text
Request 1 -> TASK-1001
Request 2 -> TASK-1001
```

Do not create:

``` text
TASK-1001
TASK-1002
```

for the same operation.

------------------------------------------------------------------------

# 53. Security Model

Minimum controls:

``` text
Authentication
Authorization
Repository permissions
Workspace isolation
Tool allowlists
Command allowlists
Secret protection
Audit logging
Policy engine
Human approval
Branch protection
```

Treat repository content as **untrusted input**.

A malicious string inside a README should not be able to instruct the
agent to expose credentials or bypass policies.

------------------------------------------------------------------------

# 54. Production Readiness Boundaries

The POC should explicitly prohibit:

``` text
Direct production database access
Direct production deployment
Production secrets
Unrestricted shell
Automatic production merge
Unbounded agent loops
```

The production architecture can later introduce controlled workflows for
these capabilities, but they should not be part of the first POC.

------------------------------------------------------------------------

# 55. Multi-Server Failure Scenario

Example:

``` text
TASK-1001
   |
Worker-1
   |
Running tests
   |
Worker-1 crashes
```

Expected behavior:

``` text
Task remains persisted in PostgreSQL
          |
          v
Lease expires
          |
          v
Redis makes task available
          |
          v
Worker-2 claims task
          |
          v
Loads durable state/checkpoint
          |
          v
Recreates workspace
          |
          v
Resumes/restarts from safe point
```

This is why durable task state matters.

------------------------------------------------------------------------

# 56. API Server Failure Scenario

``` text
Browser
   |
Load Balancer
   |
API-1
   |
API-1 crashes
```

The task continues because:

``` text
Worker
   |
PostgreSQL
   |
Redis
```

are independent of API-1.

The browser reconnects:

``` text
Browser
   |
Load Balancer
   |
API-2
   |
PostgreSQL / Redis
```

and gets the same task state.

------------------------------------------------------------------------

# 57. Why Redis Is Important in Multi-Server Deployment

Without Redis:

``` text
Browser -> API-1
           |
       local memory
```

then:

``` text
Browser -> API-2
```

API-2 does not know about API-1's in-memory events.

With Redis:

``` text
API-1 ----+
          |
API-2 ----+---- Redis
          |
API-3 ----+
```

All API instances share the event/coordination layer.

------------------------------------------------------------------------

# 58. Why PostgreSQL Is Important

Redis is fast but should not be the permanent audit system.

PostgreSQL stores:

``` text
Task
Workflow state
Agent executions
Tool executions
File changes
Approvals
CI runs
Evaluation results
```

This allows you to answer:

``` text
Who started the task?
What did the agent do?
Which files did it read?
Which files did it modify?
Which tools did it call?
How many iterations occurred?
Which tests failed?
What changed before the PR?
Who approved it?
```

------------------------------------------------------------------------

# 59. Recommended Local Ports

``` text
Next.js             3000
FastAPI             8000
PostgreSQL          5432
Redis               6379
```

Optional:

``` text
OpenTelemetry       4317
Prometheus          9090
Grafana             3001
```

Do not add observability infrastructure until the core workflow is
functioning.

------------------------------------------------------------------------

# 60. Definition of Done

The POC is complete when:

``` text
[ ] Developer submits issue
[ ] Task is persisted
[ ] Task enters Redis queue
[ ] Worker claims task
[ ] Planner creates plan
[ ] Repository Agent discovers relevant files
[ ] Agent creates isolated Git worktree
[ ] Agent modifies code
[ ] Agent generates/updates tests
[ ] Tests execute
[ ] Failure triggers debugger
[ ] Debug loop is bounded
[ ] Git diff is captured
[ ] Branch is created
[ ] CI runs
[ ] CI result returns to system
[ ] PR-ready summary is generated
[ ] Human approval is required
[ ] Task events are visible
[ ] PostgreSQL contains audit history
[ ] Multiple workers can run concurrently
[ ] API can run on multiple instances
```

------------------------------------------------------------------------

# 61. Claude Implementation Instructions

When using Claude to implement this project, instruct it to follow these
rules:

1.  **Implement incrementally.**
2.  Do not build Kubernetes first.
3.  Do not create a monolithic Python application.
4.  Keep API, workflow, agents, tools, retrieval, persistence, and
    infrastructure separated.
5.  Use dependency injection where practical.
6.  Use typed models and explicit contracts.
7.  Keep all external integrations behind interfaces/adapters.
8.  Never allow unrestricted shell execution.
9.  Never allow agents to modify the developer's main repository working
    tree.
10. Use isolated Git worktrees.
11. Persist task state in PostgreSQL.
12. Use Redis for queue/event/lock responsibilities.
13. Make API instances stateless.
14. Make workers horizontally scalable.
15. Add unit and integration tests for every major component.
16. Keep prompts version-controlled.
17. Add structured logging with task IDs.
18. Make retry and iteration limits configurable.
19. Keep GitHub and Azure DevOps behind provider interfaces.
20. Keep LLM provider integration behind an adapter.
21. Use human approval before merge.
22. Do not add production deployment capabilities to the initial POC.

------------------------------------------------------------------------

# 62. First Claude Coding Task

Give Claude this implementation sequence:

``` text
STEP 1
Create the repository structure.

STEP 2
Implement FastAPI health endpoint.

STEP 3
Implement PostgreSQL connection and task model.

STEP 4
Implement Redis connection.

STEP 5
Implement POST /api/v1/tasks.

STEP 6
Persist task and enqueue task ID.

STEP 7
Implement worker that consumes tasks.

STEP 8
Implement AgentState.

STEP 9
Implement LangGraph planner node.

STEP 10
Implement search_code and read_file tools.

STEP 11
Implement repository analysis node.

STEP 12
Implement Git worktree manager.

STEP 13
Implement apply_patch and git_diff.

STEP 14
Implement testing node.

STEP 15
Implement debugging loop with max 3 iterations.

STEP 16
Implement Git branch/commit.

STEP 17
Add GitHub provider.

STEP 18
Add CI provider.

STEP 19
Add PostgreSQL audit events.

STEP 20
Add Next.js task timeline.

STEP 21
Add pgvector RAG.

STEP 22
Add policy engine and human approval.

STEP 23
Dockerize.

STEP 24
Add Kubernetes manifests.

STEP 25
Add evaluation benchmark.
```

Claude should finish and test each step before moving to the next.

------------------------------------------------------------------------

# 63. Final Architecture Mental Model

The most important thing to understand is:

``` text
                    AI Engineering Platform
                              |
        +---------------------+----------------------+
        |                     |                      |
        v                     v                      v
Engineering Knowledge   Agent Orchestration     Governance
        |                     |                      |
   Search / RAG          Plan / Act / Test      Policy / Approval
        |                     |                      |
        +---------------------+----------------------+
                              |
                              v
                    Coding-capable LLM
                              |
                              v
                        Tool Layer
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
          Files             Git             CI/CD
             |                |                |
             +----------------+----------------+
                              |
                              v
                         Reviewable PR
                              |
                              v
                         Human Merge
```

The architectural principle is:

> **The LLM is the reasoning worker. The engineering platform is the
> control plane.**

That distinction keeps the POC useful even as general-purpose coding
agents become more capable.

------------------------------------------------------------------------

# 64. Final Local-to-Production Evolution

``` text
LOCAL
FastAPI + Worker + Redis + PostgreSQL + Git
              |
              v
DOCKER COMPOSE
API + Worker + Redis + PostgreSQL + Next.js
              |
              v
MULTI-WORKER
Multiple Agent Workers + Redis Queue
              |
              v
MULTI-SERVER
Load Balancer + Multiple API + Multiple Workers
              |
              v
KUBERNETES
Deployments + Services + Ingress + Autoscaling
              |
              v
ENTERPRISE
SSO/OIDC + Policy + Audit + RAG + CI/CD
+ Observability + Evaluation + Provider Abstractions
```

This progression should be preserved throughout implementation.

The same codebase should work locally and evolve into the multi-server
architecture without rewriting the core agent workflow.
