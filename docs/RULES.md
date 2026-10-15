# Engine B rules

Generated from `engines/rules/registry.py` by `engines/rules/scripts/generate_rules_doc.py`. Do not edit by hand.

Engine B is a pure function of its inputs: no clock (today's date is passed in), no database, no network, no LLM.
No rule produces a score, probability or percentage. Each check returns a status, a confidence derived from its
inputs, the values it used, a sentence showing the arithmetic, the clause it relied on, and any missing facts.

## Eligibility checks (Feature 2)

| Rule | Title | Critical | Extracted fields read | Facts read | Outcomes |
| --- | --- | --- | --- | --- | --- |
| `coverage_profile` | Policy coverage details | yes | - | `policy has a coverage profile` | satisfied when the policy has been read; unknown while it has not |
| `initial_waiting_period` | Initial waiting period | yes | `waiting_periods[initial].months` | `policy.start_date`<br>`claim.admitted_on` | failed if admitted before start + months; satisfied on or after |
| `ped_waiting_period` | Pre-existing disease waiting period | yes | `waiting_periods[pre_existing].months` | `facts.condition_is_pre_existing`<br>`facts.first_diagnosed_on`<br>`policy.start_date`<br>`claim.admitted_on` | satisfied if not pre-existing or period served; at risk if 'not pre-existing' but diagnosed before the start date; failed if pre-existing and admitted before start + months; unknown if either fact is missing |
| `disease_specific_waiting_period` | Waiting period for specific conditions | yes | `waiting_periods[disease_specific].months` | `facts.matched_waiting_periods`<br>`policy.start_date`<br>`claim.admitted_on` | satisfied if the user chose none, or every chosen period is served; failed if one is not served; unknown if not answered |
| `permanent_exclusions` | Permanent exclusions | yes | `exclusions[i]` | `facts.matched_exclusions` | satisfied if the user chose none; failed if the user chose one; unknown if not answered |
| `room_rent_sub_limit` | Room rent limit | no | `sub_limits[room_rent].cap_amount`<br>`sub_limits[room_rent].percent_value`<br>`sum_insured` | `facts.planned_room_rent_per_day` | satisfied if rent <= cap; at risk if above (proportionate deduction); percent caps in integer paise |
| `claim_intimation` | Telling the insurer in time | no | `intimation_deadline_hours` | `claim.admitted_on`<br>`the 'intimated' event's occurred_at` | satisfied if intimated by admission date + hours (rounded up to whole days); at risk if later; unknown if the deadline was not extracted |
| `sum_insured_adequacy` | Amount within the sum insured | no | `sum_insured` | `claim.claimed_amount` | satisfied if claimed <= sum insured; at risk if above |

### Conventions every check follows

- **Waiting-period end:** start + N calendar months, clamped to the last day of a shorter month (31 Jan + 1 month = 28 Feb). An admission on or after the end date counts as outside the waiting period.
- **Start of the clock:** Counted from the policy start date we hold. If your cover has been renewed without a break, waiting periods usually run from the first policy's start, which could be earlier.
- **Confidence:** the lowest confidence among the check's inputs. An extracted field counts at its own confidence, or `high` if the user confirmed it. Facts the user entered and policy dates count as `high`. One low-confidence, unconfirmed input stops a check being `high`.
- **Money:** integer paise. A cap stated as a share of the sum insured is `sum_insured x round(percent x 100) // 10000`, rounded down.
- **Disease-specific waiting periods and exclusions** apply only when the user selects them from the policy's own list. Nothing is matched by keyword or by an LLM.
- **Unknown** is returned whenever an input is missing, with the missing fact and where to get it. Nothing is guessed.

### Band

```
The overall band: a fixed function of the checks. No score, no weighting.

Applied strictly in this order; the first that matches decides:

  1. insufficient_information   a CRITICAL check is unknown
  2. likely_ineligible          a check failed, with high confidence
  3. at_risk                    a check failed with less than high confidence,
                                or a check is at risk
  4. likely_eligible            otherwise

Why unknown comes before failed: an assessment that is missing a fact which
could change the outcome must say so, rather than show a verdict built on
what it happened to know.

Critical checks are those that decide whether a claim is covered at all
(coverage details, waiting periods, exclusions). A non-critical check that
is unknown (room rent not given, say) is listed with its missing fact but
does not by itself stop "likely eligible".
```

Ombudsman precedent: always an empty list for now, with the note: "Precedent corpus not yet loaded, so no similar Ombudsman cases are shown."

## Gap alerts (Feature 8)

Computed on every read for each of the household's policies; nothing is stored or scheduled. An alert whose input is missing is skipped and the reason is logged.

| Kind | Severity | Reads | Fires when | Skipped when | Uses unverified reference data |
| --- | --- | --- | --- | --- | --- |
| `waiting_period_expiring` | info | `waiting_periods[*].months`<br>`policy.start_date` | a waiting period ends within the next 90 days | no policy start date, or the period is not in whole months | no |
| `renewal_due` | warning | `policy.end_date` | the policy ends within the next 30 days | no policy end date | no |
| `no_maternity_cover` | info | `waiting_periods[maternity]` | no maternity waiting period was found in the policy's extracted terms | the policy has not been read | no |
| `low_sum_insured` | info | `sum_insured`<br>`household member count` | the sum insured is below the reference figure for the household's size | no sum insured extracted | yes |
| `room_rent_below_market` | warning | `sub_limits[room_rent]`<br>`household city` | the room rent cap is well below the typical rate in the household's city | no household city is stored (always, for now) | yes |

Windows: waiting period ending within 90 days; policy ending within 30 days.

## Reference figures (`engines/rules/reference/typical_costs.yaml`)

| Figure | Value | Source | Verified |
| --- | --- | --- | --- |
| Minimum sum insured, household of up to 1 | ₹5,00,000 | Working figure based on common guidance for family floater cover in Indian cities | false |
| Minimum sum insured, household of up to 2 | ₹7,50,000 | Working figure based on common guidance for family floater cover in Indian cities | false |
| Minimum sum insured, household of up to 4 | ₹10,00,000 | Working figure based on common guidance for family floater cover in Indian cities | false |
| Minimum sum insured, larger household | ₹15,00,000 | Working figure based on common guidance for family floater cover in Indian cities | false |
| Typical room rent per day, metro (unused: no city stored) | ₹6,000 | Working figure for private single rooms in Indian hospitals | false |
| Typical room rent per day, tier_2 (unused: no city stored) | ₹3,500 | Working figure for private single rooms in Indian hospitals | false |
