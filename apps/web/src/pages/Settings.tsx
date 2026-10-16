import { useState } from "react";
import type { CityTier } from "@/api/types";
import { useHousehold, useUpdateHousehold } from "@/api/endpoints/household";
import { ErrorState, Skeleton } from "@/components/primitives";

const OPTIONS: { value: CityTier | null; label: string; hint: string }[] = [
  { value: "metro", label: "A metro city", hint: "One of India's largest cities." },
  { value: "tier_2", label: "A tier-2 city", hint: "A large city that isn't a metro." },
  { value: "other", label: "Somewhere else", hint: "We have no typical room rate for this, so the room-rent comparison is skipped." },
  { value: null, label: "I'd rather not say", hint: "The room-rent comparison is skipped." },
];

/**
 * D-40: the household chooses its kind of city itself; the app keeps no list
 * of which cities count as metros. Only the room-rent alert reads it.
 */
export function Settings() {
  const household = useHousehold();
  const update = useUpdateHousehold();
  const [error, setError] = useState<string | null>(null);

  if (household.isPending) return <Skeleton className="h-48 w-full max-w-xl" />;
  if (household.isError) {
    return <ErrorState message="We couldn't load your household settings. Check your connection and try again." onRetry={() => household.refetch()} />;
  }

  function choose(value: CityTier | null) {
    setError(null);
    update.mutate({ city_tier: value }, { onError: () => setError("Couldn't save that. Try again.") });
  }

  return (
    <div className="flex max-w-xl flex-col gap-6">
      <header>
        <h1 className="font-serif text-2xl font-semibold text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground">{household.data.name}</p>
      </header>

      <fieldset className="flex flex-col gap-2" disabled={update.isPending}>
        <legend className="font-serif text-lg font-semibold text-foreground">What kind of city do you live in?</legend>
        <p className="text-sm text-muted-foreground">
          Used only to compare your policy's room rent cap with a typical room rate. Those typical rates are estimates that haven't been checked
          against a published source.
        </p>
        {OPTIONS.map((option) => (
          <label key={option.label} className="flex items-start gap-2 rounded border border-rule bg-card px-3 py-2 text-sm">
            <input
              type="radio"
              name="city-tier"
              className="mt-1"
              checked={household.data.city_tier === option.value}
              onChange={() => choose(option.value)}
            />
            <span className="flex flex-col">
              <span className="font-medium text-foreground">{option.label}</span>
              <span className="text-xs text-muted-foreground">{option.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {update.isPending && <p className="text-sm text-muted-foreground">Saving…</p>}
      {error && <p className="text-sm text-flag">{error}</p>}
    </div>
  );
}
