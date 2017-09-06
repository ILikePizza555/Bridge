from bridge.torrent import TorrentData
from bridge.protocol import announce_tracker, generate_peer_id, encode_peer_message, PeerMessage, PeerMessageIterator
from collections import namedtuple
import asyncio
import pytest


_TestTorrent = namedtuple("Torrent", ["data"])


_encode_test_data = [
    (PeerMessage.keep_alive, None, bytes(4)),
    (PeerMessage.choke, None, bytes([0, 0, 0, 1, 0])),
    (PeerMessage.unchoke, None, bytes([0, 0, 0, 1, 1])),
    (PeerMessage.interested, None, bytes([0, 0, 0, 1, 2])),
    (PeerMessage.not_interested, None, bytes([0, 0, 0, 1, 3])),
    (PeerMessage.have, 4, bytes([0, 0, 0, 5, 4, 0, 0, 0, 4])),
    (PeerMessage.bitfield, bytes([1, 2, 3]), bytes([0, 0, 0, 4, 5, 1, 2, 3])),
    (PeerMessage.request, (4, 5, 6), bytes([0, 0, 0, 13, 6, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 6])),
    (PeerMessage.block, (7, 8, b"abc"), bytes([0, 0, 0, 12, 7, 0, 0, 0, 7, 0, 0, 0, 8, 97, 98, 99])),
    (PeerMessage.cancel, (9, 10, 11), bytes([0, 0, 0, 13, 8, 0, 0, 0, 9, 0, 0, 0, 10, 0, 0, 0, 11])),
    (PeerMessage.port, 128, bytes([0, 0, 0, 3, 9, 0, 128]))
]


_encode_test_ids = ["encode_keep_alive",
                    "encode_choke",
                    "encode_unchoke",
                    "encode_interested",
                    "encode_not_interested",
                    "encode_have",
                    "encode_bitfield",
                    "encode_request",
                    "encode_block",
                    "encode_cancel",
                    "encode_port"]


_decode_test_data = [
    ((PeerMessage.keep_alive,), "decode_keep_alive"),
    ((PeerMessage.choke,), "decode_choke"),
    ((PeerMessage.unchoke,), "decode_unchoke"),
    ((PeerMessage.interested,), "decode_interested"),
    ((PeerMessage.not_interested,), "decode_not_interested"),
    ((PeerMessage.choke, 4), "decode_have"),
    ((PeerMessage.bitfield, bytes([1, 2, 3])), "decode_bitfield"),
    ((PeerMessage.request, 7, 42, 99), "decode_request"),
    ((PeerMessage.block, 1, 5, bytes([2, 2, 2, 4])), "decode_bytes"),
    ((PeerMessage.cancel, 7, 42, 99), "decode_cancel"),
    ((PeerMessage.port, 245), "decode_port")
]


def _build_decode_test_params():
    return [pytest.param(encode_peer_message(*i[0]), i[0], id=i[1]) for i in _decode_test_data]


@pytest.mark.asyncio
async def test_announce():
    t = _TestTorrent(data=TorrentData("test.torrent"))

    tracker_response = await announce_tracker(t, t.data["announce"].decode("utf-8"),
                                              generate_peer_id(True), 8301)
    
    print(tracker_response)
    assert tracker_response.sucessful is True


@pytest.mark.parametrize("message,data,expected", _encode_test_data, ids=_encode_test_ids)
def test_encode(message, data, expected):
    if hasattr(data, '__iter__') and type(data) != bytes:
        result = encode_peer_message(message, *data)
    else:
        result = encode_peer_message(message, data)

    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("bufferdata,expected", _build_decode_test_params())
async def test_peer_message_iterator_single(bufferdata, expected):
    # Build the reader
    test_reader = asyncio.StreamReader()
    test_reader._buffer = bytearray(bufferdata)

    result = [i async for i in PeerMessageIterator(test_reader)]

    assert len(result) == 1
    assert result[0] == expected
