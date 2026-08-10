import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

const DISMISSED_KEY = "pwa-install-dismissed";

type InstallPromptEvent = Event & {
  prompt: () => void;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function InstallBanner() {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    if (localStorage.getItem(DISMISSED_KEY)) return;
    const onPrompt = (e: Event) => {
      // Chrome shows its own mini-infobar unless this fires; capturing it lets the
      // app offer install on its own terms instead.
      e.preventDefault();
      // beforeinstallprompt arrives via a raw addEventListener, outside React's own
      // event system, so React schedules the update at normal (macrotask) priority
      // instead of committing it immediately. flushSync forces the same "install is
      // available now" state the browser fired to land on screen right away.
      flushSync(() => setDeferred(e as InstallPromptEvent));
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (!deferred) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISSED_KEY, "1");
    setDeferred(null);
  };

  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-20 z-30 flex items-center justify-between gap-3 rounded-lg border border-line bg-ink/95 px-4 py-3 text-sm backdrop-blur md:bottom-4 md:left-auto md:right-4 md:w-80"
    >
      <span>Install OpenFinance for quicker access.</span>
      <div className="flex shrink-0 gap-2">
        <button
          className="btn-ghost px-2 py-1 text-[13px]"
          onClick={async () => {
            deferred.prompt();
            await deferred.userChoice;
            setDeferred(null);
          }}
        >
          Install
        </button>
        <button className="text-[13px] text-muted" onClick={dismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
