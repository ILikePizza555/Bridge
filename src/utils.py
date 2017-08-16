from typing import Any


def bytestring_to_string(s: Any) -> str:
    if type(s) == bytearray:
        return s.decode("utf-8")
    return s
