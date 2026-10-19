from datetime import date

import pytest

from app.deadlines import (
    Regime,
    RequestType,
    acknowledgement_due,
    add_business_days,
    add_months,
    extended_deadline,
    initial_deadline,
)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # clamp to shorter month
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # leap year
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 1, 30), 1, date(2026, 2, 28)),
        (date(2026, 2, 28), 1, date(2026, 3, 28)),  # no "end of month stickiness"
        (date(2026, 12, 15), 1, date(2027, 1, 15)),  # year rollover
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 5, 10), 1, date(2026, 6, 10)),
    ],
)
def test_add_months_month_ends(start, months, expected):
    assert add_months(start, months) == expected


def test_business_days_skip_weekends():
    friday = date(2026, 3, 6)
    assert add_business_days(friday, 1) == date(2026, 3, 9)  # Monday
    assert add_business_days(friday, 5) == date(2026, 3, 13)


def test_gdpr_one_month():
    d = initial_deadline(Regime.GDPR, RequestType.DELETION, date(2026, 1, 31))
    assert d.due == date(2026, 2, 28)
    assert d.extendable
    assert "Art. 12(3)" in d.basis


def test_gdpr_extension_two_further_months():
    received = date(2026, 3, 15)
    original = initial_deadline(Regime.GDPR, RequestType.ACCESS, received).due
    assert original == date(2026, 4, 15)
    assert extended_deadline(Regime.GDPR, received, original) == date(2026, 6, 15)


def test_gdpr_extension_month_end_takes_earlier_reading():
    received = date(2026, 1, 31)
    original = initial_deadline(Regime.GDPR, RequestType.ACCESS, received).due  # 28 Feb
    # due + 2 months = 28 Apr; receipt + 3 months = 30 Apr. Conservative: 28 Apr.
    assert extended_deadline(Regime.GDPR, received, original) == date(2026, 4, 28)


def test_gdpr_objection_uses_one_month_too():
    d = initial_deadline(Regime.GDPR, RequestType.OPT_OUT, date(2026, 8, 31))
    assert d.due == date(2026, 9, 30)
    assert d.extendable


@pytest.mark.parametrize("rtype", [RequestType.ACCESS, RequestType.DELETION, RequestType.CORRECTION])
def test_ccpa_45_days_plus_45(rtype):
    received = date(2026, 12, 20)
    d = initial_deadline(Regime.CCPA, rtype, received)
    assert d.due == date(2027, 2, 3)
    assert d.extendable
    assert extended_deadline(Regime.CCPA, received, d.due) == date(2027, 3, 20)


def test_ccpa_opt_out_15_business_days_not_extendable():
    d = initial_deadline(Regime.CCPA, RequestType.OPT_OUT, date(2026, 3, 2))  # Monday
    assert d.due == date(2026, 3, 23)
    assert not d.extendable


def test_acknowledgement_only_for_ccpa_know_delete_correct():
    received = date(2026, 3, 2)
    assert acknowledgement_due(Regime.CCPA, RequestType.DELETION, received) == date(2026, 3, 16)
    assert acknowledgement_due(Regime.CCPA, RequestType.OPT_OUT, received) is None
    assert acknowledgement_due(Regime.GDPR, RequestType.DELETION, received) is None
