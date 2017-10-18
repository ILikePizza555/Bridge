"""Contains functions and coroutines for the bit torrent protocol"""
from . import bencoding, peer, data
from typing import Optional
from urllib.parse import urlencode
from pizza_utils.listutils import chunk
import aiohttp
import enum
import logging


class TrackerResponse:
    def __init__(self, response: dict):
        self.response = response
    
    @property
    def sucessful(self) -> bool:
        return b"failure reason" not in self.response

    @property
    def failure_reason(self) -> Optional[str]:
        """Returns a failure reason if one exists. Otherwise returns None."""
        if b"failure reason" in self.response:
            return self.response[b"failure reason"].decode("utf-8")
        return None

    @property
    def warning_message(self) -> Optional[str]:
        """Returns a warning message if one exists. Otherwise returns None."""
        if b"warning message" in self.response:
            return self.response[b"warning message"].decode("utf-8")
        return None

    @property
    def interval(self) -> int:
        return self.response[b"interval"]

    @property
    def min_interval(self) -> Optional[int]:
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
            return [peer.Peer(*p.values()) for p in peers]
        else:
            return [peer.Peer.from_bin(p) for p in chunk(peers, 6)]
    
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
            return "Tracker Failure Response: " + self.failure_reason


class TrackerEvent(enum.Enum):
    started = enum.auto()
    stopped = enum.auto()
    completed = enum.auto()


class TrackerRequest:
    def __init__(self, http_client: aiohttp.ClientSession, torrent: data.Torrent,
                 peer_id: bytes, port: int, ip: Optional[str] = None):
        self.http_client = http_client
        self.torrent = torrent
        self.peer_id = peer_id
        self.port = port
        self.ip = ip

        self.tracker_id = None
        self._logger = logging.getLogger("bridge.tracker")

    def build_get_params(self, compact: int = 1, no_peer_id: int = 0,
                         event: Optional[TrackerEvent] = None,
                         numwant: Optional[int]  = peer.NEW_CONNECTION_LIMIT) -> dict:
        """
        Builds the paramters for use in announce
        :param compact:
        :param no_peer_id:
        :param event:
        :param numwant:
        :return:
        """
        rv = {
            "info_hash": self.torrent.meta.info_hash,
            "peer_id": self.peer_id,
            "port": self.port,
            "uploaded": str(self.torrent.total_uploaded),
            "downloaded": str(self.torrent.total_downloaded),
            "left": str(self.torrent.left),
            "key": self.torrent.key,
            "compact": compact,
            "no_peer_id": no_peer_id
        }

        if event is not None:
            rv["event"] = event.name

        if self.ip is not None:
            rv["ip"] = self.ip

        if numwant is not None:
            rv["numwant"] = numwant

        if self.tracker_id is not None:
            rv["trackerid"] = self.tracker_id

        return rv

    async def _send_announce(self, announce_url: str, params: dict):
        url = announce_url + "?" + urlencode(params)

        async with self.http_client.get(url) as response:
            if response.status == 200:
                return TrackerResponse(bencoding.decode(await response.read())[0])
            else:
                raise ConnectionError("Announce failed."
                                      "Tracker's reponse: \"{}\"".format(await response.text()))

    async def announce(self, **kwargs) -> TrackerResponse:
        if kwargs is not None:
            params = self.build_get_params(**kwargs)

        # TODO: Add support for backups
        # Normally, you go through the first sub-list of URLs and then move to the second sub-list only if all the announces
        # fail in the first list. Then, the sub-lists are rearragned so that the first successful trackers are first in
        # their sub-lists. http://bittorrent.org/beps/bep_0012.html
        for announce_url in self.torrent.meta.announce[0]:
            response = await self._send_announce(announce_url=announce_url, params=params)

            if not response.sucessful:
                self._logger.warning("Announce not successful. Tracker response " + response.failure_reason)
                continue

            return response