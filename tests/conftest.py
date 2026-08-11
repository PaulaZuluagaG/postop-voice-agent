"""Shared test helpers."""

from __future__ import annotations

from uuid import uuid4

from agent.decision.session_protocol import attach_protocol_to_session
from core.models import CallSessionState, ProcedureScenario
from core.scenarios import scenario_to_procedure_id
from knowledge.protocol.loader import load_general_protocol


def make_session(
    *,
    scenario: ProcedureScenario = ProcedureScenario.APPENDICITIS,
    postop_day: int = 3,
    uses_general_protocol: bool = False,
) -> CallSessionState:
    procedure_id = scenario_to_procedure_id(scenario)
    session = CallSessionState(
        call_id=uuid4(),
        procedure_id=procedure_id,
        procedure_scenario=scenario,
        postop_day=postop_day,
    )
    if uses_general_protocol:
        protocol, key = load_general_protocol(), "general"
        session.protocol_key = key
        session.protocol_symptoms = [s.model_dump(mode="json") for s in protocol.symptoms]
        session.protocol_thresholds = protocol.thresholds.model_dump()
        session.protocol_alert_signs = list(protocol.alert_signs)
        session.uses_general_protocol = True
        first_id = protocol.symptoms[0].id if protocol.symptoms else None
    else:
        protocol = attach_protocol_to_session(session)
        first_id = protocol.symptoms[0].id if protocol.symptoms else None
    session.current_focal_symptom = first_id
    return session
