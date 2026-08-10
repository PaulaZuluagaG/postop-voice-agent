import pytest

from core.scenarios import list_procedure_options_from_disk
from scripts.patient_registration import registration_from_frontend


def test_registration_from_frontend_maps_folder_selection() -> None:
    registration = registration_from_frontend(
        {
            "name": "Paula",
            "patientId": "PAC-001",
            "surgeryDate": "2026-08-05",
            "procedure": "cuello uterino",
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
                "procedure": "Otro",
            }
        )


def test_list_procedure_options_includes_otro_and_disk_folders(tmp_path) -> None:
    (tmp_path / "cuello uterino").mkdir()
    (tmp_path / "Appendicitis").mkdir()

    options = list_procedure_options_from_disk(tmp_path)
    values = [value for value, _label in options]

    assert "cuello uterino" in values
    assert "Appendicitis" in values
    assert "Otro" in values
    assert values.count("Otro") == 1
