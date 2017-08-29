from bridge.torrent import TorrentData
from bridge.protocol import announce_tracker, generate_peer_id
from collections import namedtuple
import pytest


_TestTorrent = namedtuple("Torrent", ["data"])


@pytest.mark.asyncio
async def test_announce():
    t = _TestTorrent(data=TorrentData("test.torrent"))

    tracker_response = await announce_tracker(t, t.data["announce"].decode("utf-8"),
                                              generate_peer_id(True), 6050)
    
    print(tracker_response)
    assert tracker_response.sucessful is True
