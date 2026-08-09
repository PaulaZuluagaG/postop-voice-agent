"""Multi-turn conversation orchestrator."""

from __future__ import annotations

import time
from datetime import date
from uuid import UUID, uuid4

from agent.decision.clinical_axes import pending_axes, update_covered_axes
from agent.decision.disclaimer_policy import should_replace_with_disclaimer
from agent.decision.intake import (
    compute_postop_day,
    detect_procedure_mismatch,
    resolve_surgery_date,
)
from agent.decision.procedure_evidence import has_procedure_specific_evidence
from agent.decision.scoring import (
    apply_cumulative_score,
    resolve_severity,
    score_turn,
    should_force_alert,
)
from agent.decision.turn_enrichment import enrich_llm_output, take_first_question
from agent.llm.groq_client import GroqClient
from agent.messages import (
    ALERT_MESSAGE,
    DEFAULT_OPENING_QUESTION,
    MAX_TURNS_CLOSE_MESSAGE,
    build_no_evidence_message,
    build_opening_intro,
    build_procedure_mismatch_message,
)
from agent.traceability.logger import CallTraceLogger
from core.config import Settings, get_settings
from core.exceptions import SessionError
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
from core.scenarios import scenario_label
from knowledge.retrieval.retriever import ContextualRetriever


class ConversationOrchestrator:
    """Run RAG → LLM → decision pipeline for each patient turn."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retriever: ContextualRetriever | None = None,
        llm: GroqClient | None = None,
        trace_logger: CallTraceLogger | None = None,
        reference_date: date | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._retriever = retriever or ContextualRetriever(self._settings)
        self._llm = llm or GroqClient(self._settings)
        self._trace = trace_logger or CallTraceLogger(self._settings)
        self._reference_date = reference_date
        self._sessions: dict[UUID, CallSessionState] = {}

    def start_call(
        self,
        *,
        procedure_scenario: ProcedureScenario,
        call_id: UUID | None = None,
        patient_name: str = "Paciente",
        patient_id: str | None = None,
        surgery_date: str | None = None,
    ) -> CallSessionState:
        ref = self._reference_date or date.today()
        postop_day = 1
        resolved_surgery_date: str | None = None
        if surgery_date:
            resolved = resolve_surgery_date(surgery_date, reference_date=ref)
            resolved_surgery_date = resolved.isoformat()
            postop_day = compute_postop_day(resolved, reference_date=ref)

        session = CallSessionState(
            call_id=call_id or uuid4(),
            procedure_scenario=procedure_scenario,
            postop_day=postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            surgery_date=resolved_surgery_date,
            opening_message=None,
        )
        self._sessions[session.call_id] = session
        self._trace.log_call_start(
            session.call_id,
            procedure_scenario=procedure_scenario.value,
            postop_day=postop_day,
            patient_name=patient_name,
            patient_id=patient_id,
            procedure_name=scenario_label(procedure_scenario),
            surgery_date=resolved_surgery_date,
        )
        return session

    def begin_triage(self, call_id: UUID) -> str:
        """Run RAG bootstrap and produce the opening message with the first triage question."""
        session = self.get_session(call_id)
        if session.opening_message:
            return session.opening_message

        procedimiento = scenario_label(session.procedure_scenario)
        ejes_pendientes = pending_axes(session.covered_axes)
        bootstrap_message = (
            f"cuidados postoperatorios complicaciones seguimiento "
            f"{procedimiento} día postoperatorio {session.postop_day}"
        )

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            bootstrap_message,
            procedure_scenario=session.procedure_scenario,
            postop_day=session.postop_day,
        )
        has_evidence = has_procedure_specific_evidence(retrieved, session.procedure_scenario)

        llm_start = time.perf_counter()
        llm_output = self._llm.generate_opening(
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            ejes_pendientes=ejes_pendientes,
            has_procedure_evidence=has_evidence,
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
        conversation_context = self._build_conversation_context(session)
        ejes_pendientes = pending_axes(session.covered_axes)
        procedimiento = scenario_label(session.procedure_scenario)
        mismatch = detect_procedure_mismatch(patient_message, session.procedure_scenario)

        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            patient_message,
            procedure_scenario=session.procedure_scenario,
            postop_day=session.postop_day,
            conversation_context=conversation_context,
        )

        llm_start = time.perf_counter()
        llm_output = self._llm.generate_turn(
            patient_message=patient_message,
            patient_name=session.patient_name,
            procedimiento=procedimiento,
            dia_postop=session.postop_day,
            ejes_cubiertos=session.covered_axes,
            ejes_pendientes=ejes_pendientes,
            puntaje_total=session.cumulative_score,
            turno=session.turn_count + 1,
            max_turnos=self._settings.max_turns_per_call,
            conversation_history=conversation_context,
            retrieved_chunks=retrieved,
            reference_date=self._reference_date or date.today(),
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000

        llm_output = enrich_llm_output(
            session,
            patient_message,
            llm_output,
            reference_date=self._reference_date,
        )
        session.covered_axes = update_covered_axes(session.covered_axes, llm_output)

        agent_response = self._compose_response(
            patient_message,
            llm_output,
            mismatch=mismatch,
            registered_scenario=session.procedure_scenario,
        )

        decision_start = time.perf_counter()
        symptoms = llm_output.to_patient_facts()
        turn_score, score_rules = score_turn(symptoms)
        cumulative_score, cumulative_rules = apply_cumulative_score(
            session.cumulative_score,
            turn_score,
            categoria=llm_output.categoria,
            settings=self._settings,
        )
        session.cumulative_score = cumulative_score
        rules = score_rules + cumulative_rules
        severity = resolve_severity(session.cumulative_score, self._settings)
        alert = should_force_alert(
            session.cumulative_score,
            implicit_alert=llm_output.implicit_alert,
            settings=self._settings,
        )

        if alert:
            agent_response = ALERT_MESSAGE
            session.alert_triggered = True
            severity = SeverityLevel.RED
            session.call_closed = True

        session.current_severity = severity
        session.turn_count += 1
        for chunk in retrieved:
            session.sources_used.add(chunk.source_id)
        for source_id in llm_output.fuentes:
            session.sources_used.add(source_id)

        decision_ms = (time.perf_counter() - decision_start) * 1000
        total_ms = (time.perf_counter() - turn_start) * 1000

        turn = TurnRecord(
            turn_number=session.turn_count,
            patient_input=patient_message,
            agent_response=agent_response,
            rag_query=rag_query,
            retrieved_chunks=retrieved,
            llm_output=llm_output,
            symptoms=symptoms,
            turn_score=turn_score,
            cumulative_score=session.cumulative_score,
            rules_applied=rules,
            alert_triggered=alert,
            severity=severity,
            timings=TurnTimings(
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
                decision_ms=decision_ms,
                total_ms=total_ms,
            ),
        )
        session.turns.append(turn)
        self._trace.log_turn(session.call_id, turn)

        if alert:
            self.close_call(session.call_id, reason="alert_triggered")
        elif llm_output.pregunta is None and not alert:
            self.close_call(session.call_id, reason="llm_closure")
        elif session.turn_count >= self._settings.max_turns_per_call:
            self.close_call(session.call_id, reason="max_turns_reached")

        return turn

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
            procedure_scenario=session.procedure_scenario,
            postop_day=session.postop_day,
            final_score=session.cumulative_score,
            severity=session.current_severity,
            alert_triggered=session.alert_triggered,
            sources_used=sorted(session.sources_used),
            turn_count=session.turn_count,
            closed_reason=reason,
            turn_history=session.turns,
        )

    @staticmethod
    def _build_conversation_context(session: CallSessionState) -> str:
        lines: list[str] = []
        if session.opening_message:
            lines.append(f"Agente: {session.opening_message}")
        for turn in session.turns:
            lines.append(f"Paciente: {turn.patient_input}")
            lines.append(f"Agente: {turn.agent_response}")
        return "\n".join(lines)

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

    @staticmethod
    def _compose_opening(
        session: CallSessionState,
        llm_output: LLMTurnOutput,
        has_evidence: bool,
    ) -> str:
        procedimiento = scenario_label(session.procedure_scenario)
        intro = build_opening_intro(
            patient_name=session.patient_name,
            has_evidence=has_evidence,
            procedure_name=procedimiento,
        )
        pregunta = take_first_question(llm_output.pregunta) or DEFAULT_OPENING_QUESTION
        return f"{intro} {pregunta}".strip()
