"""Precarga pesos de Kokoro (modelo + voz en español) para Docker."""

from __future__ import annotations

import os

from kokoro import KPipeline


def main() -> None:
    lang_code = os.getenv("KOKORO_LANG_CODE", "e")
    voice = os.getenv("KOKORO_VOICE", "ef_dora")
    print(f"Descargando Kokoro lang={lang_code} voice={voice} ...")
    pipeline = KPipeline(lang_code=lang_code, device="cpu")
    pipeline.load_single_voice(voice)
    print("Kokoro listo.")


if __name__ == "__main__":
    main()
