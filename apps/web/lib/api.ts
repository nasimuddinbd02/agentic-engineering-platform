/**
 * Typed client for the agent API (section 29).
 *
 * The browser talks to FastAPI directly; there is no Next.js server state, so
 * any API instance behind the load balancer can serve any request.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type TaskStatus =
  | "QUEUED"
  | "PLANNING"
  | "REPOSITORY_ANALYSIS"
  | "RISK_ASSESSMENT"
  | "IMPLEMENTING"
  | "TESTING"
  | "TEST_FAILED"
  | "DEBUGGING"
  | "TEST_PASSED"
  | "CI_RUNNING"
  | "CI_FAILED"
  | "CI_DEBUGGING"
  | "CI_PASSED"
  | "POLICY_CHECK"
  | "READY_FOR_REVIEW"
  | "HUMAN_APPROVED"
  | "PR_CREATED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "REJECTED"
  | "HUMAN_REVIEW_REQUIRED";

export const TERMINAL_STATUSES: TaskStatus[] = [
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "REJECTED",
  "HUMAN_REVIEW_REQUIRED",
];

export interface TaskSummary {
  task_id: string;
  status: TaskStatus;
  issue: string;
  repository_url: string;
  risk_level: string | null;
  current_node: string | null;
  iteration: number;
  approval_required: boolean;
  branch: string | null;
  commit_sha: string | null;
  pull_request_url: string | null;
  summary: string | null;
  error: string | null;
  files_changed: string[];
  tests_passed: number;
  tests_failed: number;
  ci_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskEvent {
  id: string;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface AgentRun {
  node: string;
  agent: string;
  status: string;
  iteration: number;
  duration_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  error: string | null;
}

export interface ToolCall {
  tool: string;
  ok: boolean;
  arguments: Record<string, unknown>;
  duration_ms: number | null;
  error: string | null;
}

export interface FileChange {
  path: string;
  change_type: string;
  iteration: number;
  lines_added: number;
  lines_removed: number;
}

export interface CIRun {
  provider: string;
  status: string;
  url: string | null;
  iteration: number;
}

export interface Approval {
  id: string;
  status: string;
  requested_reason: string | null;
  decided_by: string | null;
  reason: string | null;
}

export interface TaskDetail {
  task: TaskSummary;
  events: TaskEvent[];
  runs: AgentRun[];
  tool_calls: ToolCall[];
  file_changes: FileChange[];
  ci_runs: CIRun[];
  approvals: Approval[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail || response.statusText}`);
  }
  return (await response.json()) as T;
}

export function listTasks(limit = 50): Promise<TaskSummary[]> {
  return request<TaskSummary[]>(`/api/v1/tasks?limit=${limit}`);
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>(`/api/v1/tasks/${taskId}`);
}

export function createTask(body: {
  repository: string;
  repository_path?: string;
  issue: string;
  created_by?: string;
}): Promise<{ task_id: string; status: string }> {
  return request(`/api/v1/tasks`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getDiff(taskId: string): Promise<string> {
  const response = await fetch(`${API_URL}/api/v1/tasks/${taskId}/diff`, {
    cache: "no-store",
  });
  if (!response.ok) return "";
  return response.text();
}

export function decide(
  taskId: string,
  action: "approve" | "reject" | "cancel",
  body: { decided_by?: string; reason?: string },
): Promise<TaskSummary> {
  return request<TaskSummary>(`/api/v1/tasks/${taskId}/${action}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Subscribe to a task's live timeline.
 *
 * The server replays everything durable before following the live channel, so
 * `after` lets a reconnect pick up exactly where it left off (section 32).
 */
export function subscribeToEvents(
  taskId: string,
  after: number,
  onEvent: (event: TaskEvent) => void,
  onEnd: () => void,
): () => void {
  const source = new EventSource(
    `${API_URL}/api/v1/tasks/${taskId}/events?after=${after}`,
  );

  const handle = (raw: MessageEvent) => {
    try {
      const parsed = JSON.parse(raw.data) as TaskEvent & { type: string };
      if (parsed.type === "STREAM_END") {
        source.close();
        onEnd();
        return;
      }
      onEvent(parsed);
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  };

  source.onmessage = handle;
  // FastAPI sends a named `event:` field, which bypasses onmessage.
  source.addEventListener("STREAM_END", () => {
    source.close();
    onEnd();
  });
  for (const type of KNOWN_EVENT_TYPES) {
    source.addEventListener(type, handle as EventListener);
  }
  source.onerror = () => {
    source.close();
    onEnd();
  };

  return () => source.close();
}

export const KNOWN_EVENT_TYPES = [
  "TASK_CREATED",
  "TASK_CLAIMED",
  "NODE_STARTED",
  "NODE_COMPLETED",
  "TOOL_CALLED",
  "TOOL_COMPLETED",
  "TOOL_FAILED",
  "PLAN_CREATED",
  "FILES_DISCOVERED",
  "RISK_ASSESSED",
  "WORKSPACE_CREATED",
  "FILE_CHANGED",
  "TESTS_STARTED",
  "TESTS_PASSED",
  "TEST_FAILED",
  "DEBUG_ITERATION",
  "NO_PROGRESS_DETECTED",
  "POLICY_EVALUATED",
  "POLICY_BLOCKED",
  "COMMIT_CREATED",
  "CI_STARTED",
  "CI_COMPLETED",
  "APPROVAL_REQUESTED",
  "APPROVAL_GRANTED",
  "APPROVAL_REJECTED",
  "PR_CREATED",
  "TASK_COMPLETED",
  "TASK_FAILED",
  "TASK_CANCELLED",
];
