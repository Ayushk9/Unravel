import { useState, type FormEvent } from "react";
import type { Claim, ClaimFacts, Policy } from "@/api/types";
import { ApiError } from "@/api/client";
import { useSaveClaimFacts } from "@/api/endpoints/claims";
import { Money } from "@/components/primitives";

/**
 * D-37: what the user tells us about the illness and the stay. The
 * eligibility rules read these; nothing is guessed, so every question has
 * an explicit "not answered yet" (null) as well as its answers.
 *
 * Whether an illness is one of the policy's listed conditions or exclusions
 * is the user's own selection from the policy's list, by position. No
 * keyword matching happens anywhere.
 */

type Tri = "unanswered" | "yes" | "no";
type Selection = "unanswered" | "none" | "some";

function selectionOf(positions: number[] | null): Selection {
  if (positions === null) return "unanswered";
  return positions.length === 0 ? "none" : "some";
}

function positionsFor(selection: Selection, chosen: number[]): number[] | null {
  if (selection === "unanswered") return null;
  return selection === "none" ? [] : chosen;
}

const inputClass = "rounded border border-rule bg-background px-2 py-1.5 text-sm";

export interface ClaimFactsFormProps {
  claim: Claim;
  policy: Policy | null;
}

export function ClaimFactsForm({ claim, policy }: ClaimFactsFormProps) {
  const facts = claim.facts;
  const profile = policy?.coverage_profile ?? null;
  const conditions = (profile?.waiting_periods ?? [])
    .map((period, position) => ({ period, position }))
    .filter(({ period }) => period.kind === "disease_specific");
  const exclusions = (profile?.exclusions ?? []).map((exclusion, position) => ({ exclusion, position }));

  const [diagnosis, setDiagnosis] = useState(facts.diagnosis ?? "");
  const [preExisting, setPreExisting] = useState<Tri>(
    facts.condition_is_pre_existing === null ? "unanswered" : facts.condition_is_pre_existing ? "yes" : "no",
  );
  const [firstDiagnosed, setFirstDiagnosed] = useState(facts.first_diagnosed_on ?? "");
  const [conditionMode, setConditionMode] = useState<Selection>(selectionOf(facts.matched_waiting_periods));
  const [chosenConditions, setChosenConditions] = useState<number[]>(facts.matched_waiting_periods ?? []);
  const [exclusionMode, setExclusionMode] = useState<Selection>(selectionOf(facts.matched_exclusions));
  const [chosenExclusions, setChosenExclusions] = useState<number[]>(facts.matched_exclusions ?? []);
  const [roomRentRupees, setRoomRentRupees] = useState(
    facts.planned_room_rent_per_day === null ? "" : String(facts.planned_room_rent_per_day / 100),
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  const save = useSaveClaimFacts(claim.id);

  function toggle(list: number[], position: number): number[] {
    return list.includes(position) ? list.filter((p) => p !== position) : [...list, position].sort((a, b) => a - b);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErrors([]);
    setSaved(false);

    const problems: string[] = [];
    let roomRent: number | null = null;
    if (roomRentRupees.trim() !== "") {
      const rupees = Number(roomRentRupees);
      if (!Number.isFinite(rupees) || rupees < 0) problems.push("Room rent must be an amount in rupees, 0 or more.");
      else roomRent = Math.round(rupees * 100); // integer paise on the wire
    }
    if (conditionMode === "some" && chosenConditions.length === 0) problems.push("Choose at least one listed condition, or pick another answer.");
    if (exclusionMode === "some" && chosenExclusions.length === 0) problems.push("Choose at least one exclusion, or pick another answer.");
    if (problems.length > 0) {
      setErrors(problems);
      return;
    }

    const body: ClaimFacts = {
      diagnosis: diagnosis.trim() || null,
      condition_is_pre_existing: preExisting === "unanswered" ? null : preExisting === "yes",
      first_diagnosed_on: firstDiagnosed || null,
      matched_waiting_periods: positionsFor(conditionMode, chosenConditions),
      matched_exclusions: positionsFor(exclusionMode, chosenExclusions),
      planned_room_rent_per_day: roomRent,
    };
    save.mutate(body, {
      onSuccess: () => setSaved(true),
      onError: (err) =>
        setErrors(
          err instanceof ApiError && err.fieldErrors.length > 0
            ? err.fieldErrors.map((fe) => `${fe.field}: ${fe.message}`)
            : [err instanceof Error ? err.message : "Couldn't save. Try again."],
        ),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        The checks below use these answers. Leave a question as "Not answered yet" if you don't know; the check that needs it will say so
        rather than guess.
      </p>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Diagnosis (for your reference; no check reads it)</span>
        <input value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} maxLength={200} className={inputClass} />
      </label>

      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="font-medium text-foreground">Did this illness start before your cover began (a pre-existing condition)?</legend>
        <div className="flex flex-wrap gap-4">
          {(["unanswered", "yes", "no"] as const).map((option) => (
            <label key={option} className="flex items-center gap-1.5">
              <input type="radio" name="pre-existing" checked={preExisting === option} onChange={() => setPreExisting(option)} />
              {option === "unanswered" ? "Not answered yet" : option === "yes" ? "Yes" : "No"}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">When was it first diagnosed?</span>
        <input type="date" value={firstDiagnosed} onChange={(e) => setFirstDiagnosed(e.target.value)} className={`${inputClass} w-fit`} />
        <span className="text-xs text-muted-foreground">From the doctor's record or the earliest prescription or test report for it.</span>
      </label>

      <fieldset className="flex flex-col gap-1.5 text-sm">
        <legend className="font-medium text-foreground">Is it one of the conditions your policy lists with its own waiting period?</legend>
        <SelectionChoice name="conditions" value={conditionMode} onChange={setConditionMode} canChoose={conditions.length > 0} />
        {conditions.length === 0 && <span className="text-xs text-muted-foreground">Your policy's extracted terms list no such conditions.</span>}
        {conditionMode === "some" &&
          conditions.map(({ period, position }) => (
            <label key={position} className="ml-5 flex items-center gap-1.5">
              <input type="checkbox" checked={chosenConditions.includes(position)} onChange={() => setChosenConditions((l) => toggle(l, position))} />
              {period.applies_to ?? "Listed condition"} ({period.months.value ?? "?"} months)
            </label>
          ))}
      </fieldset>

      <fieldset className="flex flex-col gap-1.5 text-sm">
        <legend className="font-medium text-foreground">Does this treatment fall under one of your policy's permanent exclusions?</legend>
        <SelectionChoice name="exclusions" value={exclusionMode} onChange={setExclusionMode} canChoose={exclusions.length > 0} />
        {exclusions.length === 0 && <span className="text-xs text-muted-foreground">Your policy's extracted terms list no exclusions.</span>}
        {exclusionMode === "some" &&
          exclusions.map(({ exclusion, position }) => (
            <label key={position} className="ml-5 flex items-start gap-1.5">
              <input
                type="checkbox"
                className="mt-1"
                checked={chosenExclusions.includes(position)}
                onChange={() => setChosenExclusions((l) => toggle(l, position))}
              />
              {exclusion.value ?? "Exclusion not read clearly"}
            </label>
          ))}
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">Room rent per day for the room you will use, in rupees</span>
        <input inputMode="decimal" value={roomRentRupees} onChange={(e) => setRoomRentRupees(e.target.value)} className={`${inputClass} w-40`} />
        <span className="text-xs text-muted-foreground">
          From the hospital's room tariff.
          {facts.planned_room_rent_per_day !== null && (
            <>
              {" "}
              Saved: <Money value={facts.planned_room_rent_per_day} />
            </>
          )}
        </span>
      </label>

      {errors.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm text-flag">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {saved && <p className="text-sm text-stamp">Saved. The checks below have been re-run.</p>}

      <button
        type="submit"
        disabled={save.isPending}
        className="self-start rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {save.isPending ? "Saving…" : "Save answers"}
      </button>
    </form>
  );
}

function SelectionChoice({
  name,
  value,
  onChange,
  canChoose,
}: {
  name: string;
  value: Selection;
  onChange: (value: Selection) => void;
  canChoose: boolean;
}) {
  const options: { value: Selection; label: string }[] = [
    { value: "unanswered", label: "Not answered yet" },
    { value: "none", label: "None of them" },
    ...(canChoose ? [{ value: "some" as const, label: "Yes, choose which" }] : []),
  ];
  return (
    <div className="flex flex-wrap gap-4">
      {options.map((option) => (
        <label key={option.value} className="flex items-center gap-1.5">
          <input type="radio" name={name} checked={value === option.value} onChange={() => onChange(option.value)} />
          {option.label}
        </label>
      ))}
    </div>
  );
}
