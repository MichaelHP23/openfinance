import { useEffect, useRef, useState } from "react";
import { usd, usdCompact } from "./money";
import { ACCENT, OTHER, SERIES } from "./palette";

/** Measures its container so marks are drawn in real pixels and never distort. */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Tooltip({ x, children }: { x: number; children: React.ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-line bg-ink px-2.5 py-1.5 text-[11px] whitespace-nowrap shadow-lg"
      style={{ left: x }}
    >
      {children}
    </div>
  );
}

export type Point = { label: string; value: number };

export function AreaChart({
  points,
  height = 160,
  color = ACCENT,
  valueLabel = "",
}: {
  points: Point[];
  height?: number;
  color?: string;
  valueLabel?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const pad = { top: 10, bottom: 18, left: 0, right: 0 };
  const plotH = height - pad.top - pad.bottom;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;

  const x = (i: number) => (points.length === 1 ? width / 2 : (i / (points.length - 1)) * width);
  const y = (v: number) => pad.top + plotH - ((v - min) / span) * plotH;

  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = `${line} L${width},${pad.top + plotH} L0,${pad.top + plotH} Z`;
  const active = hover === null ? null : points[hover];

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${valueLabel || "Value"} from ${usd(points[0].value)} to ${usd(points[points.length - 1].value)}`}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const ratio = (e.clientX - rect.left) / rect.width;
            setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
          }}
          onPointerLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id={`fill-${color.slice(1)}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.24" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Recessive baseline, so the eye reads the mark and not the chrome. */}
          <line
            x1="0"
            x2={width}
            y1={pad.top + plotH}
            y2={pad.top + plotH}
            stroke="var(--color-line)"
          />
          <path d={area} fill={`url(#fill-${color.slice(1)})`} />
          <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />

          {active && (
            <>
              <line
                x1={x(hover!)}
                x2={x(hover!)}
                y1={pad.top}
                y2={pad.top + plotH}
                stroke="var(--color-line)"
              />
              {/* Surface ring keeps the marker legible over the fill. */}
              <circle cx={x(hover!)} cy={y(active.value)} r="5" fill="var(--color-ink)" />
              <circle cx={x(hover!)} cy={y(active.value)} r="4" fill={color} />
            </>
          )}
        </svg>
      )}

      {active && <Tooltip x={x(hover!)}>
        <span className="block text-bone">{usd(active.value)}</span>
        <span className="text-muted">{active.label}</span>
      </Tooltip>}

      <div className="tnum flex justify-between text-[11px] text-muted">
        <span>{points[0]?.label}</span>
        <span>{points[points.length - 1]?.label}</span>
      </div>
    </div>
  );
}

export function BarChart({
  bars,
  height = 150,
  color = ACCENT,
}: {
  bars: Point[];
  height?: number;
  color?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const peak = Math.max(...bars.map((b) => b.value), 0.01);
  const top = bars.reduce((best, b, i) => (b.value > bars[best].value ? i : best), 0);

  return (
    <div className="relative">
      <div className="flex gap-[2px]" style={{ height }}>
        {bars.map((b, i) => (
          <button
            key={b.label}
            type="button"
            onPointerEnter={() => setHover(i)}
            onPointerLeave={() => setHover(null)}
            className="group flex flex-1 cursor-default flex-col justify-end"
            aria-label={`${b.label}: ${usd(b.value)}`}
          >
            <span
              className="w-full rounded-t transition-opacity"
              style={{
                height: `${Math.max((b.value / peak) * 100, b.value > 0 ? 2 : 0)}%`,
                background: color,
                opacity: hover === null || hover === i ? 1 : 0.45,
              }}
            />
          </button>
        ))}
      </div>

      <div className="mt-2 flex gap-[2px]">
        {bars.map((b, i) => (
          <span
            key={b.label}
            className={`label flex-1 text-center ${hover === i ? "text-bone" : ""}`}
          >
            {b.label}
          </span>
        ))}
      </div>

      {/* One direct label on the peak rather than a number over every bar. */}
      {hover === null && bars[top]?.value > 0 && (
        <p className="tnum mt-2 text-right text-[11px] text-muted">
          peak {usdCompact(bars[top].value)} in {bars[top].label}
        </p>
      )}
      {hover !== null && (
        <p className="tnum mt-2 text-right text-[11px] text-bone">
          {bars[hover].label} · {usd(bars[hover].value)}
        </p>
      )}
    </div>
  );
}

export type Slice = { label: string; value: number; share: number };

/** 100% stacked bar: parts of a whole, compared along one axis rather than by angle. */
export function AllocationBar({ slices }: { slices: Slice[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = slices.slice(0, SERIES.length);
  const rest = slices.slice(SERIES.length);
  const other = rest.reduce((n, s) => n + s.share, 0);

  const segments = [
    ...shown.map((s, i) => ({ ...s, color: SERIES[i] })),
    ...(other > 0
      ? [{ label: "Other", value: rest.reduce((n, s) => n + s.value, 0), share: other, color: OTHER }]
      : []),
  ];

  return (
    <div>
      <div className="flex h-8 gap-[2px] overflow-hidden rounded-lg">
        {segments.map((s, i) => (
          <div
            key={s.label}
            onPointerEnter={() => setHover(i)}
            onPointerLeave={() => setHover(null)}
            title={`${s.label}: ${usd(s.value)} (${s.share}%)`}
            className="h-full transition-opacity first:rounded-l-lg last:rounded-r-lg"
            style={{
              width: `${Math.max(s.share, 1)}%`,
              background: s.color,
              opacity: hover === null || hover === i ? 1 : 0.4,
            }}
          />
        ))}
      </div>

      <ul className="mt-4 flex flex-col gap-2">
        {segments.map((s, i) => (
          <li
            key={s.label}
            onPointerEnter={() => setHover(i)}
            onPointerLeave={() => setHover(null)}
            className="flex items-center gap-2.5 text-[13px]"
          >
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} />
            <span className={`min-w-0 flex-1 truncate ${hover === i ? "text-bone" : ""}`}>
              {s.label}
            </span>
            <span className="tnum text-muted">{usd(s.value)}</span>
            <span className="tnum w-12 text-right">{s.share}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
