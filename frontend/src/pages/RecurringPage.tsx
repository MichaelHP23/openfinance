import { AllRecurring, PriceIncreaseCard, RecurringStats, UpcomingCard } from "../recurring";
import { PageHead } from "../ui/Shell";

export function RecurringPage() {
  return (
    <>
      <PageHead title="Recurring" sub="Repeating charges found in your history" />

      <RecurringStats />
      <UpcomingCard />
      <PriceIncreaseCard />
      <AllRecurring />

      <p className="mt-6 text-[13px] leading-relaxed text-muted">
        These series are inferred from your own transactions — same merchant, steady gap, steady
        amount. Nothing here can cancel a subscription or negotiate a bill; the bank feed is
        read-only. Tap a series to see its charges and to rename, dismiss, or mark it cancelled.
      </p>
    </>
  );
}
