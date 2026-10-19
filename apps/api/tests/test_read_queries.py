"""The read endpoints make a fixed number of queries, however many policies a household has.

Each query is a network round trip to the database (about 200 ms to Supabase
from the demo Mac), so a query per policy, per list, adds up quickly. These
tests count the SQL statements a request sends and check the count does not
grow with the number of policies (no N+1). Against a real Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event

from tests.db import ApiTester, Database


@contextmanager
def counting(database: Database) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001 - SQLAlchemy's event signature
        statements.append(statement)

    engine = database.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _queries(database: Database, api: ApiTester, path: str) -> int:
    with counting(database) as statements:
        response = api.get(path)
    assert response.status_code == 200, response.text
    return len(statements)


def test_read_endpoints_make_the_same_number_of_queries_for_one_policy_or_three(database: Database) -> None:
    one, three = database.create_household(), database.create_household()
    database.create_policy(one)
    for _ in range(3):
        database.create_policy(three)
    api_one, api_three = ApiTester(database, one), ApiTester(database, three)

    for path in ("/policies", "/alerts"):
        assert _queries(database, api_one, path) == _queries(database, api_three, path), path

    # 1 policies+insurer+profile, 1 members, 3 lists. (The household lookup is replaced by the test harness.)
    assert _queries(database, api_three, "/policies") == 5
    assert len(api_three.get("/policies").json()) == 3


def test_a_single_policy_is_read_with_the_same_fixed_queries(database: Database) -> None:
    household = database.create_household()
    policy_id = database.create_policy(household)

    assert _queries(database, ApiTester(database, household), f"/policies/{policy_id}") == 5
