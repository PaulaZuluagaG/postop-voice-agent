"""Multi-turn conversation orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from agent.decision.clinical_summary import (
    build_clinical_summary,
    consolidate_symptoms_reported,
    resolve_call_triage,
    resolve_source_labels,
)
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
    is_ambiguous_response,
    pending_symptoms,
    update_covered_symptoms,
)
from agent.decision.response_shaping import (
    append_unique_question,
    is_redundant_speech_suffix,
    soften_patient_echo,
)
from agent.decision.scoring import (
    apply_cumulative_score,
    apply_risk_factor_bonus,
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
    build_no_evidence_message,
    build_opening_intro,
    build_procedure_mismatch_message,
    closure_message_for_severity,
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

logger = logging.getLogger(__name__)


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

    @staticmethod
    def _yield_speech_chunks(text: str) -> list[str]:
        parts = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text.strip()) if part.strip()]
        if not parts:
            return [text]
        chunks: list[str] = []
        for index, part in enumerate(parts):
            suffix = " " if index < len(parts) - 1 else ""
            chunks.append(f"{part}{suffix}")
        return chunks

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
        postop_day: int | None = None,
        surgery_date: str | None = None,
        custom_procedure: str | None = None,
        uses_general_protocol: bool = False,
        patient_comorbidities: list[str] | None = None,
    ) -> CallSessionState:
        ref = self._reference_date or date.today()
        resolved_postop_day = 1
        resolved_surgery_date: str | None = None
        if postop_day is not None:
            resolved_postop_day = postop_day
        elif surgery_date:
            resolved = resolve_surgery_date(surgery_date, reference_date=ref)
            resolved_surgery_date = resolved.isoformat()
            resolved_postop_day = compute_postop_day(resolved, reference_date=ref)

        resolved_procedure_id = procedure_id or scenario_to_procedure_id(procedure_scenario)
        session = CallSessionState(
            call_id=call_id or uuid4(),
            procedure_id=resolved_procedure_id,
            procedure_scenario=procedure_scenario,
            postop_day=resolved_postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            surgery_date=resolved_surgery_date,
            custom_procedure=custom_procedure,
            uses_general_protocol=uses_general_protocol,
            opening_message=None,
            patient_comorbidities=list(patient_comorbidities or ()),
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
            postop_day=resolved_postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            procedure_name=procedure_name,
            surgery_date=resolved_surgery_date,
            protocol_used=session.protocol_key,
            custom_procedure=custom_procedure,
            uses_general_protocol=uses_general_protocol,
            patient_comorbidities=session.patient_comorbidities,
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

        opening_message = self._compose_opening(session, has_evidence)
        session.opening_message = opening_message
        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)

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
                "llm_ms": 0.0,
            },
        )
        return opening_message

    def compose_fallback_opening(self, call_id: UUID) -> str:
        """Build opening from protocol only when RAG or pipeline bootstrap fails."""
        session = self.get_session(call_id)
        if session.opening_message:
            return session.opening_message
        opening_message = self._compose_opening(session, has_evidence=False)
        session.opening_message = opening_message
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
            symptoms=extract_symptom_values(llm_output),
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
        turn = self._apply_close_reason(session, turn, llm_output, alert=decision.alert)
        self._trace.log_turn(session.call_id, turn)
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
        if retrieval_ms >= 500:
            logger.info(
                "RAG turno %s | retrieval_ms=%.0f | procedure=%s",
                session.turn_count + 1,
                retrieval_ms,
                session.procedure_id,
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
        agent_response = decision.agent_response

        session.current_severity = decision.severity
        session.turn_count += 1

        close_reason = self._resolve_close_reason(session, llm_output, alert=decision.alert)
        if close_reason is not None:
            agent_response = self._build_closing_agent_response(
                session,
                patient_message,
                llm_output,
                mismatch=mismatch,
                close_reason=close_reason,
                alert=decision.alert,
                fallback=agent_response,
            )

        if not (cancel_event and cancel_event.is_set()):
            if decision.alert and agent_response != streamed_text:
                if streamed_text:
                    yield " "
                yield agent_response
            elif agent_response.startswith(streamed_text):
                suffix = agent_response[len(streamed_text) :].strip()
                if suffix and not is_redundant_speech_suffix(streamed_text, suffix):
                    yield f" {suffix}"

        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        total_ms = (time.perf_counter() - turn_start) * 1000
        turn = TurnRecord(
            turn_number=session.turn_count,
            patient_input=patient_message,
            agent_response=agent_response,
            rag_query=rag_query,
            retrieved_chunks=retrieved,
            llm_output=llm_output,
            symptoms=extract_symptom_values(llm_output),
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
        if close_reason is not None:
            self.close_call(session.call_id, reason=close_reason)
        self._trace.log_turn(session.call_id, turn)

    async def stream_opening_response(
        self,
        call_id: UUID,
        *,
        cancel_event: asyncio.Event | None = None,
        skip_rag: bool = False,
    ) -> AsyncIterator[str]:
        """Genera el mensaje de apertura en streaming."""
        session = self.get_session(call_id)
        if session.opening_message:
            for chunk in self._yield_speech_chunks(session.opening_message):
                yield chunk
            return

        procedimiento = self._procedure_label(session)
        bootstrap_message = (
            f"cuidados postoperatorios complicaciones seguimiento "
            f"{procedimiento} día postoperatorio {session.postop_day}"
        )

        if skip_rag:
            rag_query = bootstrap_message
            retrieved: list = []
            retrieval_ms = 0.0
            has_evidence = not session.uses_general_protocol
        else:
            rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
                bootstrap_message,
                procedure_id=session.procedure_id,
                postop_day=session.postop_day,
            )
            if cancel_event and cancel_event.is_set():
                return

            has_evidence = has_procedure_specific_evidence(
                retrieved,
                session.procedure_scenario,
                procedure_id=session.procedure_id,
            )

        if cancel_event and cancel_event.is_set():
            return

        opening_message = self._compose_opening(session, has_evidence)
        session.opening_message = opening_message
        for chunk in self._yield_speech_chunks(opening_message):
            yield chunk

        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)

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
                "llm_ms": 0.0,
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
            session,
            patient_message,
            llm_output,
            mismatch=mismatch,
            registered_scenario=session.procedure_scenario,
        )
        if alert:
            agent_response = ALERT_MESSAGE
            session.alert_triggered = True
            severity = SeverityLevel.RED

        next_pending = pending_protocol_symptoms(session)
        if is_ambiguous_response(llm_output):
            session.current_focal_symptom = (
                session.current_focal_symptom
                or llm_output.foco_sintoma
                or (next_pending[0].id if next_pending else None)
            )
        else:
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

    def _resolve_close_reason(
        self,
        session: CallSessionState,
        llm_output: LLMTurnOutput,
        *,
        alert: bool,
    ) -> str | None:
        protocol = protocol_from_session(session)
        if alert:
            return "alert_triggered"
        if all_symptoms_covered(protocol, session.covered_symptoms):
            return "protocol_complete"
        if llm_output.pregunta is None:
            return "llm_closure"
        if session.turn_count >= self._settings.max_turns_per_call:
            return "max_turns_reached"
        return None

    @staticmethod
    def _ensure_closing_goodbye(
        agent_response: str,
        reason: str,
        *,
        severity: SeverityLevel,
    ) -> str:
        if reason == "alert_triggered":
            return agent_response
        closing_message = closure_message_for_severity(severity)
        normalized = agent_response.lower()
        if closing_message.lower() in normalized:
            return agent_response
        if reason != "alert_triggered" and severity == SeverityLevel.GREEN:
            if "gracias por su tiempo" in normalized and "cuídese" in normalized:
                return agent_response
        if severity == SeverityLevel.YELLOW and "vigilancia" in normalized:
            return agent_response
        return f"{agent_response} {closing_message}".strip()

    def _build_closing_agent_response(
        self,
        session: CallSessionState,
        patient_message: str,
        llm_output: LLMTurnOutput,
        *,
        mismatch: ProcedureScenario | None,
        close_reason: str,
        alert: bool,
        fallback: str,
    ) -> str:
        if close_reason == "alert_triggered" or alert:
            return fallback
        closing_body = self._compose_response(
            session,
            patient_message,
            llm_output,
            mismatch=mismatch,
            registered_scenario=session.procedure_scenario,
            include_question=False,
        )
        return self._ensure_closing_goodbye(
            closing_body,
            close_reason,
            severity=session.current_severity,
        )

    def _apply_close_reason(
        self,
        session: CallSessionState,
        turn: TurnRecord,
        llm_output: LLMTurnOutput,
        *,
        alert: bool,
    ) -> TurnRecord:
        close_reason = self._resolve_close_reason(session, llm_output, alert=alert)
        if close_reason is None:
            return turn
        updated_response = self._build_closing_agent_response(
            session,
            turn.patient_input,
            llm_output,
            mismatch=None,
            close_reason=close_reason,
            alert=alert,
            fallback=turn.agent_response,
        )
        if updated_response == turn.agent_response:
            self.close_call(session.call_id, reason=close_reason)
            return turn
        updated_turn = turn.model_copy(update={"agent_response": updated_response})
        session.turns[-1] = updated_turn
        self.close_call(session.call_id, reason=close_reason)
        return updated_turn

    def close_call(self, call_id: UUID, *, reason: str = "manual_close") -> CallSummary:
        session = self.get_session(call_id)
        close_reason = session.last_closed_reason or reason if session.call_close_logged else reason
        summary = self._build_summary(session, close_reason)

        if session.call_close_logged:
            if (
                summary.severity != session.logged_summary_severity
                or summary.alert_triggered != session.logged_summary_alert
            ):
                self._trace.log_call_close(call_id, summary)
                session.logged_summary_severity = summary.severity
                session.logged_summary_alert = summary.alert_triggered
            return summary

        session.call_closed = True
        session.last_closed_reason = reason
        self._trace.log_call_close(call_id, summary)
        session.call_close_logged = True
        session.logged_summary_severity = summary.severity
        session.logged_summary_alert = summary.alert_triggered
        return summary

    def _apply_risk_factor_bonus(self, session: CallSessionState) -> None:
        if session.risk_factor_bonus_applied:
            return

        protocol = protocol_from_session(session)
        bonus, rules = apply_risk_factor_bonus(
            session.patient_comorbidities,
            protocol.risk_factors,
            bonus_per_match=self._settings.risk_factor_score_bonus,
        )
        session.risk_factor_bonus_applied = True
        if bonus <= 0:
            return

        session.cumulative_score += bonus
        session.current_severity = resolve_severity(
            session.cumulative_score,
            protocol.thresholds,
        )
        if session.alert_triggered:
            session.current_severity = SeverityLevel.RED
        self._trace.log_event(
            session.call_id,
            "risk_factor_bonus",
            {
                "bonus": bonus,
                "rules": rules,
                "cumulative_score": session.cumulative_score,
                "severity": session.current_severity.value,
                "patient_comorbidities": session.patient_comorbidities,
            },
        )

    def _build_summary(self, session: CallSessionState, reason: str) -> CallSummary:
        self._apply_risk_factor_bonus(session)
        severity, alert, next_steps, follow_up = resolve_call_triage(
            session,
            closed_reason=reason,
        )
        session.alert_triggered = alert
        session.current_severity = severity
        symptoms_reported = consolidate_symptoms_reported(session)
        summary = CallSummary(
            call_id=session.call_id,
            procedure_id=session.procedure_id,
            procedure_scenario=session.procedure_scenario,
            custom_procedure=session.custom_procedure,
            protocol_used=session.protocol_key,
            postop_day=session.postop_day,
            patient_name=session.patient_name,
            patient_id=session.patient_id,
            final_score=session.cumulative_score,
            severity=severity,
            decision_label=severity.value,
            symptoms_reported=symptoms_reported,
            next_steps=next_steps,
            alert_triggered=alert,
            physician_escalated=alert,
            vigilancia_recomendada=follow_up,
            follow_up_recommended=follow_up,
            sources_used=sorted(session.sources_used),
            turn_count=session.turn_count,
            closed_reason=reason,
            turn_history=session.turns,
        )
        source_labels = resolve_source_labels(summary.sources_used, settings=self._settings)
        return summary.model_copy(
            update={
                "clinical_summary": build_clinical_summary(
                    session,
                    summary,
                    source_labels=source_labels,
                )
            }
        )

    def _compose_response(
        self,
        session: CallSessionState,
        patient_message: str,
        llm_output: LLMTurnOutput,
        *,
        mismatch: ProcedureScenario | None = None,
        registered_scenario: ProcedureScenario,
        include_question: bool = True,
    ) -> str:
        if llm_output.categoria == ResponseCategory.ALERTA_IMPLICITA:
            text = llm_output.texto_paciente.strip()
            if include_question and llm_output.pregunta:
                return append_unique_question(text, take_first_question(llm_output.pregunta))
            return text

        pregunta = take_first_question(llm_output.pregunta) if include_question else None

        if should_replace_with_disclaimer(patient_message, llm_output):
            base = build_no_evidence_message([], include_redirect_question=not pregunta)
        else:
            base = soften_patient_echo(
                patient_message,
                llm_output.texto_paciente.strip(),
                turn_index=session.turn_count,
            )

        if mismatch is not None:
            notice = build_procedure_mismatch_message(mismatch, registered_scenario)
            base = f"{notice} {base}".strip()

        return append_unique_question(base, pregunta)

    def _compose_opening(
        self,
        session: CallSessionState,
        has_evidence: bool,
    ) -> str:
        procedimiento = self._procedure_label(session)
        intro = build_opening_intro(
            patient_name=session.patient_name,
            has_evidence=has_evidence and not session.uses_general_protocol,
            procedure_name=procedimiento,
            postop_day=session.postop_day,
        )
        pregunta = take_first_question(next_protocol_question(session))
        if pregunta is None:
            pregunta = "¿Cómo se siente en este momento?"
        return append_unique_question(intro, pregunta)
