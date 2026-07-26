import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";
import type { NetWorthPoint } from "./data";
import { AreaChart } from "./charts";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

type Insight = { summary: string; model: string };

export function NetWorthChart({ points }: { points: NetWorthPoint[] }) {
  if (points.length < 2) {
    return (
      <Empty>
        {points.length === 1
          ? "One day recorded so far — the line appears once there are two."
          : "No history yet. Balances are recorded daily from now on."}
      </Empty>
    );
  }

  const change = points[points.length - 1].net - points[0].net;

  return (
    <div>
      <AreaChart
        valueLabel="Net worth"
        points={points.map((p) => ({ label: p.on, value: p.net }))}
      />
      <p className={`mt-1 text-[11px] ${change >= 0 ? "text-acid" : "text-clay"}`}>
        {change >= 0 ? "+" : ""}
        {usd(change)} over {points.length} days
      </p>
    </div>
  );
}

export function Assistant() {
  const [question, setQuestion] = useState("");
  const { data: availability } = useQuery({
    queryKey: ["insights-available"],
    queryFn: () => apiFetch<{ available: boolean }>("/insights/available"),
  });

  const ask = useMutation({
    mutationFn: (q: string) =>
      apiFetch<Insight>("/insights", {
        method: "POST",
        body: JSON.stringify({ question: q || null }),
      }),
  });

  if (!availability?.available) return null;

  return (
    <Card className="mt-4" delay={300}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">What's up with my money</h2>
        <span className="label">Reads only your own data</span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask.mutate(question);
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <input
          className="min-w-0 flex-1"
          placeholder="Optional: ask something specific…"
          aria-label="Question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button disabled={ask.isPending} className="btn">
          {ask.isPending ? "Thinking…" : "Ask"}
        </button>
      </form>

      {ask.isError && (
        <p className="mt-3 rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
          {(ask.error as Error).message}
        </p>
      )}

      {ask.data && <Markdown text={ask.data.summary} />}
    </Card>
  );
}

/** ponytail: the model is told to emit `## heading`, `- bullet`, `**bold**` and nothing
 *  else, so this handles exactly that instead of pulling in a markdown library. */
function Markdown({ text }: { text: string }) {
  const bold = (s: string) =>
    s.split(/\*\*(.+?)\*\*/g).map((part, i) =>
      i % 2 === 1 ? (
        <strong key={i} className="font-medium text-bone">
          {part}
        </strong>
      ) : (
        part
      ),
    );

  return (
    <div className="mt-4 flex flex-col gap-1.5 text-sm leading-relaxed text-muted">
      {text.split("\n").map((raw, i) => {
        const line = raw.trim();
        if (!line) return null;
        if (line.startsWith("##"))
          return (
            <h3 key={i} className="label mt-3 first:mt-0">
              {line.replace(/^#+\s*/, "")}
            </h3>
          );
        if (line.startsWith("- ") || line.startsWith("* "))
          return (
            <p key={i} className="flex gap-2">
              <span className="text-acid">•</span>
              <span>{bold(line.slice(2))}</span>
            </p>
          );
        return <p key={i}>{bold(line)}</p>;
      })}
    </div>
  );
}
