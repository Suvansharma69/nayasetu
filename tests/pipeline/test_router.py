"""Stage 0: the Offence-Date Router. The transition day itself is the case that matters."""
from datetime import date, datetime

import pytest

from src.pipeline.router import route

TODAY = date(2026, 9, 27)


@pytest.mark.parametrize("d, era", [
    ("2024-06-30", "ipc"),          # last day of the IPC
    ("2024-07-01", "bns"),          # the BNS binds from this day, inclusive
    ("2024-08-15", "bns"),          # Section 3 worked example
    ("2023-12-03", "ipc"),
    ("1995-01-01", "ipc"),
    (" 2025-02-11 ", "bns"),
    (date(2024, 6, 30), "ipc"),
    (datetime(2024, 7, 1, 0, 30), "bns"),
])
def test_routes_by_offence_date(d, era):
    assert route(d, today=TODAY) == era


@pytest.mark.parametrize("bad", ["", None, "15/08/2024", "08-15-2024", "2024-13-01", "yesterday", 20240815])
def test_unparseable_dates_are_refused_not_guessed(bad):
    with pytest.raises(ValueError):
        route(bad, today=TODAY)


def test_future_offence_date_is_refused():
    with pytest.raises(ValueError, match="future"):
        route("2026-09-28", today=TODAY)


def test_transition_date_comes_from_env(monkeypatch):
    monkeypatch.setenv("BNS_TRANSITION_DATE", "2024-08-01")
    assert route("2024-07-15", today=TODAY) == "ipc"
    assert route("2024-08-01", today=TODAY) == "bns"
