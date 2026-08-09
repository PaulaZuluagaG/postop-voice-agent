from datetime import date

import pytest

from agent.decision.intake import (
    compute_postop_day,
    map_procedure_to_scenario,
    parse_surgery_date,
    resolve_surgery_date,
    try_resolve_relative_date,
)
from core.models import ProcedureScenario

REF = date(2026, 8, 8)


@pytest.mark.parametrize(
    ("procedure_text", "expected"),
    [
        ("apendicectomía", ProcedureScenario.APPENDICITIS),
        ("Apendicitis aguda", ProcedureScenario.APPENDICITIS),
        ("colecistectomía laparoscópica", ProcedureScenario.CHOLECYSTITIS),
        ("cirugía de vesícula", ProcedureScenario.CHOLECYSTITIS),
        ("cáncer colorrectal", ProcedureScenario.COLORECTAL_CANCER),
        ("colectomía parcial", ProcedureScenario.COLORECTAL_CANCER),
        ("cirugía de cuello uterino", ProcedureScenario.CERVICAL_CANCER),
        ("cáncer cervical", ProcedureScenario.CERVICAL_CANCER),
        ("artroplastia de rodilla", ProcedureScenario.TOTAL_JOINT_REPLACEMENT),
        ("reemplazo total de cadera", ProcedureScenario.TOTAL_JOINT_REPLACEMENT),
        ("hernia umbilical", ProcedureScenario.OTHER),
        ("", ProcedureScenario.OTHER),
    ],
)
def test_map_procedure_to_scenario(procedure_text: str, expected: ProcedureScenario) -> None:
    assert map_procedure_to_scenario(procedure_text) == expected


def test_parse_surgery_date_accepts_iso_date_and_datetime() -> None:
    assert parse_surgery_date("2026-08-01") == date(2026, 8, 1)
    assert parse_surgery_date("2026-08-01T14:30:00") == date(2026, 8, 1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ayer", date(2026, 8, 7)),
        ("Ayer", date(2026, 8, 7)),
        ("antier", date(2026, 8, 6)),
        ("anteayer", date(2026, 8, 6)),
        ("hoy", REF),
        ("hace 3 dias", date(2026, 8, 5)),
        ("hace 1 día", date(2026, 8, 7)),
    ],
)
def test_try_resolve_relative_date(text: str, expected: date) -> None:
    assert try_resolve_relative_date(text, reference_date=REF) == expected


def test_try_resolve_relative_date_returns_none_for_non_dates() -> None:
    assert try_resolve_relative_date("una apendicitis", reference_date=REF) is None


def test_resolve_surgery_date_handles_colloquial_and_iso() -> None:
    assert resolve_surgery_date("ayer", reference_date=REF) == date(2026, 8, 7)
    assert resolve_surgery_date("2026-08-01", reference_date=REF) == date(2026, 8, 1)


def test_compute_postop_day_counts_surgery_day_as_one() -> None:
    assert compute_postop_day("2026-08-01", reference_date=date(2026, 8, 1)) == 1
    assert compute_postop_day("2026-08-01", reference_date=date(2026, 8, 7)) == 7


def test_compute_postop_day_from_ayer_is_two_on_next_day() -> None:
    assert compute_postop_day("ayer", reference_date=REF) == 2


def test_compute_postop_day_clamps_future_surgery_to_day_one() -> None:
    assert compute_postop_day("2026-08-10", reference_date=date(2026, 8, 7)) == 1
