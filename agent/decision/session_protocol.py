"""Attach runtime protocol data to call sessions."""

from __future__ import annotations

from core.models import CallSessionState
from knowledge.protocol.loader import load_protocol_for_procedure
from knowledge.protocol.models import PostOpProtocol, ProtocolThresholds, SymptomDefinition


def attach_protocol_to_session(
    session: CallSessionState,
    *,
    uses_general_protocol: bool = False,
) -> PostOpProtocol:
    protocol, protocol_key = load_protocol_for_procedure(
        session.procedure_id,
        uses_general_protocol=uses_general_protocol or session.uses_general_protocol,
    )
    session.protocol_key = protocol_key
    session.protocol_symptoms = [symptom.model_dump(mode="json") for symptom in protocol.symptoms]
    session.protocol_thresholds = protocol.thresholds.model_dump()
    session.protocol_alert_signs = list(protocol.alert_signs)
    return protocol


def protocol_from_session(session: CallSessionState) -> PostOpProtocol:
    symptoms = [SymptomDefinition.model_validate(item) for item in session.protocol_symptoms]
    thresholds = ProtocolThresholds.model_validate(session.protocol_thresholds)
    return PostOpProtocol(
        procedure=session.protocol_key,
        generated_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        symptoms=symptoms,
        thresholds=thresholds,
        alert_signs=list(session.protocol_alert_signs),
    )


def pending_protocol_symptoms(session: CallSessionState) -> list[SymptomDefinition]:
    protocol = protocol_from_session(session)
    return [symptom for symptom in protocol.symptoms if symptom.id not in session.covered_symptoms]


def next_protocol_question(session: CallSessionState) -> str | None:
    pending = pending_protocol_symptoms(session)
    return pending[0].question if pending else None
