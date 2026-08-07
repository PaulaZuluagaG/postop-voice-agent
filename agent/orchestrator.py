"""Multi-turn conversation orchestrator."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from agent.decision.scoring import resolve_severity, score_turn, should_force_alert
from agent.llm.gemini_client import GeminiClient
from agent.messages import (
    ALERT_MESSAGE,
    MAX_TURNS_CLOSE_MESSAGE,
    build_no_evidence_message,
)
from agent.traceability.logger import CallTraceLogger
from core.config import Settings, get_settings
from core.exceptions import SessionError
from core.models import (
    CallSessionState,
    CallSummary,
    LLMTurnOutput,
    ProcedureScenario,
    SeverityLevel,
    TurnRecord,
    TurnTimings,
)
from knowledge.retrieval.retriever import ContextualRetriever


class ConversationOrchestrator:
    """Run RAG → LLM → decision pipeline for each patient turn."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retriever: ContextualRetriever | None = None,
        llm: GeminiClient | None = None,
        trace_logger: CallTraceLogger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._retriever = retriever or ContextualRetriever(self._settings)
        self._llm = llm or GeminiClient(self._settings)
        self._trace = trace_logger or CallTraceLogger(self._settings)
        self._sessions: dict[UUID, CallSessionState] = {}

    def start_call(
        self,
        *,
        procedure_scenario: ProcedureScenario,
        postop_day: int,
        call_id: UUID | None = None,
    ) -> CallSessionState:
        session = CallSessionState(
            call_id=call_id or uuid4(),
            procedure_scenario=procedure_scenario,
            postop_day=postop_day,
        )
        self._sessions[session.call_id] = session
        self._trace.log_call_start(
            session.call_id,
            procedure_scenario=procedure_scenario.value,
            postop_day=postop_day,
        )
        return session

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

        # 8.1 RAG contextual
        rag_query, retrieved, retrieval_ms = self._retriever.retrieve(
            patient_message,
            procedure_scenario=session.procedure_scenario,
            postop_day=session.postop_day,
            conversation_context=conversation_context,
        )

        # 8.2 LLM structured output
        llm_start = time.perf_counter()
        llm_output = self._llm.generate_turn(
            patient_message=patient_message,
            procedure_scenario=session.procedure_scenario.value,
            postop_day=session.postop_day,
            conversation_history=conversation_context,
            retrieved_chunks=retrieved,
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000

        agent_response = self._compose_response(llm_output, retrieved)

        # 8.3 Decision logic in Python
        decision_start = time.perf_counter()
        turn_score, rules = score_turn(llm_output.extracted_symptoms)
        session.cumulative_score += turn_score
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

        decision_ms = (time.perf_counter() - decision_start) * 1000
        total_ms = (time.perf_counter() - turn_start) * 1000

        turn = TurnRecord(
            turn_number=session.turn_count,
            patient_input=patient_message,
            agent_response=agent_response,
            rag_query=rag_query,
            retrieved_chunks=retrieved,
            symptoms=llm_output.extracted_symptoms,
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
        if not session.turns:
            return ""
        lines: list[str] = []
        for turn in session.turns[-3:]:
            lines.append(f"Paciente: {turn.patient_input}")
            lines.append(f"Agente: {turn.agent_response}")
        return "\n".join(lines)

    @staticmethod
    def _compose_response(
        llm_output: LLMTurnOutput,
        retrieved: list,
    ) -> str:
        if llm_output.no_evidence_topics and not retrieved:
            return build_no_evidence_message(llm_output.no_evidence_topics)
        if llm_output.no_evidence_topics and not llm_output.cited_source_ids:
            disclaimer = build_no_evidence_message(llm_output.no_evidence_topics)
            return f"{disclaimer} {llm_output.patient_message}".strip()
        return llm_output.patient_message.strip()
