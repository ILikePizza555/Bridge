"""Contains functions and coroutines for the bit torrent protocol"""
from .torrent import Torrent, NEW_CONNECTION_LIMIT
from collections import namedtuple
from typing import Optional, Union
from enum import auto, Enum
from urllib.parse import quote, quote_from_bytes
import aiohttp
import bencoding


TrackerResponse = namedtuple('TrackerResponse', ["warning_message", "interval", "min_interval",
                                                 "tracker_id", "complete", "incomplete", "peers"])


class TrackerEvent(Enum):
    started = auto()
    stopped = auto()
    completed = auto()


async def announce_tracker(torrent: Torrent,
                           announce_url: str,
                           peer_id: str,
                           port: int,
                           key: Optional[int],
                           trackerid: Optional[str],
                           compact: int = 0,
                           no_peer_id: int = 0,
                           event: Optional[TrackerEvent] = None,
                           ip: Optional[str] = None,
                           numwant: Optional[int] = NEW_CONNECTION_LIMIT) -> TrackerResponse:
    """Announces to the tracker defined in torrent"""
    get_params = {
        "info_hash": quote_from_bytes(torrent.data.info_hash),
        # Peer_id may have binary data so we urlencode it here.
        "peer_id": quote(peer_id),
        "port": port,
        # TODO: Implement uploaded, downloaded, and left (should be in torrent)
        "uploaded": str(0),
        "downloaded": str(0),
        "left": str(1),
        "compact": compact,
        "no_peer_id": no_peer_id
    }

    if event is not None:
        get_params["event"] = event.name
    
    if ip is not None:
        get_params["ip"] = ip

    if numwant is not None:
        get_params["numwant"] = numwant

    if key is not None:
        get_params["key"] = key

    if trackerid is not None:
        get_params["trackerid"] = trackerid

    # TODO: Stop creating as session everytime we need to announce
    async with aiohttp.ClientSession() as session:
        async with session.get(announce_url, **get_params) as resp:
            resp_dict = bencoding.decode(await resp.read())

            if resp.status == 200:
                return TrackerResponse()