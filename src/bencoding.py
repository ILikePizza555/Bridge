from collections import OrderedDict
from typing import Union, Tuple, Optional


TOKEN_STRING_SEPARATOR = 58

TOKEN_INTEGER = 105

TOKEN_LIST = 108

TOKEN_DICTIONARY = 100

TOKEN_END = 101


def is_byte_digit(b: int) -> bool:
    return b >= 48 and b <= 57


def extract_int(s: bytearray) -> Tuple[int, bytearray]:
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


def decode(s: bytearray) -> Tuple[Union[bytearray, int, list, OrderedDict, None], Optional[bytearray]]:
    """
    Decodes a bencoded bytestring.
    """
    # base case
    if len(s) == 0:
        return None, None

    # byte string
    elif is_byte_digit(s[0]):
        return _decode_bytestring(s)

    # integers
    elif s[0] == TOKEN_INTEGER:
        return _decode_int(s)

    # lists
    elif s[0] == TOKEN_LIST:
        return _decode_list(s)

    # dictionary
    elif s[0] == TOKEN_DICTIONARY:
        return _decode_dict(s)
    
    raise RuntimeError('Malformed Input - Byte arry did not start with number, "i", "d", or "l"')


def _decode_bytestring(s: bytearray) -> Tuple[bytearray, bytearray]:
    length, remainder = extract_int(s)

    if remainder[0] == TOKEN_STRING_SEPARATOR:
        length += 1
        return remainder[1:length], remainder[length:]
        
    # TODO: Better errors
    raise RuntimeError("Malformed input")


def _decode_int(s: bytearray) -> Tuple[int, bytearray]:
    value, remainder = extract_int(s[1:])

    if remainder[0] == TOKEN_END:
        return value, remainder[1:]

    raise RuntimeError("Malformed input")


def _decode_list(s: bytearray) -> Tuple[list, bytearray]:
    list_accumulator = []
    remainder = s[1:]
    c = True

    while c:
        value, remainder = decode(remainder)

        list_accumulator.append(value)

        if len(remainder) == 0 or remainder[0] == TOKEN_END:
            c = False

    return list_accumulator, remainder[1:]


def _decode_dict(s: bytearray) -> Tuple[OrderedDict, bytearray]:
    dict_accumulator = OrderedDict()
    remainder = s[1:]
    c = True

    while c:
        # dictionarties need a value for each key, so we call the function twice
        key, r1 = decode(remainder)
        value, remainder = decode(r1)

        dict_accumulator[key] = value

        if len(remainder) == 0 or remainder[0] == TOKEN_END:
            c = False

    return dict_accumulator, remainder[1:]


def encode(data: Union[str, int, list, dict]) -> bytearray:
    """
    Bencodes the specified data
    """
    if type(data) == str:
        return str.encode(str(len(data)) + ":" + data)
    elif type(data) == int:
        return str.encode('i' + str(data) + 'e')
    elif isinstance(data, list):
        return b'l' + b''.join([encode(item) for item in data]) + b'e'
    elif isinstance(data, dict):
        return b'd' + b''.join([encode(key) + encode(value) for key, value in data.items()]) + b'e'
