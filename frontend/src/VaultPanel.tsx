import { useState } from "react";
import type { DocumentKind } from "./vault";
import { documentDownloadUrl, useChecklist, useDeleteDocument, useDocuments, useUploadDocument } from "./vault";
import { Card, Empty } from "./ui/Shell";

const KINDS: DocumentKind[] = ["will", "trust", "insurance", "deed", "title", "statement", "other"];

export function UploadForm() {
  const upload = useUploadDocument();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<DocumentKind>("will");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Upload a document</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return;
          upload.mutate(
            { file, kind, title, notes },
            { onSuccess: () => { setFile(null); setTitle(""); setNotes(""); } },
          );
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <label className="flex flex-col gap-1.5">
          <span className="label">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Document type</span>
          <select aria-label="Document type" value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">File</span>
          {/* No `required`: jsdom's constraint validation checks `.value`, which
              programmatic file selection (fireEvent-set `.files`, as this component's
              own test does) never populates — the JS guard below (`if (!file) return`)
              already enforces the same rule without depending on native validation. */}
          <input
            type="file"
            aria-label="Upload document"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <button className="btn" disabled={upload.isPending || !file}>
          {upload.isPending ? "Uploading…" : "Upload"}
        </button>
        {upload.isError && <span className="text-sm text-clay">{(upload.error as Error).message}</span>}
      </form>
      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        Files are encrypted before they're written to disk. Only decrypted, in memory,
        for the moment you download them.
      </p>
    </Card>
  );
}

export function DocumentList() {
  const { data = [], isLoading } = useDocuments();
  const remove = useDeleteDocument();

  if (isLoading) return <Empty>Loading…</Empty>;
  if (data.length === 0) return <Empty>No documents yet — upload your first one above.</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">Documents</h2>
      <ul className="divide-y divide-line">
        {data.map((d) => (
          <li key={d.id} className="flex items-center gap-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{d.title}</span>
              <span className="label">{d.kind} · {d.filename}</span>
            </span>
            <a href={documentDownloadUrl(d.id)} className="text-[13px] text-acid">
              Download
            </a>
            <button
              onClick={() => remove.mutate(d.id)}
              aria-label={`Delete ${d.title}`}
              className="text-[13px] text-muted transition-colors hover:text-clay"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function ChecklistCard() {
  const { data, isLoading } = useChecklist();
  if (isLoading || !data) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Estate readiness</h2>
        <span className="label">{data.gaps === 0 ? "All set" : `${data.gaps} gap${data.gaps === 1 ? "" : "s"}`}</span>
      </div>
      <ul className="flex flex-col gap-3">
        {data.items.map((item) => (
          <li key={item.label} className="flex items-start gap-3 text-[13px]">
            <span aria-hidden className={item.satisfied ? "text-acid" : "text-clay"}>
              {item.satisfied ? "✓" : "✕"}
            </span>
            <span>
              <span className="block text-bone">{item.label}</span>
              <span className="text-muted">{item.detail}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        This list reports gaps — it doesn't draft a will, a beneficiary form, or a deed.
        Upload the real documents above once you have them.
      </p>
    </Card>
  );
}
