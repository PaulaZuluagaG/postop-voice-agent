from agent.decision.response_shaping import patient_echo_overlap, soften_patient_echo


def test_soften_patient_echo_replaces_high_overlap() -> None:
    result = soften_patient_echo(
        "he tenido fiebre",
        "Entiendo, ha tenido fiebre desde anoche.",
        turn_index=0,
    )
    assert result == "De acuerdo."
    assert "fiebre" not in result.lower()


def test_soften_patient_echo_keeps_unrelated_acknowledgment() -> None:
    result = soften_patient_echo(
        "he tenido fiebre",
        "Gracias por la información.",
        turn_index=1,
    )
    assert result == "Gracias por la información."


def test_patient_echo_overlap_detects_paraphrase() -> None:
    overlap = patient_echo_overlap(
        "he tenido fiebre",
        "Entiendo, ha tenido fiebre desde anoche.",
    )
    assert overlap >= 0.45
