import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ObjectItem } from "../lib/api";
import { describeError } from "../lib/errors";

const QUICK_PUBLIC_TAGS = [
  { tag: "categorie-roman", label: "Roman" },
  { tag: "categorie-science", label: "Science" },
  { tag: "categorie-informatique", label: "Informatique" },
  { tag: "theme-histoire", label: "Histoire" },
  { tag: "theme-intelligence-artificielle", label: "Intelligence artificielle" },
  { tag: "langue-fr", label: "Français" },
  { tag: "langue-en", label: "Anglais" },
];

/** Inline tag editor used in the details drawer. */
export function TagsEditor({
  item,
  csrf,
  onSaved,
  onNotify,
  onFilterTag,
}: {
  item: ObjectItem;
  csrf: string | null;
  onSaved: () => void;
  onNotify: (kind: "ok" | "error", text: string) => void;
  /** Optional: render the saved tags as buttons that apply the files filter. */
  onFilterTag?: (tag: string) => void;
}) {
  const [value, setValue] = useState((item.tags ?? []).join(", "));
  const [error, setError] = useState<string | null>(null);
  const currentTags = value.split(",").map((tag) => tag.trim()).filter(Boolean);

  function toggleQuickTag(tag: string) {
    const next = currentTags.includes(tag)
      ? currentTags.filter((current) => current !== tag)
      : [...currentTags, tag];
    setValue(next.join(", "));
    setError(null);
  }

  useEffect(() => {
    setValue((item.tags ?? []).join(", "));
    setError(null);
  }, [item.id, item.tags]);

  const save = useMutation({
    mutationFn: () => {
      if (!csrf) throw new Error("Session expirée.");
      const tags = value
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      return api.setObjectTags(item.id, tags, csrf);
    },
    onSuccess: () => {
      setError(null);
      onNotify("ok", "Étiquettes enregistrées.");
      onSaved();
    },
    onError: (err) => setError(describeError(err, "Enregistrement impossible.")),
  });

  return (
    <div className="tags-editor">
      <label className="field">
        <span>Étiquettes (séparées par des virgules)</span>
        <input
          type="text"
          value={value}
          placeholder="categorie-roman, theme-histoire, langue-fr"
          aria-describedby="public-tag-help"
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <p id="public-tag-help" className="hint">
        Pour le catalogue public : <code>categorie-roman</code>, <code>theme-histoire</code>,
        <code>langue-fr</code>. Les autres étiquettes restent privées.
      </p>
      <div className="tag-suggestions" role="group" aria-label="Classification publique rapide">
        {QUICK_PUBLIC_TAGS.map(({ tag, label }) => (
          <button
            key={tag}
            type="button"
            className="tag-chip"
            aria-pressed={currentTags.includes(tag)}
            onClick={() => toggleQuickTag(tag)}
          >
            {label}
          </button>
        ))}
      </div>
      {onFilterTag && (item.tags ?? []).length > 0 ? (
        <div className="tag-chips" aria-label="Étiquettes enregistrées">
          {(item.tags ?? []).map((tag) => (
            <button
              key={tag}
              type="button"
              className="tag-chip"
              aria-label={`Filtrer par l'étiquette ${tag}`}
              title={`Filtrer par l'étiquette ${tag}`}
              onClick={() => onFilterTag(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      ) : null}
      <button
        type="button"
        className="btn btn-small"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Enregistrement…" : "Enregistrer les étiquettes"}
      </button>
      {error ? (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
