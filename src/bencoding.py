from collections import OrderedDict
from typing import Union, Tuple, Optional


TOKEN_STRING_SEPARATOR = 58

TOKEN_INTEGER = 105

TOKEN_LIST = 108

TOKEN_DICTIONARY = 100

TOKEN_END = 101


def is_byte_digit(b: int) -> bool:
    return b >= 48 and b <= 57


def extract_int(s: bytearray) -> int:
    """Extracts an integer from the given bytearry, assuming the first
    value is the starting digit."""

    current_num = bytearray()
    i = 0

    # Because this is a byte array (and thus represented as ints), we have
    # to check the ascii encoding
    while is_byte_digit(s[i]):
        current_num.append(s[i])
        i += 1

    return int(current_num.decode()), s[i:]


def decode(s: bytearray) -> Tuple[Union[str, int, list, OrderedDict, None], Optional[bytearray]]:
    # base case
    if len(s) == 0:
        return None, None

    # byte string
    elif is_byte_digit(s[0]):
        length, remainder = extract_int(s)

        if remainder[0] == TOKEN_STRING_SEPARATOR:
            length += 1
            return remainder[1:length].decode(), remainder[length:]
        
        # TODO: Better errors
        raise RuntimeError("Malformed input")

    # integers
    elif s[0] == TOKEN_INTEGER:
        value, remainder = extract_int(s[1:])

        if remainder[0] == TOKEN_END:
            return value, remainder[1:]

        raise RuntimeError("Malformed input")

    # lists
    elif s[0] == TOKEN_LIST:
        accumulator = []
        remainder = s[1:]
        c = True

        while c:
            value, remainder = decode(remainder)

            accumulator.append(value)

            if len(remainder) == 0 or remainder[0] == TOKEN_END:
                c = False
        
        return accumulator, remainder[1:]

    # dictionary
    elif s[0] == TOKEN_DICTIONARY:
        accumulator = OrderedDict()
        remainder = s[1:]
        c = True

        while c:
            # dictionarties need a value for each key, so we call the function twice
            key, r1 = decode(remainder)
            value, remainder = decode(r1)

            accumulator[key] = value

            if len(remainder) == 0 or remainder[0] == TOKEN_END:
                c = False

        return accumulator, remainder[1:]
    
    raise RuntimeError("Malformed Input - Byte arry did not start with number, \"i\", \"d\", or \"l\"")
