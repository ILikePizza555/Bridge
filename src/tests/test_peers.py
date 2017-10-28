from bridge import peer
from typing import List, Tuple
from functools import reduce
from operator import concat
import asyncio
import pytest
import random

_test_data: Tuple[Tuple[peer.PeerMessage, bytes]] = (
    (peer.KeepAlivePeerMessage(), bytes(4)),
    (peer.ChokePeerMessage(), bytes([0, 0, 0, 1, 0])),
    (peer.UnchokePeerMessage(), bytes([0, 0, 0, 1, 1])),
    (peer.InterestedPeerMessage(), bytes([0, 0, 0, 1, 2])),
    (peer.NotInterestedPeerMessage(), bytes([0, 0, 0, 1, 3])),
    (peer.HavePeerMessage(4), bytes([0, 0, 0, 5, 4, 0, 0, 0, 4])),
    (peer.BitfieldPeerMessage(bytes([1, 2, 3])), bytes([0, 0, 0, 4, 5, 1, 2, 3])),
    (peer.RequestPeerMessage(4, 5, 6), bytes([0, 0, 0, 13, 6, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 6])),
    (peer.BlockPeerMessage(7, 8, b"abc"), bytes([0, 0, 0, 12, 7, 0, 0, 0, 7, 0, 0, 0, 8, 97, 98, 99])),
    (peer.CancelPeerMessage(9, 10, 11), bytes([0, 0, 0, 13, 8, 0, 0, 0, 9, 0, 0, 0, 10, 0, 0, 0, 11])),
    (peer.PortPeerMessage(128), bytes([0, 0, 0, 3, 9, 0, 128]))
)

_test_stream_expected, _test_stream_bytes = zip(
    _test_data[0], _test_data[2], _test_data[3], _test_data[1], _test_data[6],
    _test_data[5], _test_data[7], _test_data[0], _test_data[4], _test_data[8],
    _test_data[0], _test_data[1], _test_data[4], _test_data[2], _test_data[3]
)

_test_stream_bytes = reduce(concat, _test_stream_bytes, b'')


def build_reader(buffer_data: bytes, monkeypatch, reader_size=-1, **kwargs):
    mock_buffer = bytearray(buffer_data)

    async def mock_read(b):
        if len(mock_buffer) == 0:
            raise StopAsyncIteration()

        read_size = b if reader_size <= 0 else min(reader_size, b)

        data = bytes(mock_buffer[:read_size])
        del mock_buffer[:read_size]
        return data

    test_reader = asyncio.StreamReader()
    monkeypatch.setattr(test_reader, 'read', mock_read)

    return peer.PeerMessageIterator(test_reader, **kwargs)


@pytest.mark.parametrize("message,expected", [
    pytest.param(*_test_data[0], id="encode_keep_alive"),
    pytest.param(*_test_data[1], id="encode_choke"),
    pytest.param(*_test_data[2], id="encode_unchoke"),
    pytest.param(*_test_data[3], id="encode_interested"),
    pytest.param(*_test_data[4], id="encode_not_interested"),
    pytest.param(*_test_data[5], id="encode_have"),
    pytest.param(*_test_data[6], id="encode_bitfield"),
    pytest.param(*_test_data[7], id="encode_request"),
    pytest.param(*_test_data[8], id="encode_block"),
    pytest.param(*_test_data[9], id="encode_cancel"),
    pytest.param(*_test_data[10], id="encode_port")
])
def test_encoding(message: peer.PeerMessage, expected: bytes):
    assert message.encode() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer_data,expected", [
    pytest.param(*_test_data[0][::-1], id="decode_keep_alive"),
    pytest.param(*_test_data[1][::-1], id="decode_choke"),
    pytest.param(*_test_data[2][::-1], id="decode_unchoke"),
    pytest.param(*_test_data[3][::-1], id="decode_interested"),
    pytest.param(*_test_data[4][::-1], id="decode_not_interested"),
    pytest.param(*_test_data[5][::-1], id="decode_have"),
    pytest.param(*_test_data[6][::-1], id="decode_bitfield"),
    pytest.param(*_test_data[7][::-1], id="decode_request"),
    pytest.param(*_test_data[8][::-1], id="decode_block"),
    pytest.param(*_test_data[9][::-1], id="decode_cancel"),
    pytest.param(*_test_data[10][::-1], id="decode_port")
])
async def test_individual_iteration(monkeypatch, buffer_data: bytes, expected: peer.PeerMessage):
    """
    Tests that the iterator can handle each of the message individually.
    :param monkeypatch:
    :param buffer_data:
    :param expected:
    :return:
    """
    message_iterator = build_reader(buffer_data, monkeypatch)

    # Actual test
    for message in await message_iterator.load_iterator():
        assert message == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer_data,expected", [
    pytest.param(_test_stream_bytes, _test_stream_expected)
])
async def test_single_stream_iteration(monkeypatch,
                                       buffer_data: bytes,
                                       expected: List[peer.PeerMessage]):
    """
    Tests that the iterator can handle a stream of messages.
    :param monkeypatch:
    :param buffer_data:
    :param expected:
    :return:
    """
    message_iterator = build_reader(buffer_data, monkeypatch)

    actual = tuple(await message_iterator.load_iterator())

    assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer_data,reader_size,expected", [
    pytest.param(_test_stream_bytes, 5, _test_stream_expected)
])
async def test_multi_stream_reader_iteration(monkeypatch,
                                             buffer_data: bytes,
                                             reader_size: int,
                                             expected: List[List[peer.PeerMessage]]):
    """Tests that an iterator can handle an interrupted stream of messages because of incomplete reads."""
    message_iterator = build_reader(buffer_data, monkeypatch, reader_size=reader_size)

    actual = []

    while True:
        a = list(await message_iterator.load_iterator())

        if len(a) == 0:
            break

        actual.append(a)

    assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer_data,buffer_size,expected", [
    pytest.param(_test_stream_bytes, 5, _test_stream_expected)
])
async def test_multi_stream_buffer_iteration(monkeypatch,
                                             buffer_data: bytes,
                                             buffer_size: int,
                                             expected: List[List[peer.PeerMessage]]):
    """Tests that an iterator can handle an interrupted stream of messages because of a small buffer size"""
    message_iterator = build_reader(buffer_data, monkeypatch, buffer_size=buffer_size)
    actual = []

    while True:
        a = list(await message_iterator.load_iterator())

        if len(a) == 0:
            break

        actual.append(a)

    assert actual == expected


def test_decode_handshake():
    pstrlen = bytes([len(peer.PROTOCOL_STRING)])
    pstr = peer.PROTOCOL_STRING.encode()
    reserved = bytes(8)
    info_hash = bytes(random.choices(range(0, 16), k=20))
    peer_id = "Test Peer IDaaaaaaaa".encode()

    data = pstrlen + pstr + reserved + info_hash + peer_id

    actual = peer.HandshakeMessage.decode(data)

    assert actual.info_hash == info_hash
    assert actual.peer_id == peer_id
