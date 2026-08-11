"""Multi-turn conversation orchestrator."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from agent.decision.disclaimer_policy import should_replace_with_disclaimer
from agent.decision.intake import (
    compute_postop_day,
    detect_procedure_mismatch,
    resolve_surgery_date,
)
from agent.decision.procedure_evidence import has_procedure_specific_evidence
from agent.decision.protocol_triage import (
    all_symptoms_covered,
    extract_symptom_values,
    pending_symptoms,
    update_covered_symptoms,
)
from agent.decision.scoring import (
    apply_cumulative_score,
    detect_critical_alert,
    resolve_severity,
    score_turn_from_protocol,
    should_force_alert,
)
from agent.decision.session_protocol import (
    attach_protocol_to_session,
    next_protocol_question,
    pending_protocol_symptoms,
    protocol_from_session,
)
from agent.decision.turn_enrichment import enrich_llm_output, take_first_question
from agent.llm.groq_client import GroqClient
from agent.llm.streaming import GroqStreamingClient, drain_output_future
from agent.memory.compact_memory import build_compact_memory
from agent.messages import (
    ALERT_MESSAGE,
    MAX_TURNS_CLOSE_MESSAGE,
    build_no_evidence_message,
    build_opening_intro,
    build_procedure_mismatch_message,
)
from agent.traceability.logger import CallTraceLogger
from core.config import Settings, get_settings
from core.exceptions import LLMCancelledError, SessionError
from core.models import (
    CallSessionState,
    CallSummary,
    LLMTurnOutput,
    ProcedureScenario,
    ResponseCategory,
    SeverityLevel,
    TurnRecord,
    TurnTimings,
)
from core.scenarios import procedure_display_label, scenario_to_procedure_id
from knowledge.retrieval.retriever import ContextualRetriever


@dataclass
class _TurnDecision:
    agent_response: str
    base_score: int
    day_factor: float
    weighted_score: int
    cumulative_score: int
    rules: list[str]
    severity: SeverityLevel
    alert: bool
    symptom_id: str | None


class ConversationOrchestrator:
    """Run RAG → LLM → decision pipeline for each patient turn."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retriever: ContextualRetriever | None = None,
        llm: GroqClient | None = None,
        streaming_llm: GroqStreamingClient | None = None,
        trace_logger: CallTraceLogger | None = None,
        reference_date: date | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._retriever = retriever or ContextualRetriever(self._settings)
        self._llm = llm or GroqClient(self._settings)
        self._streaming_llm = streaming_llm or GroqStreamingClient(
            self._settings,
            groq_client=self._llm,
        )
        self._trace = trace_logger or CallTraceLogger(self._settings)
        self._reference_date = reference_date
        self._sessions: dict[UUID, CallSessionState] = {}

    def start_call(
        self,
        *,
        procedure_scenario: ProcedureScenario,
        procedure_id: str | None = None,
        call_id: UUID | None = None,
        patient_name: str = "Paciente",
        patient_id: str | None = None,
        surgery_date: str | None = None,
        custom_procedure: str | None = None,
        uses_general_protocol: bool = False,
    ) -> CallSessionState:
        ref = self._reference_date or date.today()
        postop_day = 1
        resolved_surgery_date: str | None = None
        if surgery_date:
            resolved = resolve_surgery_date(surgery_date, reference_date=ref)
            resolved_surgery_date = resolved.isoformat()
            postop_day = compute_postop_day(resolved, reference_date=ref)

        resolved_procedure_id = procedure_id or scenario_to_procedure_id(procedure_scenario)
        session = CallSessionState(
            call_id=call_id or uuid4(),
            procedure_id=resolved_procedure_id,
            procedure_scenario=procedure_scenario,
            postop_day=postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            surgery_date=resolved_surgery_date,
            custom_procedure=custom_procedure,
            uses_general_protocol=uses_general_protocol,
            opening_message=None,
        )
        protocol = attach_protocol_to_session(session, uses_general_protocol=uses_general_protocol)
        first_symptom = protocol.symptoms[0] if protocol.symptoms else None
        session.current_focal_symptom = first_symptom.id if first_symptom else None

        self._sessions[session.call_id] = session
        procedure_name = custom_procedure or procedure_display_label(resolved_procedure_id)
        self._trace.log_call_start(
            session.call_id,
            procedure_id=resolved_procedure_id,
            procedure_scenario=procedure_scenario.value,
            postop_day=postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            procedure_name=procedure_name,
            surgery_date=resolved_surgery_date,
            protocol_used=session.protocol_key,
            custom_procedure=custom_procedure,
            uses_general_protocol=uses_general_protocol,
        )
        return session

    def _procedure_label(self, session: CallSessionState) -> str:
        if session.custom_procedure:
            return session.custom_procedure
        return procedure_display_label(session.procedure_id)

    def begin_triage(self, call_id: UUID) -> str:
        """Run RAG bootstrap and produce the opening message with the first triage question."""
        session = self.get_session(call_id)
        if session.opening_message:
            return session.opening_message

        procedimiento = self._procedure_label(session)
        protocol = protocol_from_session(session)
        pending = pending_symptoms(protocol, session.covered_symptoms)
        bootstrap_message = (
            f"cuidados postoperatorios complicaciones seguimiento "
            f"{procedimiento} día postoperatorio {session.postop_day}"
        )

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            bootstrap_message,
            procedure_id=session.procedure_id,
            postop_day=session.postop_day,
        )
        has_evidence = has_procedure_specific_evidence(
            retrieved,
            session.procedure_scenario,
            procedure_id=session.procedure_id,
        )

        llm_start = time.perf_counter()
        llm_output = self._llm.generate_opening(
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            pending_symptoms=pending,
            alert_signs=protocol.alert_signs,
            has_procedure_evidence=has_evidence,
            uses_general_protocol=session.uses_general_protocol,
            retrieved_chunks=retrieved,
            reference_date=self._reference_date or date.today(),
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000

        opening_message = self._compose_opening(session, llm_output, has_evidence)
        session.opening_message = opening_message
        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        self._trace.log_event(
            call_id,
            "triage_opening",
            {
                "opening_message": opening_message,
                "has_procedure_evidence": has_evidence,
                "protocol_used": session.protocol_key,
                "rag_query": rag_query,
                "retrieved_chunk_count": len(retrieved),
                "retrieval_ms": retrieval_ms,
                "llm_ms": llm_ms,
            },
        )
        return opening_message

    def get_session(self, call_id: UUID) -> CallSessionState:
        session = self._sessions.get(call_id)
        if session is None:
            raise SessionError(f"Unknown call_id: {call_id}")
        return session

    def process_turn(self, call_id: UUID, patient_message: str) -> TurnRecord:
        session = self.get_session(call_id)
        if session.call_closed:
            raise SessionError("Call is already closed")

        turn_start = time.perf_counter()
        memory = build_compact_memory(session, self._settings)
        protocol = protocol_from_session(session)
        pending = pending_symptoms(protocol, session.covered_symptoms)
        procedimiento = self._procedure_label(session)
        mismatch = detect_procedure_mismatch(patient_message, session.procedure_scenario)

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            patient_message,
            procedure_id=session.procedure_id,
            postop_day=session.postop_day,
            conversation_context=memory.rag_context,
        )

        llm_start = time.perf_counter()
        llm_output = self._llm.generate_turn(
            patient_message=patient_message,
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            covered_symptom_ids=session.covered_symptoms,
            pending_symptoms=pending,
            alert_signs=protocol.alert_signs,
            puntaje_total=session.cumulative_score,
            turno=session.turn_count + 1,
            max_turnos=self._settings.max_turns_per_call,
            conversation_history=memory.llm_history,
            accumulated_facts=memory.accumulated_facts,
            retrieved_chunks=retrieved,
            reference_date=self._reference_date or date.today(),
            current_focal_symptom=session.current_focal_symptom,
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000

        llm_output = enrich_llm_output(
            session,
            patient_message,
            llm_output,
            reference_date=self._reference_date,
        )
        session.covered_symptoms = update_covered_symptoms(
            session.covered_symptoms,
            llm_output,
            focal_symptom_id=session.current_focal_symptom,
        )

        decision = self._apply_turn_decision(
            session,
            llm_output,
            patient_message=patient_message,
            mismatch=mismatch,
        )

        session.current_severity = decision.severity
        session.turn_count += 1
        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        total_ms = (time.perf_counter() - turn_start) * 1000
        turn = TurnRecord(
            turn_number=session.turn_count,
            patient_input=patient_message,
            agent_response=decision.agent_response,
            rag_query=rag_query,
            retrieved_chunks=retrieved,
            llm_output=llm_output,
            symptoms=llm_output.to_patient_facts(),
            protocol_procedure=session.protocol_key,
            symptom_id=decision.symptom_id,
            base_score=decision.base_score,
            day_factor=decision.day_factor,
            turn_score=decision.weighted_score,
            weighted_score=decision.weighted_score,
            cumulative_score=decision.cumulative_score,
            rules_applied=decision.rules,
            alert_triggered=decision.alert,
            severity=decision.severity,
            timings=TurnTimings(
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                decision_ms=0.0,
                total_ms=total_ms,
            ),
        )
        session.turns.append(turn)
        self._trace.log_turn(session.call_id, turn)
        self._maybe_close_call(session, llm_output, alert=decision.alert)
        return turn

    async def stream_turn_response(
        self,
        call_id: UUID,
        patient_message: str,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Genera tokens hablables en streaming y finaliza el turno al completar."""
        session = self.get_session(call_id)
        if session.call_closed:
            raise SessionError("Call is already closed")

        turn_start = time.perf_counter()
        memory = build_compact_memory(session, self._settings)
        protocol = protocol_from_session(session)
        pending = pending_symptoms(protocol, session.covered_symptoms)
        procedimiento = self._procedure_label(session)
        mismatch = detect_procedure_mismatch(patient_message, session.procedure_scenario)

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            patient_message,
            procedure_id=session.procedure_id,
            postop_day=session.postop_day,
            conversation_context=memory.rag_context,
        )

        llm_start = time.perf_counter()
        stream = self._streaming_llm.stream_turn(
            patient_message=patient_message,
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            covered_symptom_ids=session.covered_symptoms,
            pending_symptoms=pending,
            alert_signs=protocol.alert_signs,
            puntaje_total=session.cumulative_score,
            turno=session.turn_count + 1,
            max_turnos=self._settings.max_turns_per_call,
            conversation_history=memory.llm_history,
            accumulated_facts=memory.accumulated_facts,
            retrieved_chunks=retrieved,
            reference_date=self._reference_date or date.today(),
            current_focal_symptom=session.current_focal_symptom,
            cancel_event=cancel_event,
        )

        streamed_parts: list[str] = []
        async for token in stream.tokens:
            if cancel_event and cancel_event.is_set():
                await drain_output_future(stream.output_future)
                return
            streamed_parts.append(token)
            yield token

        if cancel_event and cancel_event.is_set():
            await drain_output_future(stream.output_future)
            return

        try:
            llm_output = await stream.output_future
        except LLMCancelledError:
            return
        llm_ms = (time.perf_counter() - llm_start) * 1000

        llm_output = enrich_llm_output(
            session,
            patient_message,
            llm_output,
            reference_date=self._reference_date,
        )
        session.covered_symptoms = update_covered_symptoms(
            session.covered_symptoms,
            llm_output,
            focal_symptom_id=session.current_focal_symptom,
        )

        decision = self._apply_turn_decision(
            session,
            llm_output,
            patient_message=patient_message,
            mismatch=mismatch,
        )

        streamed_text = "".join(streamed_parts).strip()
        if not (cancel_event and cancel_event.is_set()):
            if decision.alert and decision.agent_response != streamed_text:
                if streamed_text:
                    yield " "
                yield decision.agent_response
            elif decision.agent_response.startswith(streamed_text):
                suffix = decision.agent_response[len(streamed_text) :].strip()
                if suffix:
                    yield f" {suffix}"
            elif decision.agent_response != streamed_text:
                yield decision.agent_response

        session.current_severity = decision.severity
        session.turn_count += 1
        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        total_ms = (time.perf_counter() - turn_start) * 1000
        turn = TurnRecord(
            turn_number=session.turn_count,
            patient_input=patient_message,
            agent_response=decision.agent_response,
            rag_query=rag_query,
            retrieved_chunks=retrieved,
            llm_output=llm_output,
            symptoms=llm_output.to_patient_facts(),
            protocol_procedure=session.protocol_key,
            symptom_id=decision.symptom_id,
            base_score=decision.base_score,
            day_factor=decision.day_factor,
            turn_score=decision.weighted_score,
            weighted_score=decision.weighted_score,
            cumulative_score=decision.cumulative_score,
            rules_applied=decision.rules,
            alert_triggered=decision.alert,
            severity=decision.severity,
            timings=TurnTimings(
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                decision_ms=0.0,
                total_ms=total_ms,
            ),
        )
        session.turns.append(turn)
        self._trace.log_turn(session.call_id, turn)
        self._maybe_close_call(session, llm_output, alert=decision.alert)

    async def stream_opening_response(
        self,
        call_id: UUID,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[str]:
        """Genera el mensaje de apertura en streaming."""
        session = self.get_session(call_id)
        if session.opening_message:
            yield session.opening_message
            return

        procedimiento = self._procedure_label(session)
        protocol = protocol_from_session(session)
        pending = pending_symptoms(protocol, session.covered_symptoms)
        bootstrap_message = (
            f"cuidados postoperatorios complicaciones seguimiento "
            f"{procedimiento} día postoperatorio {session.postop_day}"
        )

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            bootstrap_message,
            procedure_id=session.procedure_id,
            postop_day=session.postop_day,
        )
        has_evidence = has_procedure_specific_evidence(
            retrieved,
            session.procedure_scenario,
            procedure_id=session.procedure_id,
        )

        llm_start = time.perf_counter()
        stream = self._streaming_llm.stream_opening(
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            pending_symptoms=pending,
            alert_signs=protocol.alert_signs,
            has_procedure_evidence=has_evidence,
            uses_general_protocol=session.uses_general_protocol,
            retrieved_chunks=retrieved,
            reference_date=self._reference_date or date.today(),
            cancel_event=cancel_event,
        )

        streamed_parts: list[str] = []
        async for token in stream.tokens:
            if cancel_event and cancel_event.is_set():
                await drain_output_future(stream.output_future)
                return
            streamed_parts.append(token)
            yield token

        if cancel_event and cancel_event.is_set():
            await drain_output_future(stream.output_future)
            return

        try:
            llm_output = await stream.output_future
        except LLMCancelledError:
            return
        llm_ms = (time.perf_counter() - llm_start) * 1000
        opening_message = self._compose_opening(session, llm_output, has_evidence)
        session.opening_message = opening_message

        streamed_text = "".join(streamed_parts).strip()
        if not (cancel_event and cancel_event.is_set()):
            if opening_message.startswith(streamed_text):
                suffix = opening_message[len(streamed_text) :].strip()
                if suffix:
                    yield f" {suffix}"
            elif opening_message != streamed_text:
                yield opening_message

        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        self._trace.log_event(
            call_id,
            "triage_opening",
            {
                "opening_message": opening_message,
                "has_procedure_evidence": has_evidence,
                "protocol_used": session.protocol_key,
                "rag_query": rag_query,
                "retrieved_chunk_count": len(retrieved),
                "retrieval_ms": retrieval_ms,
                "llm_ms": llm_ms,
            },
        )

    def _apply_turn_decision(
        self,
        session: CallSessionState,
        llm_output: LLMTurnOutput,
        *,
        patient_message: str,
        mismatch: ProcedureScenario | None,
    ) -> _TurnDecision:
        protocol = protocol_from_session(session)
        symptom_values = extract_symptom_values(llm_output)
        base_score, day_factor, weighted_score, score_rules = score_turn_from_protocol(
            symptom_values,
            protocol,
            session.postop_day,
        )
        cumulative_score, cumulative_rules = apply_cumulative_score(
            session.cumulative_score,
            weighted_score,
            categoria=llm_output.categoria,
            thresholds=protocol.thresholds,
        )
        session.cumulative_score = cumulative_score
        rules = score_rules + cumulative_rules
        critical = detect_critical_alert(
            symptom_values,
            protocol,
            implicit_alert=llm_output.implicit_alert,
        )
        severity = resolve_severity(session.cumulative_score, protocol.thresholds)
        alert = should_force_alert(
            session.cumulative_score,
            implicit_alert=llm_output.implicit_alert,
            critical_alert=critical,
            thresholds=protocol.thresholds,
        )

        agent_response = self._compose_response(
            patient_message,
            llm_output,
            mismatch=mismatch,
            registered_scenario=session.procedure_scenario,
        )
        if alert:
            agent_response = ALERT_MESSAGE
            session.alert_triggered = True
            severity = SeverityLevel.RED
            session.call_closed = True

        next_pending = pending_protocol_symptoms(session)
        session.current_focal_symptom = next_pending[0].id if next_pending else None

        return _TurnDecision(
            agent_response=agent_response,
            base_score=base_score,
            day_factor=day_factor,
            weighted_score=weighted_score,
            cumulative_score=session.cumulative_score,
            rules=rules,
            severity=severity,
            alert=alert,
            symptom_id=llm_output.foco_sintoma or session.current_focal_symptom,
        )

    def _maybe_close_call(
        self,
        session: CallSessionState,
        llm_output: LLMTurnOutput,
        *,
        alert: bool,
    ) -> None:
        protocol = protocol_from_session(session)
        if alert:
            self.close_call(session.call_id, reason="alert_triggered")
            return
        if all_symptoms_covered(protocol, session.covered_symptoms):
            self.close_call(session.call_id, reason="protocol_complete")
            return
        if llm_output.pregunta is None:
            self.close_call(session.call_id, reason="llm_closure")
            return
        if session.turn_count >= self._settings.max_turns_per_call:
            self.close_call(session.call_id, reason="max_turns_reached")

    def close_call(self, call_id: UUID, *, reason: str = "manual_close") -> CallSummary:
        session = self.get_session(call_id)
        if session.call_closed and reason != "max_turns_reached":
            return self._build_summary(session, reason)

        if reason == "max_turns_reached" and session.turns:
            last_turn = session.turns[-1]
            if MAX_TURNS_CLOSE_MESSAGE not in last_turn.agent_response:
                last_turn.agent_response = (
                    f"{last_turn.agent_response} {MAX_TURNS_CLOSE_MESSAGE}".strip()
                )

        session.call_closed = True
        summary = self._build_summary(session, reason)
        self._trace.log_call_close(call_id, summary)
        return summary

    def _build_summary(self, session: CallSessionState, reason: str) -> CallSummary:
        return CallSummary(
            call_id=session.call_id,
            procedure_id=session.procedure_id,
            procedure_scenario=session.procedure_scenario,
            custom_procedure=session.custom_procedure,
            protocol_used=session.protocol_key,
            postop_day=session.postop_day,
            final_score=session.cumulative_score,
            severity=session.current_severity,
            alert_triggered=session.alert_triggered,
            physician_escalated=session.alert_triggered,
            sources_used=sorted(session.sources_used),
            turn_count=session.turn_count,
            closed_reason=reason,
            turn_history=session.turns,
        )

    @staticmethod
    def _compose_response(
        patient_message: str,
        llm_output: LLMTurnOutput,
        *,
        mismatch: ProcedureScenario | None = None,
        registered_scenario: ProcedureScenario,
    ) -> str:
        if llm_output.categoria == ResponseCategory.ALERTA_IMPLICITA:
            parts = [llm_output.texto_paciente.strip()]
            if llm_output.pregunta:
                parts.append(llm_output.pregunta.strip())
            return " ".join(parts).strip()

        pregunta = take_first_question(llm_output.pregunta)

        if should_replace_with_disclaimer(patient_message, llm_output):
            base = build_no_evidence_message([], include_redirect_question=not pregunta)
        else:
            base = llm_output.texto_paciente.strip()

        if mismatch is not None:
            notice = build_procedure_mismatch_message(mismatch, registered_scenario)
            base = f"{notice} {base}".strip()

        if pregunta:
            return f"{base} {pregunta}".strip()
        return base

    def _compose_opening(
        self,
        session: CallSessionState,
        llm_output: LLMTurnOutput,
        has_evidence: bool,
    ) -> str:
        procedimiento = self._procedure_label(session)
        intro = build_opening_intro(
            patient_name=session.patient_name,
            has_evidence=has_evidence and not session.uses_general_protocol,
            procedure_name=procedimiento,
        )
        pregunta = take_first_question(llm_output.pregunta) or next_protocol_question(session)
        if pregunta is None:
            pregunta = "¿Cómo se siente en este momento?"
        return f"{intro} {pregunta}".strip()
