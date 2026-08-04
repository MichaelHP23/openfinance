import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

export type NavEntry = { to: string; label: string; short: string; end: boolean; glyph: string };

/** The mobile tab bar's fourth slot: three fixed destinations plus this sheet, holding
 * whatever didn't fit. Generic over `items` on purpose — P3 and P5 push one more entry
 * into Shell.tsx's `MORE` array and pass the same array in, without touching this file.
 */
export function MoreMenu({ items }: { items: NavEntry[] }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const triggerRef = useRef<HTMLButtonElement>(null);

  // A tap on a MORE destination navigates; the sheet should not linger open behind it.
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const active = items.some(
    (i) => location.pathname === i.to || (!i.end && location.pathname.startsWith(`${i.to}/`)),
  );

  return (
    <div className="relative flex flex-1">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="More"
        onClick={() => setOpen((v) => !v)}
        className={[
          "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] transition-colors",
          active || open ? "text-acid" : "text-muted",
        ].join(" ")}
      >
        <span aria-hidden className="text-base leading-none">
          ⋯
        </span>
        <span className={active ? "font-medium" : ""}>More</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 bottom-full mb-2 w-48 rounded-lg border border-line bg-ink shadow-lg"
        >
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              role="menuitem"
              className={({ isActive }) =>
                [
                  "flex items-center gap-2 px-4 py-2.5 text-sm transition-colors",
                  isActive ? "text-acid" : "text-muted hover:text-bone",
                ].join(" ")
              }
            >
              <span aria-hidden>{item.glyph}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}
