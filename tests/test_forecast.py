"""Numeric tests for the projection math behind `beans forecast`.

The command-level tests only assert that forecast *runs*; these pin the
actual arithmetic of `_project` for known series so a sign error or
off-by-one in the trend extrapolation can't ship green.
"""

from beans.forecast import _project


def test_project_trend_continues_a_linear_series():
    # A perfectly linear history must extrapolate along the same line:
    # slope 100, so the next steps continue 500, 600, 700 (not 650, 750…).
    assert _project([100, 200, 300, 400], "trend", 3) == [500, 600, 700]


def test_project_trend_flat_series_stays_flat():
    assert _project([50, 50, 50], "trend", 2) == [50, 50]


def test_project_trend_decreasing_series():
    # Mirror of the increasing case: slope -100 continues down past zero.
    assert _project([400, 300, 200, 100], "trend", 2) == [0, -100]


def test_project_average_is_the_mean():
    assert _project([10, 20, 30], "average", 2) == [20, 20]
    # round() uses banker's rounding: mean of 10 and 15 is 12.5 -> 12.
    assert _project([10, 15], "average", 1) == [12]


def test_project_short_history_falls_back_to_average():
    # The trend branch needs >= 2 points; a single point degrades to the
    # average (the point itself), repeated for every step.
    assert _project([42], "trend", 3) == [42, 42, 42]


def test_project_empty_history_is_zero():
    assert _project([], "trend", 2) == [0, 0]
    assert _project([], "average", 2) == [0, 0]
