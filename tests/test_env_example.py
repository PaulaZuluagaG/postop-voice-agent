from pathlib import Path

from core.config import Settings
from core.env_example import (
    SECRET_FIELDS,
    env_var_name,
    field_default,
    format_env_value,
    generate_full_env_example,
    generate_minimal_env_example,
)


def test_minimal_env_example_lists_only_secrets_and_docker_vars() -> None:
    content = generate_minimal_env_example()
    for field_name in SECRET_FIELDS:
        assert env_var_name(field_name) in content
    assert "GEMINI_MODEL=gemini-3.6-flash" not in content
    assert "NEXT_PUBLIC_VOICE_API_URL=" in content
    assert "src/core/config.py" in content


def test_full_env_example_matches_settings_defaults() -> None:
    content = generate_full_env_example()
    for field_name, _field in Settings.model_fields.items():
        if field_name in SECRET_FIELDS:
            continue
        expected = format_env_value(field_default(field_name))
        assert f"{env_var_name(field_name)}={expected}" in content


def test_write_env_example_defaults_to_full_template(tmp_path: Path) -> None:
    from core.env_example import write_env_example

    target = tmp_path / ".env.example"
    write_env_example(target)
    content = target.read_text(encoding="utf-8")
    assert "GEMINI_MODEL=gemini-3.6-flash" in content
    assert "GROQ_API_KEY=your_groq_api_key_here" in content


def test_write_env_example_minimal(tmp_path: Path) -> None:
    from core.env_example import write_env_example

    target = tmp_path / ".env.example"
    write_env_example(target, minimal=True)
    content = target.read_text(encoding="utf-8")
    assert "GEMINI_MODEL=gemini-3.6-flash" not in content
    assert "GROQ_API_KEY=your_groq_api_key_here" in content
