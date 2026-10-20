import { useState, type FormEvent } from "react";
import { UserPen } from "lucide-react";
import type { Policy, PolicyUpdateRequest, PolicyUserEnteredField } from "@/api/types";
import { ApiError } from "@/api/client";
import { useUpdatePolicy } from "@/api/endpoints/policies";
import { formatISTDate } from "@/lib/formatDate";

/**
 * D-39, D-46: what the user copies from their policy schedule, because the
 * parser does not read it: the insurer, product and policy number, and the
 * dates. Waiting periods count from the first inception date when it is given
 * (cover renewed without a break), else from the start date.
 *
 * These are typed by the user, so they carry no provenance chip (there is no
 * page they were read from). Each one the user entered is marked "Entered by
 * you" instead, from `policy.user_entered_fields`.
 */

const TEXT_FIELDS = [
  { key: "insurer_name", label: "Insurer", hint: "The insurance company's name, as on your schedule." },
  { key: "product_name", label: "Product (plan) name", hint: "The plan's name, as on your schedule." },
  { key: "policy_number", label: "Policy number", hint: "As printed on your schedule." },
] as const;

const DATE_FIELDS = [
  { key: "start_date", label: "Current policy start date", hint: "On your policy schedule." },
  { key: "end_date", label: "Current policy end date", hint: "On your policy schedule." },
  {
    key: "first_inception_date",
    label: "Cover first started (first inception)",
    hint: "If this policy has been renewed without a break, the start date of the very first policy. Waiting periods count from it.",
  },
] as const;

const ALL_FIELDS = [...TEXT_FIELDS, ...DATE_FIELDS];
type FieldKey = PolicyUserEnteredField;

function EnteredByYou() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <UserPen className="size-3" aria-hidden="true" />
      Entered by you
    </span>
  );
}

function shownValue(policy: Policy, key: FieldKey): string | null {
  // The insurer box shows the linked reference insurer when there is one, else what the user typed.
  if (key === "insurer_name") return policy.insurer?.name ?? policy.insurer_name;
  const value = policy[key];
  if (value === null) return null;
  return key === "start_date" || key === "end_date" || key === "first_inception_date" ? formatISTDate(value) : value;
}

export function PolicyDetailsForm({ policy }: { policy: Policy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<FieldKey, string>>({
    insurer_name: "",
    product_name: "",
    policy_number: "",
    start_date: "",
    end_date: "",
    first_inception_date: "",
  });
  const [errors, setErrors] = useState<string[]>([]);
  const update = useUpdatePolicy(policy.id);
  const entered = new Set(policy.user_entered_fields);

  function startEditing() {
    setDraft({
      insurer_name: policy.insurer_name ?? "",
      product_name: policy.product_name ?? "",
      policy_number: policy.policy_number ?? "",
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
    // Only what changed is sent, so a value read from elsewhere is never re-saved as the user's own.
    // An emptied box clears that value (null); "" is never sent.
    const body: PolicyUpdateRequest = {};
    for (const field of ALL_FIELDS) {
      const before = field.key === "insurer_name" ? (policy.insurer_name ?? "") : (policy[field.key] ?? "");
      const after = draft[field.key].trim();
      if (after !== before) body[field.key] = after || null;
    }
    if (Object.keys(body).length === 0) {
      setEditing(false);
      return;
    }
    update.mutate(body, {
      onSuccess: () => setEditing(false),
      onError: (err) =>
        setErrors(
          err instanceof ApiError && err.fieldErrors.length > 0
            ? err.fieldErrors.map((fe) => `${ALL_FIELDS.find((f) => f.key === fe.field.split(".").pop())?.label ?? fe.field}: ${fe.message}`)
            : [err instanceof Error ? err.message : "Couldn't save. Try again."],
        ),
    });
  }

  if (!editing) {
    const missingDates = policy.start_date === null && policy.first_inception_date === null;
    return (
      <div className="flex flex-col gap-2">
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {ALL_FIELDS.map((field) => {
            const value = shownValue(policy, field.key);
            return (
              <div key={field.key} className="flex flex-col gap-0.5 rounded border border-rule bg-card px-3 py-2">
                <dt className="text-xs text-muted-foreground">{field.label}</dt>
                <dd className="font-tabular text-sm text-foreground">{value ?? <span className="text-muted-foreground">Not stated</span>}</dd>
                {/* The reference insurer is ours, not the user's entry, so it is not marked. */}
                {entered.has(field.key) && !(field.key === "insurer_name" && policy.insurer) && <EnteredByYou />}
              </div>
            );
          })}
        </dl>
        {missingDates && (
          <p className="text-sm text-neutral">
            Without a start date, waiting periods can't be checked and claims on this policy show "insufficient information".
          </p>
        )}
        <p className="text-xs text-muted-foreground">These details come from your policy schedule, typed in by you; they weren't read from the document.</p>
        <button type="button" onClick={startEditing} className="self-start rounded border border-rule px-3 py-1.5 text-sm font-medium hover:bg-secondary">
          Edit details
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      {TEXT_FIELDS.map((field) => (
        <label key={field.key} className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">{field.label}</span>
          <input
            type="text"
            maxLength={200}
            value={draft[field.key]}
            onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
            className="w-full max-w-md rounded border border-rule bg-background px-2 py-1.5 text-sm"
          />
          <span className="text-xs text-muted-foreground">{field.hint} Leave empty if you don't know it.</span>
        </label>
      ))}
      {DATE_FIELDS.map((field) => (
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
          {update.isPending ? "Saving…" : "Save details"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="rounded border border-rule px-3 py-1.5 text-sm">
          Cancel
        </button>
      </div>
    </form>
  );
}
