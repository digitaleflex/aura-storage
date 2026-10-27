import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ObjectItem } from "../lib/api";
import { describeError } from "../lib/errors";

/** Inline tag editor used in the details drawer. */
export function TagsEditor({
  item,
  csrf,
  onSaved,
  onNotify,
}: {
  item: ObjectItem;
  csrf: string | null;
  onSaved: () => void;
  onNotify: (kind: "ok" | "error", text: string) => void;
}) {
  const [value, setValue] = useState((item.tags ?? []).join(", "));
  const [error, setError] = useState<string | null>(null);

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
          placeholder="maths, l1, video"
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => {
            const next = value.trim();
            if (next !== (item.tags ?? []).join(", ")) save.mutate();
          }}
        />
      </label>
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
