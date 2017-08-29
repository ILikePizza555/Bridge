"""Contains functions and coroutines for the bit torrent protocol"""
from . import bencoding
from .torrent import Torrent, NEW_CONNECTION_LIMIT
from typing import Optional
from enum import auto, Enum
from random import choices
from urllib.parse import urlencode
from pizza_utils.listutils import chunk
from struct import unpack
import aiohttp
import socket


PEER_ID_PREFIX = "-BI0001-"


class Peer():
    @classmethod
    def from_bin(cls, binrep: bytes):
        """Builds a peer from the binary representation"""
        rv = cls(None, None, 0)

        rv.ip = socket.inet_ntoa(binrep[:4])
        rv.port = unpack(">H", binrep[4:])[0]

        return rv

    def __init__(self, peer_id: bytes, ip: bytes, port: int):
        self.peer_id = peer_id.decode("utf-8") if peer_id is not None else None
        self.ip = ip.decode("utf-8") if ip is not None else None
        self.port = port

    def __str__(self):
        return "{}:{}".format(self.ip, self.port)


class TrackerResponse():
    def __init__(self, response: dict):
        self.response = response
    
    @property
    def sucessful(self) -> bool:
        return b"failure reason" not in self.response

    @property
    def failure_reason(self) -> str:
        """Returns a failure reason if one exists. Otherwise returns None."""
        if b"failure reason" in self.response:
            return self.response[b"failure reason"].decode("utf-8")
        return None

    @property
    def warning_message(self) -> str:
        """Returns a warning message if one exists. Otherwise returns None."""
        if b"warning message" in self.response:
            return self.response[b"warning message"].decode("utf-8")
        return None

    @property
    def interval(self) -> int:
        return self.response[b"interval"]

    @property
    def min_interval(self) -> int:
        if b"min interval" in self.response:
            return self.response[b"min interval"]
        return None

    @property
    def tracker_id(self) -> bytes:
        return self.response[b"tracker id"]

    @property
    def seeders(self) -> int:
        return self.response[b"complete"]

    @property
    def leechers(self) -> int:
        return self.response[b"incomplete"]

    @property
    def peers(self) -> list:
        peers = self.response[b"peers"]

        if type(peers) == list:
            # Dictionary model
            return [Peer(*p.values()) for p in peers]
        else:
            return [Peer.from_bin(p) for p in chunk(peers, 6)]
    
    def __str__(self):
        if self.sucessful:
            return ("Tracker Response\n"
                    "warning: {}\n"
                    "seeders: {}\n"
                    "leechers: {}\n"
                    "peers: {}"
                    ).format(self.warning_message, 
                             self.seeders,
                             self.leechers,
                             self.peers)
        else:
            return "Tracker Response: " + self.failure_reason


class TrackerEvent(Enum):
    started = auto()
    stopped = auto()
    completed = auto()


async def announce_tracker(torrent: Torrent,
                           announce_url: str,
                           peer_id: str,
                           port: int,
                           key: Optional[int] = None,
                           trackerid: Optional[str] = None,
                           compact: int = 0,
                           no_peer_id: int = 0,
                           event: Optional[TrackerEvent] = None,
                           ip: Optional[str] = None,
                           numwant: Optional[int] = NEW_CONNECTION_LIMIT) -> TrackerResponse:
    """Announces to the tracker defined in torrent"""
    get_params = {
        "info_hash": torrent.data.info_hash,
        # Peer_id may have binary data so we urlencode it here.
        "peer_id": peer_id,
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

        url = announce_url + "?" + urlencode(get_params)

        async with session.get(url) as resp:

            if resp.status == 200:
                return TrackerResponse(bencoding.decode(await resp.read())[0])
            else:
                raise ConnectionError("Announce failed."
                                      "Tracker's reponse: \"{}\"".format(await resp.text()))


def generate_peer_id(debug=False):
    if debug:
        return PEER_ID_PREFIX + "4" + "".join(map(str, choices(range(0, 10), k=11)))
    else:
        return PEER_ID_PREFIX + "1" + "".join(map(str, choices(range(0, 10), k=11)))
