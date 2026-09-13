from datetime import date

from src.options_research.events_rules import (
    EVENT_COLUMNS,
    fomc_events,
    fourth_friday,
    rule_events,
    third_friday,
)


def _find(events, type_):
    return [e for e in events if e["type"] == type_]


def test_event_columns():
    assert EVENT_COLUMNS == ["date", "time_et", "type", "tier", "source", "ticker"]


def test_third_and_fourth_friday():
    assert third_friday(2025, 6) == date(2025, 6, 20)
    assert fourth_friday(2023, 6) == date(2023, 6, 23)


def test_opex_moves_to_thursday_on_good_friday_2022():
    events = rule_events(date(2022, 4, 1), date(2022, 4, 30))
    assert [e["date"] for e in _find(events, "opex")] == [date(2022, 4, 14)]


def test_quad_witching_only_in_quarter_months():
    events = rule_events(date(2025, 1, 1), date(2025, 12, 31))
    assert [e["date"].month for e in _find(events, "quad_witching")] == [3, 6, 9, 12]
    assert len(_find(events, "opex")) == 12


def test_vix_expiration_june_2025():
    events = rule_events(date(2025, 6, 1), date(2025, 6, 30))
    assert [e["date"] for e in _find(events, "vix_expiration")] == [date(2025, 6, 18)]


def test_ism_and_conference_board_rules_sep_aug_2025():
    sep = rule_events(date(2025, 9, 1), date(2025, 9, 30))
    assert [e["date"] for e in _find(sep, "ism_manufacturing")] == [date(2025, 9, 2)]
    assert [e["date"] for e in _find(sep, "ism_services")] == [date(2025, 9, 4)]
    assert _find(sep, "ism_manufacturing")[0]["time_et"] == "10:00"
    aug = rule_events(date(2025, 8, 1), date(2025, 8, 31))
    assert [e["date"] for e in _find(aug, "consumer_confidence")] == [date(2025, 8, 26)]


def test_month_and_quarter_end_are_last_sessions():
    events = rule_events(date(2025, 5, 1), date(2025, 6, 30))
    assert [e["date"] for e in _find(events, "month_end")] == [date(2025, 5, 30), date(2025, 6, 30)]
    assert [e["date"] for e in _find(events, "quarter_end")] == [date(2025, 6, 30)]


def test_russell_reconstitution_is_fourth_friday_of_june():
    events = rule_events(date(2023, 1, 1), date(2023, 12, 31))
    assert [e["date"] for e in _find(events, "russell_reconstitution")] == [date(2023, 6, 23)]


def test_fomc_decision_press_and_minutes_june_2025():
    events = fomc_events(date(2025, 6, 1), date(2025, 7, 31))
    decisions = _find(events, "fomc_decision")
    assert [(e["date"], e["time_et"], e["tier"]) for e in decisions] == [
        (date(2025, 6, 18), "14:00", "1"), (date(2025, 7, 30), "14:00", "1")
    ]
    assert [e["date"] for e in _find(events, "fomc_press_conference")] == [date(2025, 6, 18), date(2025, 7, 30)]
    assert [e["date"] for e in _find(events, "fomc_minutes")] == [date(2025, 7, 9)]


def test_fomc_decision_count_over_study_window():
    events = fomc_events(date(2021, 6, 18), date(2026, 9, 11))
    assert len(_find(events, "fomc_decision")) == 41


def test_rule_events_december_2026_vix_lookahead_stays_in_calendar():
    events = rule_events(date(2026, 12, 1), date(2026, 12, 31))
    assert [e["date"] for e in _find(events, "vix_expiration")] == [date(2026, 12, 16)]
