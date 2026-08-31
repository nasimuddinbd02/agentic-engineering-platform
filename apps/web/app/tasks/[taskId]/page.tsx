"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";

import { DiffView } from "@/components/DiffView";
import { RiskBadge, StatusBadge, TestBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";
import {
  decide,
  getDiff,
  getTask,
  subscribeToEvents,
  TERMINAL_STATUSES,
  type TaskDetail,
  type TaskEvent,
} from "@/lib/api";

export default function TaskPage({
  params,
}: {
  params: Promise<{ taskId: string }>;
}) {
  const { taskId } = use(params);

  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [diff, setDiff] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [verbose, setVerbose] = useState(false);
  const highest = useRef(0);

  const load = useCallback(async () => {
    try {
      const loaded = await getTask(taskId);
      setDetail(loaded);
      setEvents(loaded.events);
      highest.current = loaded.events.at(-1)?.sequence ?? 0;
      setDiff(await getDiff(taskId));
      setError(null);
      return loaded;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return null;
    }
  }, [taskId]);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;

    void (async () => {
      const loaded = await load();
      if (!loaded) return;
      if (TERMINAL_STATUSES.includes(loaded.task.status)) return;

      setLive(true);
      unsubscribe = subscribeToEvents(
        taskId,
        highest.current,
        (event) => {
          highest.current = Math.max(highest.current, event.sequence);
          setEvents((current) =>
            current.some((existing) => existing.id === event.id)
              ? current
              : [...current, event],
          );
        },
        () => {
          setLive(false);
          void load();
        },
      );
    })();

    return () => unsubscribe?.();
  }, [taskId, load]);

  if (error && !detail) {
    return (
      <div className="panel">
        <p className="error">{error}</p>
        <Link href="/">← All tasks</Link>
      </div>
    );
  }
  if (!detail) return <p className="empty">Loading…</p>;

  const { task } = detail;
  const awaitingReview = task.status === "READY_FOR_REVIEW";

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link href="/">← All tasks</Link>
        <span className="mono muted">{task.task_id}</span>
        <StatusBadge status={task.status} />
        <RiskBadge risk={task.risk_level} />
        <TestBadge passed={task.tests_passed} failed={task.tests_failed} />
        {live && <span className="badge busy">live</span>}
      </div>

      <div className="grid">
        <section>
          <div className="panel">
            <h2>Issue</h2>
            <p style={{ marginTop: 0 }}>{task.issue}</p>
            {task.summary && (
              <>
                <h2 style={{ marginTop: 16 }}>Agent summary</h2>
                <p style={{ margin: 0 }}>{task.summary}</p>
              </>
            )}
            {task.error && <p className="error">{task.error}</p>}
          </div>

          <div className="panel">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>Timeline</h2>
              <button
                className="secondary"
                onClick={() => setVerbose((value) => !value)}
              >
                {verbose ? "Hide tool detail" : "Show tool detail"}
              </button>
            </div>
            <div style={{ marginTop: 12 }}>
              <Timeline events={events} showEverything={verbose} />
            </div>
          </div>

          <div className="panel">
            <h2>Diff</h2>
            <DiffView diff={diff} />
          </div>
        </section>

        <aside>
          {awaitingReview && (
            <ApprovalPanel taskId={taskId} onDecided={load} detail={detail} />
          )}

          <div className="panel">
            <h2>Result</h2>
            <dl className="kv">
              <dt>Repository</dt>
              <dd className="mono">{task.repository_url}</dd>
              <dt>Branch</dt>
              <dd className="mono">{task.branch ?? "—"}</dd>
              <dt>Commit</dt>
              <dd className="mono">
                {task.commit_sha ? task.commit_sha.slice(0, 12) : "—"}
              </dd>
              <dt>Pull request</dt>
              <dd className="mono">
                {task.pull_request_url ? (
                  <a href={task.pull_request_url}>open</a>
                ) : (
                  "—"
                )}
              </dd>
              <dt>CI</dt>
              <dd>{task.ci_status || "not run"}</dd>
              <dt>Debug iterations</dt>
              <dd>{task.iteration}</dd>
              <dt>Current node</dt>
              <dd className="mono">{task.current_node ?? "—"}</dd>
            </dl>
          </div>

          <div className="panel">
            <h2>Files changed ({detail.file_changes.length})</h2>
            {detail.file_changes.length === 0 ? (
              <p className="empty">None.</p>
            ) : (
              <table>
                <tbody>
                  {detail.file_changes.map((change, index) => (
                    <tr key={`${change.path}-${index}`}>
                      <td className="mono">{change.path}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <span style={{ color: "var(--ok)" }}>
                          +{change.lines_added}
                        </span>{" "}
                        <span style={{ color: "var(--bad)" }}>
                          −{change.lines_removed}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel">
            <h2>Node timings</h2>
            {detail.runs.length === 0 ? (
              <p className="empty">Not started.</p>
            ) : (
              <table>
                <tbody>
                  {detail.runs.map((run, index) => (
                    <tr key={`${run.node}-${index}`}>
                      <td className="mono">{run.node}</td>
                      <td className="muted">{run.agent}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {run.duration_ms != null
                          ? `${(run.duration_ms / 1000).toFixed(1)}s`
                          : "—"}
                      </td>
                      <td>
                        {run.status !== "COMPLETED" && (
                          <span className="badge bad">{run.status}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel">
            <h2>Tool calls ({detail.tool_calls.length})</h2>
            {detail.tool_calls.length === 0 ? (
              <p className="empty">None.</p>
            ) : (
              <table>
                <tbody>
                  {detail.tool_calls.map((call, index) => (
                    <tr key={index}>
                      <td className="mono">{call.tool}</td>
                      <td>
                        {call.ok ? (
                          <span className="muted">ok</span>
                        ) : (
                          <span className="error">{call.error?.slice(0, 80)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

function ApprovalPanel({
  taskId,
  detail,
  onDecided,
}: {
  taskId: string;
  detail: TaskDetail;
  onDecided: () => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [who, setWho] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pending = detail.approvals.find(
    (approval) => approval.status === "PENDING",
  );

  async function act(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await decide(taskId, action, { decided_by: who || undefined, reason });
      await onDecided();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Human approval required</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        {pending?.requested_reason ?? "This change is waiting for a reviewer."}
      </p>

      <label htmlFor="who">Your name</label>
      <input
        id="who"
        value={who}
        onChange={(event) => setWho(event.target.value)}
        placeholder="reviewer"
      />

      <label htmlFor="reason">Note (optional)</label>
      <input
        id="reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />

      <div className="row">
        <button disabled={busy} onClick={() => void act("approve")}>
          Approve
        </button>
        <button
          className="danger"
          disabled={busy}
          onClick={() => void act("reject")}
        >
          Reject
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        Approving records the decision and completes the task. Merging stays
        with a person — the agent never merges.
      </p>
    </div>
  );
}
