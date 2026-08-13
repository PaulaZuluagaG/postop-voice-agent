from agent.decision.response_shaping import append_unique_question, is_redundant_speech_suffix


def test_is_redundant_speech_suffix_detects_exact_duplicate() -> None:
    spoken = (
        "De acuerdo, vamos a revisar su temperatura. "
        "¿Cuál ha sido su temperatura corporal máxima registrada hoy?"
    )
    suffix = "¿Cuál ha sido su temperatura corporal máxima registrada hoy?"
    assert is_redundant_speech_suffix(spoken, suffix) is True


def test_append_unique_question_keeps_single_question() -> None:
    question = "¿Cuál ha sido su temperatura corporal máxima registrada hoy?"
    base = f"De acuerdo, vamos a revisar su temperatura. {question}"
    assert append_unique_question(base, question) == base
