"""Feature 7: grievance letter drafting (D-43 to D-45).

    letter.py      the deterministic parts of the letter: subject, addressee, header, closing, plain text
    evidence.py    the evidence checklist, from the completeness report and the eligibility checks
    llm.py         the two Gemini calls: draft the argument paragraphs, judge each against its clauses
    run_draft.py   the generate_grievance_draft job: retrieving, drafting, verifying
"""
