import pytest

from core.registration import registration_from_frontend
from core.scenarios import list_procedure_options_from_disk


def test_registration_from_frontend_parses_comorbidities() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-003",
            "postopDay": 3,
            "procedure": "appendicitis",
            "comorbidities": ["diabetes_tipo_2", "obesidad"],
        }
    )
    assert registration.patient_comorbidities == ["diabetes_tipo_2", "obesidad"]
    assert registration.postop_day == 3


def test_registration_from_frontend_maps_folder_selection() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-001",
            "postopDay": 1,
            "procedure": "cervical-cancer",
        }
    )
    assert registration.patient_name == "Paula"
    assert registration.procedure_label == "Cáncer de cuello uterino"


def test_registration_from_frontend_requires_all_fields() -> None:
    with pytest.raises(ValueError, match="incompletos"):
        registration_from_frontend(
            {
                "name": "Paula",
                "patientId": "",
                "postopDay": 1,
                "procedure": "other",
            }
        )


def test_registration_from_frontend_supports_other_with_custom_label() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-002",
            "postopDay": 14,
            "procedure": "other",
            "customProcedure": "Reparación de hernia",
        }
    )
    assert registration.procedure_id == "other"
    assert registration.custom_procedure == "Reparación de hernia"
    assert registration.uses_general_protocol is True
    assert registration.postop_day == 14


def test_list_procedure_options_includes_other_and_disk_folders(tmp_path) -> None:
    cervical = tmp_path / "cervical-cancer"
    cervical.mkdir()
    (cervical / "guide.pdf").write_bytes(b"%PDF")
    appendicitis = tmp_path / "appendicitis"
    appendicitis.mkdir()
    (appendicitis / "guide.pdf").write_bytes(b"%PDF")

    options = list_procedure_options_from_disk(tmp_path)
    values = [value for value, _label in options]
    labels = {value: label for value, label in options}

    assert "cervical-cancer" in values
    assert "appendicitis" in values
    assert "other" in values
    assert values.count("other") == 1
    assert labels["appendicitis"] == "Apendicitis"


def test_list_procedure_options_uses_custom_spanish_label(tmp_path) -> None:
    from core.procedure_labels import save_procedure_label

    folder = tmp_path / "my-procedure"
    folder.mkdir()
    (folder / "guide.pdf").write_bytes(b"%PDF")
    save_procedure_label(tmp_path, "my-procedure", "Mi procedimiento")

    options = list_procedure_options_from_disk(tmp_path)
    labels = {value: label for value, label in options}
    assert labels["my-procedure"] == "Mi procedimiento"
