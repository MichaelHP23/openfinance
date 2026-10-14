import { useEffect, useState } from "react";

const fmtTime = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

export function OfflineBanner() {
  const [since, setSince] = useState<Date | null>(() => (navigator.onLine ? null : new Date()));

  useEffect(() => {
    const onOffline = () => setSince(new Date());
    const onOnline = () => setSince(null);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  if (!since) return null;

  return (
    <p
      role="status"
      className="mb-4 rounded-lg border border-line bg-clay/10 px-3 py-2 text-[13px] text-clay"
    >
      Offline — showing cached data as of {fmtTime(since)}.
    </p>
  );
}
