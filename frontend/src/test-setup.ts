import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Auto-cleanup only registers when vitest globals are on; they are not, so renders
// would otherwise pile up in the document and make queries ambiguous.
afterEach(cleanup);

// jsdom ships no ResizeObserver, and charts measure their container before drawing.
// Reporting a fixed width makes them render — and therefore testable — under jsdom.
class TestResizeObserver {
  private callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(_target: Element) {
    this.callback(
      [{ contentRect: { width: 600, height: 160 } } as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
