import pytest

from core.scenarios import list_procedure_options_from_disk
from scripts.patient_registration import registration_from_frontend


def test_registration_from_frontend_maps_folder_selection() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-001",
            "surgeryDate": "2026-08-05",
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
                "surgeryDate": "2026-08-05",
                "procedure": "other",
            }
        )


def test_registration_from_frontend_supports_other_with_custom_label() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-002",
            "surgeryDate": "2026-08-05",
            "procedure": "other",
            "customProcedure": "Reparación de hernia",
        }
    )
    assert registration.procedure_id == "other"
    assert registration.custom_procedure == "Reparación de hernia"
    assert registration.uses_general_protocol is True


def test_list_procedure_options_includes_other_and_disk_folders(tmp_path) -> None:
    (tmp_path / "cervical-cancer").mkdir()
    (tmp_path / "appendicitis").mkdir()

    options = list_procedure_options_from_disk(tmp_path)
    values = [value for value, _label in options]

    assert "cervical-cancer" in values
    assert "appendicitis" in values
    assert "other" in values
    assert values.count("other") == 1
