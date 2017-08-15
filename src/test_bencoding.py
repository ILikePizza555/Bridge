import bencoding
import pytest


def test_extract_int():
    return_int, return_string = bencoding.extract_int(b"864234:hellomynameisbob")
    assert return_int == 864234
    assert return_string == b":hellomynameisbob"


def test_decode_byte_string():
    return_string, return_remainder = bencoding.decode(b"7:abcd fg")
    assert return_string == "abcd fg"
    assert return_remainder == b''


def test_decode_integer():
    value, remainder = bencoding.decode(b"i1234e")
    assert value == 1234
    assert remainder == b''


def test_decode_list():
    value, remainder = bencoding.decode(b"li24e4:runai72ee")
    assert value == [24, "runa", 72]
    assert remainder == b''


def test_decode_nested_list():
    value, remainder = bencoding.decode(b"lli1e3:runei1234ee")
    assert value == [[1, "run"], 1234]
    assert remainder == b''


def test_decode_dict():
    value, remainder = bencoding.decode(b"d3:key5:valuei23ei45ee")
    assert value == {"key": "value", 23: 45}
    assert remainder == b''

