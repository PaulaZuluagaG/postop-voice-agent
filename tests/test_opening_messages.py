from agent.messages import build_opening_intro, build_postop_day_context, patient_first_name


def test_patient_first_name_uses_first_token() -> None:
    assert patient_first_name("Paula Zuluaga") == "Paula"
    assert patient_first_name("  María José García ") == "María"
    assert patient_first_name("") == "Paciente"


def test_build_postop_day_context_for_excel_timepoints() -> None:
    assert "primer día" in build_postop_day_context(1).lower()
    assert "primeros días" in build_postop_day_context(3).lower()
    assert "una semana" in build_postop_day_context(7).lower()
    assert "dos semanas" in build_postop_day_context(14).lower()


def test_build_opening_intro_uses_first_name_and_stage() -> None:
    intro = build_opening_intro(
        patient_name="Paula Zuluaga",
        has_evidence=True,
        procedure_name="Apendicitis",
        postop_day=1,
    )
    assert "Hola Paula," in intro
    assert "Zuluaga" not in intro
    assert "primer día" in intro.lower()
    assert "guías clínicas" not in intro.lower()

    intro_day_14 = build_opening_intro(
        patient_name="Paula Zuluaga",
        has_evidence=True,
        procedure_name="Apendicitis",
        postop_day=14,
    )
    assert "dos semanas" in intro_day_14.lower()
    assert "guías clínicas" not in intro_day_14.lower()


def test_build_opening_intro_warns_when_no_evidence() -> None:
    intro = build_opening_intro(
        patient_name="Paula",
        has_evidence=False,
        procedure_name="Apendicitis",
        postop_day=3,
    )
    assert "No tengo guías clínicas" in intro
    assert "documentos específicos" in intro
    assert "triaje general" in intro.lower()
