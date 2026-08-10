import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { InstallBanner } from "./InstallBanner";

afterEach(() => {
  localStorage.clear();
});

function firePrompt() {
  const event = new Event("beforeinstallprompt") as Event & {
    prompt: () => void;
    userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  };
  event.prompt = vi.fn();
  event.userChoice = Promise.resolve({ outcome: "accepted" });
  window.dispatchEvent(event);
  return event;
}

test("renders nothing until the browser fires beforeinstallprompt", () => {
  render(<InstallBanner />);
  expect(screen.queryByText(/install/i)).not.toBeInTheDocument();
});

test("shows an Install button after the event fires, and calling it invokes prompt()", () => {
  render(<InstallBanner />);
  const event = firePrompt();
  fireEvent.click(screen.getByRole("button", { name: "Install" }));
  expect(event.prompt).toHaveBeenCalled();
});

test("dismissing hides the banner and remembers the choice", () => {
  render(<InstallBanner />);
  firePrompt();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  expect(localStorage.getItem("pwa-install-dismissed")).toBe("1");
});

test("stays hidden on a fresh render if already dismissed", () => {
  localStorage.setItem("pwa-install-dismissed", "1");
  render(<InstallBanner />);
  firePrompt();
  expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
});
