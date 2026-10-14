import { useState } from "react";
import { Link } from "react-router-dom";
import { questionFor, useAdvisorAvailable, useAlerts, useDismissAlert } from "./alerts";
import type { Alert, AlertSeverity } from "./alerts";
import { Card } from "./ui/Shell";

const SHOWN = 5;

// Severity is carried by the dot's colour and by a visually hidden word, so it does
// not depend on colour alone.
const DOT: Record<AlertSeverity, string> = {
  urgent: "bg-clay",
  warn: "bg-acid",
  info: "bg-muted",
};

function AlertRow({ alert, onAsk }: { alert: Alert; onAsk?: (question: string) => void }) {
  const dismiss = useDismissAlert();
  return (
    <li className="flex flex-wrap items-start gap-x-3 border-b border-line py-3 last:border-0">
      <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[alert.severity]}`} />
      <div className="min-w-0 flex-1 basis-48">
        <span className="sr-only">{alert.severity}: </span>
        <Link to={alert.href} className="text-sm font-medium hover:text-acid">
          {alert.title}
        </Link>
        <p className="mt-0.5 text-xs text-muted">{alert.body}</p>
        {dismiss.isError && (
          <p className="text-xs text-clay">{(dismiss.error as Error).message}</p>
        )}
      </div>
      <div className="ml-5 flex shrink-0">
        {onAsk && (
          <button
            type="button"
            aria-label={`Ask advisor about ${alert.title}`}
            onClick={() => onAsk(questionFor(alert))}
            className="label px-2 py-1 transition-colors hover:text-bone"
          >
            Ask advisor
          </button>
        )}
        <button
          type="button"
          aria-label={`Dismiss ${alert.title}`}
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate(alert.key)}
          className="label px-2 py-1 transition-colors hover:text-bone disabled:opacity-50"
        >
          Dismiss
        </button>
      </div>
    </li>
  );
}

/** `onAsk` receives a ready-made question about one alert. The button only appears when
 * a model is configured — without one there is nothing to hand the question to. */
export function AlertsCard({ onAsk }: { onAsk?: (question: string) => void }) {
  const { data: alerts = [], isError } = useAlerts();
  const canAsk = useAdvisorAvailable(onAsk !== undefined);
  const [showAll, setShowAll] = useState(false);
  // A failed fetch must not look the same as "nothing needs attention".
  if (isError) return <p className="mb-8 text-sm text-clay">Couldn't load alerts.</p>;
  if (alerts.length === 0) return null;
  const extra = showAll ? 0 : alerts.length - SHOWN;
  return (
    <Card className="mb-8" delay={40}>
      <h2 id="alerts" className="mb-1 text-sm font-medium">
        Needs attention
      </h2>
      <ul>
        {(showAll ? alerts : alerts.slice(0, SHOWN)).map((a) => (
          <AlertRow key={a.key} alert={a} onAsk={canAsk ? onAsk : undefined} />
        ))}
      </ul>
      {extra > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="label mt-3 transition-colors hover:text-bone"
        >
          Show {extra} more
        </button>
      )}
    </Card>
  );
}

export function AlertBell() {
  const { data: alerts = [], isPending, isError } = useAlerts();
  const n = alerts.length;
  const name = isError
    ? "Alerts unavailable"
    : isPending
      ? "Loading alerts"
      : n === 0
        ? "No alerts"
        : `${n} alert${n === 1 ? "" : "s"}`;
  return (
    <Link
      to="/#alerts"
      aria-label={name}
      className="relative ml-auto px-1 text-base leading-none text-muted transition-colors hover:text-bone"
    >
      <span aria-hidden>◉</span>
      {n > 0 && (
        <span
          aria-hidden
          className="tnum absolute -top-2 -right-2 rounded-full bg-acid px-1 text-[10px] leading-4 text-white"
        >
          {n}
        </span>
      )}
    </Link>
  );
}
