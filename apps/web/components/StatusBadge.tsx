import type { TaskStatus } from "@/lib/api";

const TONE: Record<string, "ok" | "warn" | "bad" | "busy"> = {
  COMPLETED: "ok",
  CI_PASSED: "ok",
  TEST_PASSED: "ok",
  READY_FOR_REVIEW: "warn",
  HUMAN_REVIEW_REQUIRED: "warn",
  HUMAN_APPROVED: "ok",
  FAILED: "bad",
  REJECTED: "bad",
  CANCELLED: "bad",
  TEST_FAILED: "bad",
  CI_FAILED: "bad",
};

export function StatusBadge({ status }: { status: TaskStatus | string }) {
  const tone = TONE[status] ?? "busy";
  return <span className={`badge ${tone}`}>{status.replace(/_/g, " ")}</span>;
}

export function RiskBadge({ risk }: { risk: string | null }) {
  if (!risk) return null;
  const tone = risk === "HIGH" ? "bad" : risk === "MEDIUM" ? "warn" : "ok";
  return <span className={`badge ${tone}`}>risk {risk}</span>;
}

export function TestBadge({
  passed,
  failed,
}: {
  passed: number;
  failed: number;
}) {
  if (passed === 0 && failed === 0) {
    return <span className="badge">tests not run</span>;
  }
  return (
    <span className={`badge ${failed > 0 ? "bad" : "ok"}`}>
      {passed} passed{failed > 0 ? `, ${failed} failed` : ""}
    </span>
  );
}
