from bridge.data import Torrent
from bridge.tracker import announce_tracker
from bridge.peer import generate_peer_id
import pytest


@pytest.mark.asyncio
async def test_announce():
    t = Torrent("test.torrent", generate_peer_id(True), 8301)

    tracker_response = await announce_tracker(t, t.data.announce[0][0])
    
    print(tracker_response)
    assert tracker_response.sucessful is True
