import { useState, type FormEvent } from "react";
import type { Policy } from "@/api/types";
import { ApiError } from "@/api/client";
import { useUpdatePolicyDates } from "@/api/endpoints/policies";
import { formatISTDate } from "@/lib/formatDate";

/**
 * D-39: the dates from the policy schedule, entered by the user, because
 * the parser does not read them. Waiting periods count from the first
 * inception date when it is given (cover renewed without a break), else
 * from the start date. These are typed by the user, so they carry no
 * provenance chip: there is no page they were read from.
 */

const FIELDS = [
  { key: "start_date", label: "Current policy start date", hint: "On your policy schedule." },
  { key: "end_date", label: "Current policy end date", hint: "On your policy schedule." },
  {
    key: "first_inception_date",
    label: "Cover first started (first inception)",
    hint: "If this policy has been renewed without a break, the start date of the very first policy. Waiting periods count from it.",
  },
] as const;

type DateKey = (typeof FIELDS)[number]["key"];

export function PolicyDatesForm({ policy }: { policy: Policy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<DateKey, string>>({ start_date: "", end_date: "", first_inception_date: "" });
  const [errors, setErrors] = useState<string[]>([]);
  const update = useUpdatePolicyDates(policy.id);

  function startEditing() {
    setDraft({
      start_date: policy.start_date ?? "",
      end_date: policy.end_date ?? "",
      first_inception_date: policy.first_inception_date ?? "",
    });
    setErrors([]);
    setEditing(true);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrors([]);
    // An empty box clears that date (null), it is never sent as "".
    update.mutate(
      {
        start_date: draft.start_date || null,
        end_date: draft.end_date || null,
        first_inception_date: draft.first_inception_date || null,
      },
      {
        onSuccess: () => setEditing(false),
        onError: (err) =>
          setErrors(
            err instanceof ApiError && err.fieldErrors.length > 0
              ? err.fieldErrors.map((fe) => `${FIELDS.find((f) => f.key === fe.field)?.label ?? fe.field}: ${fe.message}`)
              : [err instanceof Error ? err.message : "Couldn't save. Try again."],
          ),
      },
    );
  }

  if (!editing) {
    const missing = policy.start_date === null && policy.first_inception_date === null;
    return (
      <div className="flex flex-col gap-2">
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {FIELDS.map((field) => {
            const value = policy[field.key];
            return (
              <div key={field.key} className="rounded border border-rule bg-card px-3 py-2">
                <dt className="text-xs text-muted-foreground">{field.label}</dt>
                <dd className="font-tabular text-sm text-foreground">{value ? formatISTDate(value) : <span className="text-muted-foreground">Not stated</span>}</dd>
              </div>
            );
          })}
        </dl>
        {missing && (
          <p className="text-sm text-neutral">
            Without a start date, waiting periods can't be checked and claims on this policy show "insufficient information".
          </p>
        )}
        <p className="text-xs text-muted-foreground">Entered by you, from your policy schedule.</p>
        <button type="button" onClick={startEditing} className="self-start rounded border border-rule px-3 py-1.5 text-sm font-medium hover:bg-secondary">
          Edit dates
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      {FIELDS.map((field) => (
        <label key={field.key} className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">{field.label}</span>
          <input
            type="date"
            value={draft[field.key]}
            onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
            className="w-fit rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
          <span className="text-xs text-muted-foreground">{field.hint} Leave empty if you don't know it.</span>
        </label>
      ))}
      {errors.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm text-flag">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={update.isPending} className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50">
          {update.isPending ? "Saving…" : "Save dates"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="rounded border border-rule px-3 py-1.5 text-sm">
          Cancel
        </button>
      </div>
    </form>
  );
}
