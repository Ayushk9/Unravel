"""Reading and correcting policies through the API, against a real Postgres.

Policies here are written by store_extraction directly (no upload, no child
process), which keeps these tests about the endpoints.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.ids import new_id
from app.db.models import Document
from app.services.policy_writer import store_extraction
from tests import fake_workers
from tests.db import ApiTester, Database, run

ENVELOPE_KEYS = {"code", "message", "field_errors", "request_id", "retryable"}


def _create_policy(db: Database, api: ApiTester) -> SimpleNamespace:
    document_id = new_id()
    storage_path = f"{api.household_id}/{document_id}/policy.pdf"

    async def create() -> UUID:
        await api.storage.save(storage_path, b"%PDF-1.7 body", "application/pdf")
        async with db.session_factory() as session, session.begin():
            document = Document(
                id=document_id,
                household_id=api.household_id,
                file_name="policy.pdf",
                mime_type="application/pdf",
                storage_path=storage_path,
                parse_status="parsed",
            )
            session.add(document)
            await session.flush()
            return await store_extraction(session, document, fake_workers.build_policy_result())

    return SimpleNamespace(policy_id=str(run(create())), document_id=str(document_id))


@pytest.fixture(scope="module")
def shared(database: Database) -> SimpleNamespace:
    """One household with one policy, plus a second household that owns nothing."""
    api = ApiTester(database, database.create_household())
    created = _create_policy(database, api)
    return SimpleNamespace(
        api=api, db=database, stranger=database.create_household(), policy_id=created.policy_id, document_id=created.document_id
    )


def _profile_row(shared: SimpleNamespace):
    return shared.db.execute("SELECT * FROM coverage_profile WHERE policy_id = :p", p=shared.policy_id)[0]


# --- reading ---


def test_get_policy_returns_every_field_as_extracted_with_provenance(shared: SimpleNamespace) -> None:
    response = shared.api.get(f"/policies/{shared.policy_id}")

    assert response.status_code == 200
    policy = response.json()
    assert set(policy) == {
        "id", "insurer", "policy_number", "product_name", "policy_type", "start_date", "end_date",
        "first_inception_date", "insurer_name", "user_entered_fields", "members", "coverage_profile", "source_document_id",
    }
    # Not extracted by Engine A: sent as null, with every key still present (D-05, D-25, D-39).
    keys = ("insurer", "insurer_name", "policy_number", "product_name", "start_date", "end_date", "first_inception_date")
    assert [policy[key] for key in keys] == [None] * 7
    assert policy["user_entered_fields"] == [], "nothing typed by the user yet (D-46)"
    assert policy["policy_type"] == "other"
    assert policy["members"] == []
    assert policy["source_document_id"] == shared.document_id

    profile = policy["coverage_profile"]
    assert profile["policy_id"] == shared.policy_id
    extracted_fields = [
        profile["sum_insured"],
        profile["co_pay_percent"],
        profile["intimation_deadline_hours"],
        *(sub_limit["cap_amount"] for sub_limit in profile["sub_limits"]),
        *(period["months"] for period in profile["waiting_periods"]),
        *profile["exclusions"],
    ]
    assert len(extracted_fields) == 8
    for field in extracted_fields:
        assert set(field) == {"value", "confidence", "provenance", "user_confirmed"}, "Extracted[T] is never flattened"
        assert field["confidence"] in {"high", "medium", "low"}
        if field["provenance"] is not None:
            assert set(field["provenance"]) == {"document_id", "page", "bbox", "snippet"}
            assert field["provenance"]["document_id"] == shared.document_id
            assert all(0 <= coordinate <= 1 for coordinate in field["provenance"]["bbox"])

    assert type(profile["sum_insured"]["value"]) is int
    assert [type(s["cap_amount"]["value"]) for s in profile["sub_limits"]] == [int, int, int]
    assert profile["intimation_deadline_hours"] == {"value": None, "confidence": "low", "provenance": None, "user_confirmed": False}
    assert [s["category"] for s in profile["sub_limits"]] == ["room_rent", "procedure", "procedure"]
    assert profile["waiting_periods"][0]["starts_on"] is None and profile["waiting_periods"][0]["expires_on"] is None


def test_list_policies_is_a_bare_array_of_the_callers_policies(shared: SimpleNamespace) -> None:
    response = shared.api.get("/policies")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list), "CONTRACTS.md row 7: a full array, not a paginated collection"
    assert [policy["id"] for policy in body] == [shared.policy_id]
    assert body[0]["coverage_profile"]["sum_insured"]["confidence"] == "high"


def test_get_document_has_the_stored_document_shape(shared: SimpleNamespace) -> None:
    response = shared.api.get(f"/documents/{shared.document_id}")

    assert response.status_code == 200
    document = response.json()
    assert set(document) == {
        "id", "file_name", "mime_type", "page_count", "uploaded_at", "detected_type",
        "parse_status", "parse_error", "deleted_at", "claim_id",
    }
    assert document["parse_status"] == "parsed" and document["page_count"] == 48
    # Engine A does not classify documents, so the type is unknown rather than guessed.
    assert document["detected_type"] == {"value": None, "confidence": "low", "provenance": None, "user_confirmed": False}
    assert document["deleted_at"] is None and document["claim_id"] is None
    assert document["uploaded_at"].endswith(("Z", "+00:00"))


def test_document_file_returns_a_short_lived_signed_url(shared: SimpleNamespace) -> None:
    response = shared.api.get(f"/documents/{shared.document_id}/file")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"url", "expires_at"}
    assert body["url"].startswith("https://") and "expires_in=300" in body["url"]
    assert shared.document_id in body["url"]


# --- other households see nothing ---


def test_another_households_ids_are_404_everywhere(shared: SimpleNamespace) -> None:
    api = shared.api
    patch_body = {"value": 1, "user_confirmed": True}

    with api.acting_as(shared.stranger):
        responses = {
            "policy": api.get(f"/policies/{shared.policy_id}"),
            "document": api.get(f"/documents/{shared.document_id}"),
            "file": api.get(f"/documents/{shared.document_id}/file"),
            "patch": api.patch(f"/policies/{shared.policy_id}/coverage-profile/fields/sum_insured", json=patch_body),
            "list": api.get("/policies"),
        }

    for name in ("policy", "document", "file", "patch"):
        response = responses[name]
        assert response.status_code == 404, f"{name}: 404, never 403 (D-10)"
        assert set(response.json()["error"]) == ENVELOPE_KEYS
        assert response.json()["error"]["code"] == "not_found"
    assert responses["list"].json() == []
    # And the refused PATCH changed nothing.
    assert _profile_row(shared).sum_insured_original_value == 50_000_000
    assert _profile_row(shared).sum_insured_user_confirmed is False


def test_another_households_job_is_404(api: ApiTester, db: Database) -> None:
    api.hold_jobs()
    job_id = api.upload().json()["job_id"]
    mine = api.get(f"/jobs/{job_id}")

    with api.acting_as(db.create_household()):
        theirs = api.get(f"/jobs/{job_id}")

    assert mine.status_code == 200
    assert theirs.status_code == 404 and theirs.json()["error"]["code"] == "not_found"


def test_unknown_and_malformed_ids_use_the_envelope(shared: SimpleNamespace) -> None:
    missing = shared.api.get(f"/policies/{new_id()}")
    malformed = shared.api.get("/policies/not-a-uuid")
    missing_job = shared.api.get(f"/jobs/{new_id()}")

    assert missing.status_code == 404 and missing_job.status_code == 404
    assert malformed.status_code == 422
    for response in (missing, malformed, missing_job):
        assert set(response.json()["error"]) == ENVELOPE_KEYS


# --- correcting a field ---


def _patch(shared: SimpleNamespace, field_path: str, value, user_confirmed=True):
    return shared.api.patch(
        f"/policies/{shared.policy_id}/coverage-profile/fields/{field_path}",
        json={"value": value, "user_confirmed": user_confirmed},
    )


@pytest.mark.parametrize(
    "field_path",
    [
        "nonsense",
        "sum_insured_original_value",  # a real column, but not correctable
        "sum_insured.value",
        "extraction_completeness",
        "sub_limits.room_rent",
        "sub_limits.room_rent.cap_basis",
        "sub_limits.icu.cap_amount",  # valid category, but this policy has no such row
        "sub_limits.not_a_category.cap_amount",
        "waiting_periods.maternity.months",
        "exclusions.0.text",
        "sub_limits.room_rent.cap_amount.extra",
        "sub_limits.3.cap_amount",  # only positions 0..2 exist
        "sub_limits.-1.cap_amount",
        "sub_limits.1.0.cap_amount",
        "waiting_periods.9.months",
        "sub_limits.0.months",
    ],
)
def test_unknown_field_path_is_422(shared: SimpleNamespace, field_path: str) -> None:
    response = _patch(shared, field_path, 1)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["field_errors"][0]["field"] == "field_path"


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        ("sum_insured", 500000.5),  # fractional paise
        ("sum_insured", "500000"),
        ("sum_insured", True),
        ("sum_insured", None),
        ("sum_insured", -1),
        ("co_pay_percent", 150),
        ("co_pay_percent", "ten"),
        ("waiting_periods.pre_existing.months", -3),
        ("sub_limits.room_rent.cap_amount", 5000.0),
    ],
)
def test_wrong_value_type_is_422_and_changes_nothing(shared: SimpleNamespace, field_path: str, value) -> None:
    response = _patch(shared, field_path, value)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["field_errors"][0]["field"] == "value"


def test_user_confirmed_false_is_422(shared: SimpleNamespace) -> None:
    response = _patch(shared, "co_pay_percent", 5, user_confirmed=False)

    assert response.status_code == 422
    assert response.json()["error"]["field_errors"][0]["field"] == "user_confirmed"


def test_rejected_patches_left_the_row_untouched(shared: SimpleNamespace) -> None:
    """Runs after the 422 cases above within this module's shared policy."""
    sub_limits = shared.db.execute(
        "SELECT cap_amount_value, cap_amount_user_confirmed FROM sub_limit s JOIN coverage_profile c "
        "ON c.id = s.coverage_profile_id WHERE c.policy_id = :p ORDER BY position",
        p=shared.policy_id,
    )

    assert [(s.cap_amount_value, s.cap_amount_user_confirmed) for s in sub_limits] == [
        (500_000, False), (4_000_000, False), (6_000_000, False),
    ]
    assert _profile_row(shared).co_pay_percent_user_confirmed is False


def test_path_matching_two_rows_is_409_not_a_guess(shared: SimpleNamespace) -> None:
    response = _patch(shared, "sub_limits.procedure.cap_amount", 1)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ambiguous_field_path"


def test_patch_sets_value_and_confirmation_but_never_original_or_provenance(shared: SimpleNamespace) -> None:
    before = _profile_row(shared)

    response = _patch(shared, "sum_insured", 75_000_000)

    assert response.status_code == 200
    field = response.json()["coverage_profile"]["sum_insured"]
    assert field["value"] == 75_000_000 and field["user_confirmed"] is True
    assert field["provenance"] == before.sum_insured_provenance, "the response still points at the original source"

    after = _profile_row(shared)
    assert after.sum_insured_value == 75_000_000
    assert after.sum_insured_user_confirmed is True
    assert after.sum_insured_original_value == 50_000_000 == before.sum_insured_original_value
    assert after.sum_insured_provenance == before.sum_insured_provenance
    assert after.sum_insured_confidence == before.sum_insured_confidence

    # A second correction still keeps the parser's value.
    _patch(shared, "sum_insured", 100_000_000)
    again = _profile_row(shared)
    assert (again.sum_insured_value, again.sum_insured_original_value) == (100_000_000, 50_000_000)


def test_confirming_without_changing_keeps_the_value_and_marks_it_confirmed(shared: SimpleNamespace) -> None:
    response = _patch(shared, "co_pay_percent", 10)

    field = response.json()["coverage_profile"]["co_pay_percent"]
    assert response.status_code == 200
    assert field["value"] == 10.0 and field["user_confirmed"] is True
    assert _profile_row(shared).co_pay_percent_original_value == 10.0


def test_nested_paths_correct_the_addressed_row_only(shared: SimpleNamespace) -> None:
    room_rent = _patch(shared, "sub_limits.room_rent.cap_amount", 600_000)
    waiting = _patch(shared, "waiting_periods.pre_existing.months", 24)

    assert room_rent.status_code == 200 and waiting.status_code == 200
    profile = waiting.json()["coverage_profile"]
    assert [(s["category"], s["cap_amount"]["value"], s["cap_amount"]["user_confirmed"]) for s in profile["sub_limits"]] == [
        ("room_rent", 600_000, True),
        ("procedure", 4_000_000, False),
        ("procedure", 6_000_000, False),
    ]
    assert profile["waiting_periods"][0]["months"] == {
        **profile["waiting_periods"][0]["months"], "value": 24.0, "user_confirmed": True,
    }
    originals = shared.db.execute(
        "SELECT cap_amount_original_value FROM sub_limit s JOIN coverage_profile c ON c.id = s.coverage_profile_id "
        "WHERE c.policy_id = :p AND s.category = 'room_rent'",
        p=shared.policy_id,
    )
    assert originals[0].cap_amount_original_value == 500_000


def test_a_field_the_parser_missed_can_be_filled_in_by_the_user(shared: SimpleNamespace) -> None:
    response = _patch(shared, "intimation_deadline_hours", 24)

    field = response.json()["coverage_profile"]["intimation_deadline_hours"]
    assert field == {"value": 24.0, "confidence": "low", "provenance": None, "user_confirmed": True}
    row = _profile_row(shared)
    assert row.intimation_deadline_hours_original_value is None, "the record still shows the parser found nothing"


def test_a_position_addresses_one_row_even_when_categories_repeat(shared: SimpleNamespace) -> None:
    # Positions 1 and 2 are both "procedure" caps: by category that is a 409, by position it is exact (D-41).
    response = _patch(shared, "sub_limits.2.cap_amount", 6_500_000)

    assert response.status_code == 200, response.text
    sub_limits = response.json()["coverage_profile"]["sub_limits"]
    assert [(s["label"], s["cap_amount"]["value"], s["cap_amount"]["user_confirmed"]) for s in sub_limits][1:] == [
        ("Cataract", 4_000_000, False),
        ("Hernia", 6_500_000, True),
    ]
    original = shared.db.execute(
        "SELECT cap_amount_original_value FROM sub_limit s JOIN coverage_profile c ON c.id = s.coverage_profile_id "
        "WHERE c.policy_id = :p ORDER BY position",
        p=shared.policy_id,
    )
    assert original[2].cap_amount_original_value == 6_000_000


def test_a_waiting_period_can_be_addressed_by_position(shared: SimpleNamespace) -> None:
    response = _patch(shared, "waiting_periods.0.months", 30)

    assert response.status_code == 200, response.text
    assert response.json()["coverage_profile"]["waiting_periods"][0]["months"]["value"] == 30.0


def test_the_ambiguous_409_says_to_use_a_position(shared: SimpleNamespace) -> None:
    response = _patch(shared, "sub_limits.procedure.cap_amount", 1)

    assert response.status_code == 409 and "position" in response.json()["error"]["message"]
