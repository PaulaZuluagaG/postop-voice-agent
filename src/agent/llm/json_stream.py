"""Utilidades para extraer campos JSON desde respuestas en streaming."""

from __future__ import annotations


class JsonStringFieldExtractor:
    """Extrae tokens de un campo string mientras llega JSON parcial."""

    def __init__(self, field_name: str) -> None:
        self._needle = f'"{field_name}"'
        self._buffer = ""
        self._in_field = False
        self._escape = False
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def feed(self, chunk: str) -> str:
        """Devuelve el texto recién descubierto dentro del campo."""
        if self._done or not chunk:
            return ""

        self._buffer += chunk
        emitted = ""

        while self._buffer and not self._done:
            if not self._in_field:
                idx = self._buffer.find(self._needle)
                if idx == -1:
                    keep = max(0, len(self._buffer) - len(self._needle) + 1)
                    self._buffer = self._buffer[keep:]
                    break

                tail = self._buffer[idx + len(self._needle) :]
                self._buffer = tail.lstrip()
                if not self._buffer.startswith(":"):
                    self._buffer = ""
                    break
                self._buffer = self._buffer[1:].lstrip()
                if not self._buffer.startswith('"'):
                    break
                self._buffer = self._buffer[1:]
                self._in_field = True
                continue

            while self._buffer:
                char = self._buffer[0]
                self._buffer = self._buffer[1:]

                if self._escape:
                    emitted += _decode_json_escape(char)
                    self._escape = False
                    continue

                if char == "\\":
                    self._escape = True
                    continue

                if char == '"':
                    self._done = True
                    break

                emitted += char

        return emitted


def _decode_json_escape(char: str) -> str:
    mapping = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    return mapping.get(char, char)
