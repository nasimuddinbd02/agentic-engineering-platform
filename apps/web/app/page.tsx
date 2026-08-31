"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { RiskBadge, StatusBadge, TestBadge } from "@/components/StatusBadge";
import { createTask, listTasks, type TaskSummary } from "@/lib/api";

const REFRESH_MS = 3000;

export default function HomePage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setTasks(await listTasks());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <div className="grid">
      <section>
        <div className="panel">
          <h2>Tasks</h2>
          {error && <p className="error">Cannot reach the API: {error}</p>}
          {loading && !tasks.length && <p className="empty">Loading…</p>}
          {!loading && !tasks.length && !error && (
            <p className="empty">
              No tasks yet. Submit an engineering issue to get started.
            </p>
          )}
          {tasks.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Issue</th>
                  <th>Status</th>
                  <th>Tests</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.task_id}>
                    <td className="mono">
                      <Link href={`/tasks/${task.task_id}`}>{task.task_id}</Link>
                    </td>
                    <td>
                      {task.issue.length > 90
                        ? `${task.issue.slice(0, 90)}…`
                        : task.issue}
                    </td>
                    <td>
                      <div className="row">
                        <StatusBadge status={task.status} />
                        <RiskBadge risk={task.risk_level} />
                      </div>
                    </td>
                    <td>
                      <TestBadge
                        passed={task.tests_passed}
                        failed={task.tests_failed}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <aside>
        <SubmitForm onSubmitted={refresh} />
      </aside>
    </div>
  );
}

function SubmitForm({ onSubmitted }: { onSubmitted: () => void }) {
  const [repositoryPath, setRepositoryPath] = useState("");
  const [issue, setIssue] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await createTask({
        repository: repositoryPath,
        repository_path: repositoryPath,
        issue,
      });
      setMessage(`Queued ${created.task_id}`);
      setIssue("");
      onSubmitted();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New task</h2>

      <label htmlFor="repository">Repository path on the worker</label>
      <input
        id="repository"
        value={repositoryPath}
        onChange={(event) => setRepositoryPath(event.target.value)}
        placeholder="D:\Projects\order-service"
        required
      />

      <label htmlFor="issue">Engineering issue</label>
      <textarea
        id="issue"
        value={issue}
        onChange={(event) => setIssue(event.target.value)}
        placeholder="Cancelling an already cancelled order returns HTTP 500 instead of succeeding. Make cancellation idempotent and add a regression test."
        minLength={8}
        required
      />

      <button type="submit" disabled={busy}>
        {busy ? "Submitting…" : "Submit task"}
      </button>

      {message && (
        <p className="muted" style={{ marginBottom: 0 }}>
          {message}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        The API returns 202 immediately; a worker picks the task up from the
        queue. Nothing runs inside the request.
      </p>
    </form>
  );
}
