import json

from packages.shared.protocol import JobState, TERMINAL_STATES


def test_all_states_are_strings() -> None:
    for state in JobState:
        assert isinstance(state.value, str)
        assert state.value == state.name


def test_terminal_states_are_marked() -> None:
    assert JobState.SUCCEEDED.is_terminal
    assert JobState.FAILED.is_terminal
    assert JobState.TIMED_OUT.is_terminal
    assert JobState.CANCELLED.is_terminal


def test_non_terminal_states_are_not_marked() -> None:
    assert not JobState.PENDING.is_terminal
    assert not JobState.DISPATCHED.is_terminal
    assert not JobState.RUNNING.is_terminal


def test_terminal_set_matches_expected() -> None:
    assert TERMINAL_STATES == {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.TIMED_OUT,
        JobState.CANCELLED,
    }


def test_state_serializes_as_string() -> None:
    assert json.dumps({"state": JobState.PENDING}) == '{"state": "PENDING"}'


def test_state_compares_to_string() -> None:
    assert JobState.PENDING == "PENDING"