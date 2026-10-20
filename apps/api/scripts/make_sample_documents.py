"""Write fictional sample claim documents for the four demo claims, as PDFs.

Run from apps/api (no database, no network, no model):
    ../../.venv/bin/python scripts/make_sample_documents.py

Writes apps/api/sample_documents/<member>/<type>.pdf: a discharge summary, a
final hospital bill, a payment receipt and an insurer denial letter for each
claim in scripts/seed_demo_claims.py, using that claim's own dates, amounts,
hospital and diagnosis. Ishaan's payment receipt is deliberately left out, so
his claim still has a required document missing.

Everything here is FICTIONAL. Every page is stamped "SAMPLE DOCUMENT -
FICTIONAL PATIENT" at the top and the bottom. There are no real registration
numbers, addresses, phone numbers or e-mail addresses. The denial letters come
from a "Sample Insurer" and quote the sample policy number, never a real
insurer's letterhead. Denial letters for claims that the event log does not
show as denied were asked for as briefed (DECISIONS.md, Phase 7 decisions).

scripts/upload_sample_documents.py attaches them through the normal upload flow.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sample_pdf import write_pdf  # noqa: E402
from seed_demo_claims import CLAIMS, DemoClaim  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "sample_documents"
POLICY_NUMBER = "SAMPLE-0001"
DOCTOR = "Dr. A. Sample (fictional)"

TREATMENT = {
    "Acute appendicitis": ("Laparoscopic appendicectomy under general anaesthesia.", "Soft diet for one week. Review in the surgical clinic after 7 days."),
    "Planned knee arthroscopy": ("Arthroscopic knee procedure (right knee) under spinal anaesthesia.", "Physiotherapy as advised. Review in the orthopaedic clinic after 10 days."),
    "Complications of type 2 diabetes": ("Insulin titration, intravenous fluids and management of blood sugar control.", "Continue the prescribed insulin regimen. Review in the diabetes clinic after 2 weeks."),
    "Severe asthma attack": ("Nebulisation, systemic steroids and oxygen support.", "Continue inhalers as prescribed. Review in the chest clinic after 1 week."),
}
DENIAL_REASON = {
    "Vikram": "The hospitalisation records submitted with the claim are incomplete.",
    "Ananya": "The treatment falls under a listed condition with a waiting period that had not been completed on the date of admission.",
    "Lakshmi": "Denied as a pre-existing disease within the waiting period.",
    "Ishaan": "The claim cannot be admitted without the investigation reports and the history of the ailment.",
}
# Shares of the bill, in percent, by line. The last line takes the rounding remainder.
BILL_LINES = (("Room and nursing charges", 22), ("Doctor and consultation fees", 18), ("Operation theatre / procedure charges", 20),
              ("Pharmacy and consumables", 20), ("Laboratory and investigations", 12), ("Other hospital services", 8))


def rupees(paise: int) -> str:
    """Rs with Indian digit grouping, in Latin-1 text (the PDF font has no rupee sign)."""
    whole = str(paise // 100)
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "Rs " + ",".join([*groups, tail]) if groups else f"Rs {tail}"


def day(value: date) -> str:
    return f"{value.day:02d} {value:%b %Y}"


def patient(claim: DemoClaim) -> str:
    return f"{claim.member} Rao"


def hospital_header(claim: DemoClaim, title: str) -> list[str]:
    return [f"{claim.hospital.upper()} (fictional sample)", title, ""]


def discharge_summary(claim: DemoClaim) -> list[str]:
    discharged = claim.discharged_on or claim.admitted_on
    treatment, advice = TREATMENT[claim.facts["diagnosis"]]
    history = (
        f"Known case of {claim.facts['diagnosis'].lower().replace('complications of ', '')}, first diagnosed on {day(claim.facts['first_diagnosed_on'])}."
        if claim.facts.get("condition_is_pre_existing") else "No relevant past history recorded."
    )
    return [
        *hospital_header(claim, "DISCHARGE SUMMARY"),
        f"Patient name: {patient(claim)}",
        f"Date of admission: {day(claim.admitted_on)}",
        f"Date of discharge: {day(discharged)}",
        f"Type of admission: {claim.admission_type.capitalize()}",
        "",
        f"Final diagnosis: {claim.facts['diagnosis']}",
        f"History: {history}",
        f"Treatment given: {treatment}",
        "Condition at discharge: Stable.",
        f"Advice on discharge: {advice}",
        "",
        f"Treating doctor: {DOCTOR}",
    ]


def final_bill(claim: DemoClaim) -> list[str]:
    total = claim.claimed_amount
    amounts = [total * share // 100 for _, share in BILL_LINES[:-1]]
    amounts.append(total - sum(amounts))
    discharged = claim.discharged_on or claim.admitted_on
    return [
        *hospital_header(claim, "FINAL HOSPITAL BILL (ITEMISED)"),
        f"Patient name: {patient(claim)}",
        f"Admitted: {day(claim.admitted_on)}    Discharged: {day(discharged)}",
        f"Bill date: {day(discharged)}",
        "",
        "Particulars                                         Amount",
        *(f"{label:<50}  {rupees(amount)}" for (label, _), amount in zip(BILL_LINES, amounts, strict=True)),
        "",
        f"{'TOTAL':<50}  {rupees(total)}",
    ]


def payment_receipt(claim: DemoClaim) -> list[str]:
    discharged = claim.discharged_on or claim.admitted_on
    return [
        *hospital_header(claim, "PAYMENT RECEIPT"),
        f"Received from: {patient(claim)}",
        f"Date: {day(discharged)}",
        f"Amount received: {rupees(claim.claimed_amount)}",
        "Towards: final hospital bill for the stay from "
        f"{day(claim.admitted_on)} to {day(discharged)}",
        "Mode of payment: UPI (sample)",
        "",
        "Received with thanks. Cashier (fictional)",
    ]


def denial_date(claim: DemoClaim) -> date:
    denied = next((occurred for state, occurred, _ in claim.events if state == "denied"), None)
    if denied is not None:
        return denied.date()
    return (claim.discharged_on or claim.admitted_on) + timedelta(days=14)


def denial_letter(claim: DemoClaim) -> list[str]:
    discharged = claim.discharged_on or claim.admitted_on
    return [
        "SAMPLE INSURER - CLAIMS DEPARTMENT (fictional)",
        "LETTER OF CLAIM DENIAL (REPUDIATION)",
        "",
        f"Date: {day(denial_date(claim))}",
        f"To: {patient(claim)}",
        f"Policy number: {POLICY_NUMBER}",
        f"Insured person: {patient(claim)}",
        f"Hospital: {claim.hospital}",
        f"Period of hospitalisation: {day(claim.admitted_on)} to {day(discharged)}",
        f"Amount claimed: {rupees(claim.claimed_amount)}",
        "",
        "We have examined your claim. We regret that it is not admissible under the policy.",
        f"Reason: {DENIAL_REASON[claim.member]}",
        "",
        "If you disagree with this decision, you may write to the insurer's grievance cell.",
        "",
        "Claims Manager (fictional)",
    ]


DOCUMENTS = {
    "discharge_summary": discharge_summary,
    "final_hospital_bill": final_bill,
    "payment_receipt": payment_receipt,
    "denial_letter": denial_letter,
}
# Left out so the missing-documents list still has something to show.
LEFT_OUT = {("Ishaan", "payment_receipt")}


def main() -> None:
    written = 0
    for claim in CLAIMS:
        folder = OUT_DIR / claim.member.lower()
        folder.mkdir(parents=True, exist_ok=True)
        for name, build in DOCUMENTS.items():
            path = folder / f"{name}.pdf"
            if (claim.member, name) in LEFT_OUT:
                path.unlink(missing_ok=True)
                print(f"  left out  {path.relative_to(OUT_DIR.parent)}")
                continue
            path.write_bytes(write_pdf(build(claim)))
            written += 1
            print(f"  wrote     {path.relative_to(OUT_DIR.parent)}")
    print(f"{written} sample documents written to {OUT_DIR}")


if __name__ == "__main__":
    main()
