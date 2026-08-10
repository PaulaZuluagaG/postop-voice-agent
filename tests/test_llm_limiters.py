"""Tests for separate Groq agent and Gemini batch concurrency limiters."""

from __future__ import annotations

import threading

from core.gemini_limiter import gemini_call_slot
from core.groq_limiter import agent_groq_call_slot


def test_agent_and_gemini_limiters_are_independent() -> None:
    """Agent Groq and batch Gemini calls can run concurrently."""
    agent_started = threading.Event()
    gemini_started = threading.Event()
    agent_can_finish = threading.Event()
    gemini_can_finish = threading.Event()
    overlap_detected = threading.Event()

    def agent_worker() -> None:
        with agent_groq_call_slot():
            agent_started.set()
            gemini_started.wait(timeout=2)
            overlap_detected.set()
            agent_can_finish.set()
            gemini_can_finish.wait(timeout=2)

    def gemini_worker() -> None:
        with gemini_call_slot():
            gemini_started.set()
            agent_started.wait(timeout=2)
            overlap_detected.set()
            gemini_can_finish.set()
            agent_can_finish.wait(timeout=2)

    agent_thread = threading.Thread(target=agent_worker)
    gemini_thread = threading.Thread(target=gemini_worker)
    agent_thread.start()
    gemini_thread.start()
    agent_thread.join(timeout=3)
    gemini_thread.join(timeout=3)

    assert overlap_detected.is_set()
    assert not agent_thread.is_alive()
    assert not gemini_thread.is_alive()
