"""Shared test doubles for a Neo4j driver Session, so resolver logic can be
unit tested without a live database (requirements §8)."""
import pytest


class FakeResult:
    def __init__(self, rows):
        self._rows = [dict(r) for r in rows]

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Records every `.run()` call and returns canned rows based on a
    simple substring match against the query text, in registration order.
    If a registered response is an Exception instance/class, it is raised
    instead of returned (used to simulate e.g. a missing GDS plugin)."""

    def __init__(self):
        self.calls = []
        self._responses = []

    def when(self, query_substring, rows_or_exception):
        self._responses.append((query_substring, rows_or_exception))

    def run(self, query, **params):
        self.calls.append((query, params))
        for substring, response in self._responses:
            if substring in query:
                if isinstance(response, Exception):
                    raise response
                if isinstance(response, type) and issubclass(response, Exception):
                    raise response("simulated failure")
                return FakeResult(response)
        return FakeResult([])


@pytest.fixture
def fake_session():
    return FakeSession()
