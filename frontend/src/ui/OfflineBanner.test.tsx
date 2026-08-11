import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OfflineBanner } from "./OfflineBanner";

let online = true;

beforeEach(() => {
  online = true;
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function goOffline() {
  online = false;
  act(() => window.dispatchEvent(new Event("offline")));
}

function goOnline() {
  online = true;
  act(() => window.dispatchEvent(new Event("online")));
}

test("renders nothing while online", () => {
  render(<OfflineBanner />);
  expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
});

test("shows a banner naming the outage time when the browser goes offline", () => {
  render(<OfflineBanner />);
  goOffline();
  expect(screen.getByText(/offline — showing cached data as of/i)).toBeInTheDocument();
});

test("hides again once back online", () => {
  render(<OfflineBanner />);
  goOffline();
  goOnline();
  expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
});
