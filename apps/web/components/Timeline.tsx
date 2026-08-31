"use client";

import type { TaskEvent } from "@/lib/api";

/** The one-line summary each event type deserves in the timeline. */
function describe(event: TaskEvent): string {
  const payload = event.payload as Record<string, unknown>;
  const value = (key: string) => payload?.[key];

  switch (event.type) {
    case "PLAN_CREATED":
      return `${value("summary") ?? ""} (${value("steps") ?? 0} steps)`;
    case "FILES_DISCOVERED": {
      const files = (value("files") as string[]) ?? [];
      return files.length ? files.join(", ") : "no files identified";
    }
    case "RISK_ASSESSED":
      return `${value("risk")}${value("approval_required") ? " · approval required" : ""}`;
    case "WORKSPACE_CREATED":
      return String(value("branch") ?? "");
    case "TOOL_CALLED":
      return String(value("tool") ?? "");
    case "TOOL_COMPLETED":
    case "TOOL_FAILED":
      return `${value("tool")} · ${value("duration_ms")}ms`;
    case "FILE_CHANGED":
      return String(value("path") ?? "");
    case "TESTS_PASSED":
      return value("skipped")
        ? String(value("reason") ?? "skipped")
        : `${value("passed") ?? 0} passed`;
    case "TEST_FAILED": {
      const failures = (value("failures") as string[]) ?? [];
      return `${value("failed")} failed · ${failures[0]?.split("\n")[0] ?? ""}`;
    }
    case "DEBUG_ITERATION":
      return `iteration ${value("iteration")}`;
    case "NO_PROGRESS_DETECTED":
      return String(value("reason") ?? "");
    case "POLICY_EVALUATED": {
      const findings = (value("findings") as string[]) ?? [];
      return `${value("action")} · risk ${value("risk")}${
        findings.length ? ` · ${findings.join("; ")}` : ""
      }`;
    }
    case "POLICY_BLOCKED":
      return ((value("findings") as string[]) ?? []).join("; ");
    case "COMMIT_CREATED":
      return `${String(value("sha") ?? "").slice(0, 10)} on ${value("branch")}`;
    case "CI_STARTED":
      return `${value("provider")} · ${value("branch")}`;
    case "CI_COMPLETED":
      return String(value("status") ?? "");
    case "PR_CREATED":
      return String(value("url") ?? "");
    case "APPROVAL_REQUESTED":
      return `risk ${value("risk")} · ${
        ((value("files") as string[]) ?? []).length
      } file(s) changed`;
    case "NODE_STARTED":
    case "NODE_COMPLETED":
      return String(value("node") ?? "");
    default:
      return "";
  }
}

const HIDDEN = new Set(["NODE_COMPLETED", "TOOL_COMPLETED"]);

export function Timeline({
  events,
  showEverything,
}: {
  events: TaskEvent[];
  showEverything: boolean;
}) {
  const visible = showEverything
    ? events
    : events.filter((event) => !HIDDEN.has(event.type));

  if (!visible.length) {
    return <p className="empty">No events yet.</p>;
  }

  return (
    <ol className="timeline">
      {visible.map((event) => (
        <li key={event.id}>
          <span className="time">
            {new Date(event.timestamp).toLocaleTimeString(undefined, {
              hour12: false,
            })}
          </span>
          <span>
            <span className="type">{event.type.replace(/_/g, " ")}</span>
            {describe(event) && (
              <>
                <br />
                <span className="detail">{describe(event)}</span>
              </>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}
