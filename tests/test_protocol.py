from bridge.torrent import TorrentData
from bridge.protocol import announce_tracker, generate_peer_id, encode_peer_message, PeerMessage
from collections import namedtuple
import asyncio
import pytest


_TestTorrent = namedtuple("Torrent", ["data"])


@pytest.mark.asyncio
async def test_announce():
    t = _TestTorrent(data=TorrentData("test.torrent"))

    tracker_response = await announce_tracker(t, t.data["announce"].decode("utf-8"),
                                              generate_peer_id(True), 8301)
    
    print(tracker_response)
    assert tracker_response.sucessful is True


@pytest.mark.parametrize("message,data,expected", [
    (PeerMessage.keep_alive,        None,               bytes(4)),
    (PeerMessage.choke,             None,               bytes([0, 0, 0, 1, 0])),
    (PeerMessage.unchoke,           None,               bytes([0, 0, 0, 1, 1])),
    (PeerMessage.interested,        None,               bytes([0, 0, 0, 1, 2])),
    (PeerMessage.not_interested,    None,               bytes([0, 0, 0, 1, 3])),
    (PeerMessage.have,              4,                  bytes([0, 0, 0, 5, 4, 0, 0, 0, 4])),
    (PeerMessage.bitfield,          bytes([1, 2, 3]),   bytes([0, 0, 0, 4, 5, 1, 2, 3])),
    (PeerMessage.request,           (4, 5, 6),          bytes([0, 0, 0, 13, 6, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 6])),
    (PeerMessage.piece,             (7, 8, b"abc"),     bytes([0, 0, 0, 12, 7, 0, 0, 0, 7, 0, 0, 0, 8, 97, 98, 99])),
    (PeerMessage.cancel,            (9, 10, 11),        bytes([0, 0, 0, 13, 8, 0, 0, 0, 9, 0, 0, 0, 10, 0, 0, 0, 11])),
    (PeerMessage.port,              128,                bytes([0, 0, 0, 3, 9, 0, 128]))
])
def test_encode(message, data, expected):
    result = encode_peer_message(message)
    assert result == expected


@pytest.mark.asyncio
async def test_peer_message_iterator():
    test_reader = asyncio.StreamReader()
    test_reader._buffer = bytearray()