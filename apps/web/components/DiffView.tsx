"use client";

/** Minimal unified-diff colouring - enough to review a small agent change. */
export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="empty">No changes recorded for this task.</p>;
  }

  return (
    <pre className="diff">
      {diff.split("\n").map((line, index) => (
        <div key={index} className={classify(line)}>
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function classify(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("diff ") || line.startsWith("index ")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "";
}
