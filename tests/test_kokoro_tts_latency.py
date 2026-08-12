import pytest

from scripts.benchmark_kokoro_tts import CLINICAL_SAMPLE, run_benchmark


@pytest.mark.slow
def test_kokoro_sentence_mode_faster_or_equal_ttfb_than_token_style() -> None:
    results = {item.mode: item for item in run_benchmark(text=CLINICAL_SAMPLE)}
    sentence = results["sentence (como Pipecat SENTENCE)"]
    token = results["token (fragmentos por puntuación)"]

    assert sentence.audio_chunks >= 1
    assert sentence.ttfb_ms <= token.total_ms
