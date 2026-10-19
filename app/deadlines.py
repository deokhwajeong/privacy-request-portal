"""Per-regulation response deadlines and extensions.

All deadlines are computed on calendar dates in UTC and treated as end of day.
Real programs pin a reference timezone per regime (for example the controller's
establishment); this simplification is called out in docs/design-decisions.md.

The clock starts on the date of receipt and keeps running while identity
verification is pending. That is the conservative reading for both regimes
(see the note on each rule below and the open questions in the docs).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum


class Regime(StrEnum):
    GDPR = "gdpr"
    CCPA = "ccpa"


class RequestType(StrEnum):
    ACCESS = "access"
    DELETION = "deletion"
    CORRECTION = "correction"
    OPT_OUT = "opt_out"  # CCPA: opt-out of sale/sharing. GDPR: objection to processing (Art. 21).


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping to the last day of a shorter month.

    This follows Regulation (EEC, Euratom) No 1182/71, Art. 3(2)(c): a period
    expressed in months ends on the same date in the last month, or, if that
    date does not exist, on the last day of that month. So 31 Jan + 1 month is
    28 Feb (29 Feb in a leap year).
    """
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_business_days(d: date, days: int) -> date:
    """Add business days (Mon to Fri). Public holidays are NOT modeled.

    Holiday calendars are jurisdiction specific; production code should take a
    holiday provider. Ignoring holidays makes deadlines earlier, never later.
    """
    current = d
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59))


@dataclass(frozen=True)
class Deadline:
    due: date
    extendable: bool
    basis: str


def initial_deadline(regime: Regime, request_type: RequestType, received: date) -> Deadline:
    if regime is Regime.GDPR:
        # GDPR Art. 12(3): information on action taken "without undue delay and in any
        # event within one month of receipt of the request". Applies to Arts. 15 to 22,
        # so access (15), rectification (16), erasure (17) and objection (21) alike.
        return Deadline(add_months(received, 1), True, "GDPR Art. 12(3): one month from receipt")

    if request_type is RequestType.OPT_OUT:
        # CCPA regulations, 11 CCR 7026(f): comply with a request to opt-out of sale/sharing
        # as soon as feasibly possible, but no later than 15 business days from receipt.
        # The regulations do not provide an extension for opt-outs.
        return Deadline(
            add_business_days(received, 15), False, "11 CCR 7026(f): 15 business days from receipt"
        )

    # Cal. Civ. Code 1798.130(a)(2): respond within 45 days of receiving a verifiable
    # request to know, delete, or correct. 11 CCR 7021(b) states the 45 days begins on
    # the day the request is received, regardless of time needed to verify.
    return Deadline(received + timedelta(days=45), True, "Civ. Code 1798.130(a)(2): 45 days from receipt")


def extended_deadline(regime: Regime, received: date, original_due: date) -> date:
    if regime is Regime.GDPR:
        # GDPR Art. 12(3): "may be extended by two further months where necessary, taking
        # into account the complexity and number of the requests". The requester must be
        # told of the extension and the reasons within the first month.
        #
        # Month-end ambiguity: "original due + 2 months" and "receipt + 3 months" differ
        # when the original due date was clamped (31 Jan -> 28 Feb -> 28 Apr vs 30 Apr).
        # We take the earlier date. Confirm with counsel; see docs/design-decisions.md.
        return min(add_months(original_due, 2), add_months(received, 3))
    # Cal. Civ. Code 1798.130(a)(2): may be extended once by an additional 45 days when
    # reasonably necessary, with notice to the consumer within the first 45-day period.
    return original_due + timedelta(days=45)


def acknowledgement_due(regime: Regime, request_type: RequestType, received: date) -> date | None:
    # 11 CCR 7021(a): confirm receipt of a request to delete, know, or correct within
    # 10 business days. GDPR sets no separate acknowledgement deadline. The portal sends
    # the acknowledgement at intake for every request regardless.
    if regime is Regime.CCPA and request_type is not RequestType.OPT_OUT:
        return add_business_days(received, 10)
    return None
