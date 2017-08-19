from bridge import bencoding

from collections import OrderedDict


def test_extract_int():
    return_int, return_string = bencoding.extract_int(b"864234:hellomynameisbob")
    assert return_int == 864234
    assert return_string == b":hellomynameisbob"


def test_decode_byte_string():
    return_string, return_remainder = bencoding.decode(b"7:abcd fg")
    assert return_string == b"abcd fg"
    assert return_remainder == b''


def test_decode_integer():
    value, remainder = bencoding.decode(b"i1234e")
    assert value == 1234
    assert remainder == b''


def test_decode_list():
    value, remainder = bencoding.decode(b"li24e4:runai72ee")
    assert value == [24, b"runa", 72]
    assert remainder == b''


def test_decode_nested_list():
    value, remainder = bencoding.decode(b"lli1e3:runei1234ee")
    assert value == [[1, b"run"], 1234]
    assert remainder == b''


def test_decode_dict():
    value, remainder = bencoding.decode(b"d3:key5:valuei23ei45ee")
    assert value == {b"key": b"value", 23: 45}
    assert remainder == b''


def test_decode_torrent():
    with open('test.torrent', 'rb') as t:
        data = t.read()

        value, remainder = bencoding.decode(data)
        assert type(value) == OrderedDict
        assert value[b'announce'] == b'http://torrent.ubuntu.com:6969/announce'
        assert value[b'info'][b'length'] == 1609039872


def test_encode_string():
    return_string = bencoding.encode("abcd")
    assert return_string == b'4:abcd'


def test_encode_int():
    return_string = bencoding.encode(42)
    assert return_string == b'i42e'


def test_encode_list():
    return_string = bencoding.encode([42, "abcd"])
    assert return_string == b'li42e4:abcde'


def test_encode_dict():
    return_string = bencoding.encode(OrderedDict({"key": "value", 42: 25}))
    assert return_string == b'd3:key5:valuei42ei25ee'