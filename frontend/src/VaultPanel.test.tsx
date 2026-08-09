import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ChecklistCard, DocumentList, UploadForm } from "./VaultPanel";

vi.mock("./api/client", () => ({ apiFetch: vi.fn(), API_BASE: "" }));
import { apiFetch } from "./api/client";

const originalFetch = globalThis.fetch;

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  globalThis.fetch = originalFetch;
});

describe("DocumentList", () => {
  it("lists uploaded documents by title and kind", async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      {
        id: "d1", kind: "will", title: "My Will", filename: "will.pdf",
        content_type: "application/pdf", size_bytes: 1024, notes: null, created_at: "2026-07-01T00:00:00Z",
      },
    ]);
    render(<DocumentList />, { wrapper });
    await screen.findByText("My Will");
    // Regex /will/i alone is ambiguous here — it matches both the title ("My Will")
    // and the kind label ("will · will.pdf"); pin to the kind label specifically.
    expect(screen.getByText(/will · will\.pdf/i)).toBeInTheDocument();
  });

  it("shows an empty state with nothing uploaded", async () => {
    vi.mocked(apiFetch).mockResolvedValue([]);
    render(<DocumentList />, { wrapper });
    await waitFor(() => expect(screen.getByText(/no documents/i)).toBeInTheDocument());
  });
});

describe("ChecklistCard", () => {
  it("shows every checklist item and its gap detail", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [
        { label: "Will on file", satisfied: false, detail: "No will uploaded to the vault yet." },
        { label: "Beneficiary on every retirement/insurance account", satisfied: true, detail: "All set." },
      ],
      gaps: 1,
    });
    render(<ChecklistCard />, { wrapper });
    await screen.findByText("Will on file");
    expect(screen.getByText("No will uploaded to the vault yet.")).toBeInTheDocument();
  });
});

describe("UploadForm", () => {
  it("submits kind, title, and the file as multipart form data", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "d1" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<UploadForm />, { wrapper });

    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "My Will" } });
    fireEvent.change(screen.getByLabelText("Document type"), { target: { value: "will" } });
    const file = new File(["will contents"], "will.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Upload document"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/documents");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
  });
});
