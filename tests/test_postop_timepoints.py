import pytest

from agent.decision.intake import POSTOP_TIMEPOINTS, parse_postop_timepoint
from agent.decision.scoring import get_day_factor, resolve_severity, score_turn_from_protocol
from core.models import SeverityLevel
from knowledge.protocol.loader import load_protocol_for_procedure
from knowledge.protocol.models import ProtocolThresholds


def test_postop_timepoints_are_excel_days() -> None:
    assert POSTOP_TIMEPOINTS == (1, 3, 7, 14)


def test_parse_postop_timepoint_accepts_excel_days() -> None:
    assert parse_postop_timepoint(1) == 1
    assert parse_postop_timepoint("14") == 14


def test_parse_postop_timepoint_rejects_other_days() -> None:
    with pytest.raises(ValueError, match="inválido"):
        parse_postop_timepoint(2)


def test_day_factor_matches_excel_timepoints() -> None:
    assert get_day_factor(1) == 0.5
    assert get_day_factor(3) == 1.0
    assert get_day_factor(7) == 1.25
    assert get_day_factor(14) == 1.5


def test_day_14_fever_escalates_to_red() -> None:
    protocol, _ = load_protocol_for_procedure("total-joint-replacement")
    _base, factor, weighted, _rules = score_turn_from_protocol(
        {"fiebre": 38.2},
        protocol,
        postop_day=14,
    )
    assert factor == 1.5
    assert weighted == 15
    assert resolve_severity(weighted, protocol.thresholds) == SeverityLevel.RED


def test_day_14_wound_infection_escalates_to_red() -> None:
    protocol, _ = load_protocol_for_procedure("total-joint-replacement")
    _base, factor, weighted, _rules = score_turn_from_protocol(
        {"infeccion_herida": True},
        protocol,
        postop_day=14,
    )
    assert factor == 1.5
    assert weighted == 15
    assert resolve_severity(weighted, protocol.thresholds) == SeverityLevel.RED


def test_day_14_calf_pain_hits_yellow_band() -> None:
    protocol, _ = load_protocol_for_procedure("total-joint-replacement")
    _base, factor, weighted, _rules = score_turn_from_protocol(
        {"dolor_hinchazon_pantorrilla": True},
        protocol,
        postop_day=14,
    )
    assert factor == 1.5
    assert weighted == 12
    thresholds = ProtocolThresholds(verde=0, amarillo=8, rojo=15)
    assert resolve_severity(weighted, thresholds) == SeverityLevel.YELLOW


def test_day_1_same_fever_stays_below_yellow() -> None:
    protocol, _ = load_protocol_for_procedure("total-joint-replacement")
    _base, factor, weighted, _rules = score_turn_from_protocol(
        {"fiebre": 38.2},
        protocol,
        postop_day=1,
    )
    assert factor == 0.5
    assert weighted == 5
    assert resolve_severity(weighted, protocol.thresholds) == SeverityLevel.GREEN
