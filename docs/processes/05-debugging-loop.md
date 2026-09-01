# Process 5 — The Bounded Debugging Loop

**The most important agentic behaviour in the platform — and the one most in
need of a leash.**

An agent that can retry is useful. An agent that can retry *forever* burns money
and eventually damages the codebase. This process is about knowing when to stop.

---

## The loop

```mermaid
flowchart TD
    run["run_tests<br/><b>the platform runs them</b>"] --> pass{"passed?"}
    pass -->|yes| policy["security_policy"]
    pass -->|no| B1{"iteration<br/>&ge; max?"}
    B1 -->|yes| halt
    B1 -->|no| B2{"same failure<br/>signature twice?"}
    B2 -->|yes| halt
    B2 -->|no| B3{"changed files<br/>&gt; max?"}
    B3 -->|yes| halt
    B3 -->|no| debug["debugging agent<br/>diagnose + patch"]
    debug --> run

    halt["<b>halt</b><br/>HUMAN_REVIEW_REQUIRED<br/>nothing committed"]

    style run fill:#2563eb,color:#fff
    style policy fill:#16a34a,color:#fff
    style halt fill:#dc2626,color:#fff
```

Three independent brakes. Any one of them ends the loop.

---

## Brake 1 — a hard iteration cap

`MAX_AGENT_ITERATIONS` (default **3**). Simple, and the only brake that is
guaranteed to fire.

## Brake 2 — failure fingerprinting

The interesting one. An agent can burn its whole budget producing three
variations of the same broken idea. Fingerprinting notices.

Each failure is normalised, then hashed:

```mermaid
flowchart LR
    R["PaymentGatewayException: Order 20ae256e-... <br/>already refunded at line 42"] --> N["normalise"]
    N --> S["paymentgatewayexception |<br/>order &lt;guid&gt; already refunded at :&lt;line&gt;"]
    S --> H["sha256 -> a3f2b1c8d4e5f6a7"]
```

Normalisation strips everything that varies between identical runs:

| Removed | Why |
|---|---|
| GUIDs | a new order id each run |
| timestamps | wall clock |
| durations (`12ms`) | timing noise |
| line numbers | shift as the agent edits |
| file paths | differ per worktree |
| hex addresses | not meaningful |

Order matters here — timestamps are consumed *before* the line-number rule,
which would otherwise chew through `10:00:00`. That was a real bug caught by a
unit test.

```mermaid
flowchart LR
    i1["iteration 1<br/>[sig-A]"] --> i2["iteration 2<br/>[sig-A]"]
    i2 --> D{"identical"}
    D --> STOP["not making progress<br/>-> human"]

    style STOP fill:#dc2626,color:#fff
```

Two identical rounds means stop — which usually fires *before* the iteration
cap, saving a wasted attempt. An empty failure set is explicitly not evidence of
being stuck.

## Brake 3 — the scope guard

If `modified_files` exceeds `MAX_FILES_PER_TASK`, stop. A change that keeps
growing is a change that is no longer understood.

---

## What the debugging agent sees

It is shown every previous attempt, so it cannot silently repeat itself:

```
Debugging iteration 2 of 3.

Current test failures:
  OrderCancellationIdempotencyTests.CancelOrder_AlreadyCancelled_ReturnsSuccess
  Assert.Equal() Failure: Expected Cancelled, Actual NotCancellable

Previous attempts:
  - iteration 0: CancelOrder_AlreadyCancelled_ReturnsSuccess: Assert.Equal...
  - iteration 1 analysis: Added a guard returning NotCancellable for an
    already-cancelled order.
```

The prompt asks it to form **one hypothesis before touching a file**, and gives
it explicit permission to fix the *test* when the production behaviour is right
and the expectation is wrong — with the reason stated.

Two things it may never do: delete or weaken a test to make the suite green, and
widen the change to unrelated files.

---

## Why the platform runs the tests

`run_tests` is a platform node, not an agent action. The result comes from a
process exit code and parsed output:

```mermaid
flowchart LR
    N["run_tests node"] --> C["dotnet test<br/>allowlisted argv, no shell"]
    C --> P["parse: totals,<br/>failing names, exceptions"]
    P --> ST["tests_passed / tests_failed<br/>failure_signatures"]
    ST --> R["routing decides"]

    style C fill:#2563eb,color:#fff
```

If an agent reported its own results, "the tests pass" would be a claim. Here it
is a measurement. The parser is tested against **verbatim** `dotnet test` output
captured from the sample repository, not against an idea of the format.

Edge cases it handles: a build error becomes one synthetic failure (nothing ran,
but the run failed), and a timeout is never `ok` regardless of exit code.

---

## A real run

From the end-to-end test, which exercises exactly this:

```mermaid
sequenceDiagram
    participant I as implementation
    participant T as run_tests
    participant D as debugging

    I->>I: guard returns NotCancellable
    I->>T: 
    T->>T: dotnet test -> 1 failed, 8 passed
    Note over T: expected Cancelled, got NotCancellable
    T->>D: fingerprint [sig-A], iteration 0 < 3
    D->>D: "already cancelled is a successful no-op,<br/>not a conflict"
    D->>D: apply_patch -> return Cancelled
    D->>T: 
    T->>T: dotnet test -> 9 passed
    Note over T: proceed to policy gate
```

The companion test scripts a debugger that *never* fixes anything and asserts
the opposite outcome: `HUMAN_REVIEW_REQUIRED`, no commit, and a
`NO_PROGRESS_DETECTED` event.

---

## CI has its own budget

The same shape, a separate counter (`MAX_CI_ITERATIONS`, default 2), because CI
failures have different causes — see
[09-cicd-integration.md](09-cicd-integration.md).

---

## Where the code lives

| Concern | File |
|---|---|
| the brakes | `graph/routing.py` (`after_tests`) |
| fingerprinting | `graph/fingerprint.py` |
| test execution and parsing | `tools/testing/test.py` |
| the agent | `agents/debugging_agent.py` |
| its prompt | `prompts/debugging.md` |
| loop nodes | `graph/nodes.py` |

**Tests:** `tests/unit/test_routing_and_fingerprint.py`,
`tests/unit/test_test_output_parser.py`,
`tests/graph/test_workflow_end_to_end.py`
