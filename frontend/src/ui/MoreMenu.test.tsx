import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { MoreMenu, type NavEntry } from "./MoreMenu";

const items: NavEntry[] = [
  { to: "/investments", label: "Investments", short: "Invest", end: false, glyph: "◈" },
  { to: "/budgets", label: "Budgets", short: "Budgets", end: false, glyph: "▥" },
];

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<MoreMenu items={items} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("MoreMenu", () => {
  it("is a native button, closed by default, with aria-expanded reflecting state", () => {
    renderAt("/");
    const trigger = screen.getByRole("button", { name: "More" });
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: /Budgets/ })).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", () => {
    renderAt("/");
    const trigger = screen.getByRole("button", { name: "More" });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("closes when a menu item is followed and the route changes", () => {
    renderAt("/");
    const trigger = screen.getByRole("button", { name: "More" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: /Budgets/ }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
