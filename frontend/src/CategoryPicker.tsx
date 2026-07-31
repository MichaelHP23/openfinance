// Named CategoryPicker.tsx, not categories.tsx: Vite's default resolve order picks
// categories.ts over categories.tsx for the bare specifier "./categories", so a same-
// named component file would be unreachable from any importer but itself. See
// categories.ts for the hooks and types this component consumes.
import { useCategories } from "./categories";

export function CategoryPicker({
  value,
  onChange,
  ariaLabel = "Category",
}: {
  value: string | null;
  onChange: (id: string | null) => void;
  ariaLabel?: string;
}) {
  const { data = [] } = useCategories();
  const groups = data.filter((c) => c.parent_id === null);

  return (
    <select
      aria-label={ariaLabel}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="text-[13px]"
    >
      <option value="">Uncategorized</option>
      {groups.map((g) => {
        const leaves = data.filter((c) => c.parent_id === g.id);
        // A group with no leaves is selectable in its own right — "Transfers" may never
        // need splitting, and forcing a leaf under it would be busywork.
        return leaves.length === 0 ? (
          <option key={g.id} value={g.id}>
            {g.name}
          </option>
        ) : (
          <optgroup key={g.id} label={g.name}>
            {leaves.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}
