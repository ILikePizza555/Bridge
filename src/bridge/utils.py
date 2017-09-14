from typing import Any
from random import choices


def bytestring_to_string(s: Any) -> str:
    if type(s) == bytearray:
        return s.decode("utf-8")
    return s


def generate_peer_id(prefix: str) -> str:
    return prefix + "".join(choices(range(0, 10), 12))