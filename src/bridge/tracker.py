"""Contains functions and coroutines for the bit torrent protocol"""
from . import bencoding, peer
from typing import Optional
from urllib.parse import urlencode
from pizza_utils.listutils import chunk
import aiohttp
import enum


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


async def announce_tracker(torrent: 'data.Torrent',
                           peer_id: bytes,
                           announce_url: str,
                           port: int,
                           compact: int = 1,
                           no_peer_id: int = 0,
                           trackerid: Optional[str] = None,
                           event: Optional[TrackerEvent] = None,
                           ip: Optional[str] = None,
                           numwant: Optional[int] = peer.NEW_CONNECTION_LIMIT) -> TrackerResponse:
    """
    Announces to the tracker.

    Params:
        - torrent: The torrent object that corresponds to the announce
        - announce_url: the url to announce to
        - compact: Optional. Indicates that the client accepts a compact response. Defaults to 1.
        - no_peer_id: Optional. Indicates that the tracker can omit peer_ids. Defaults to 0.
        - key: Optional. An additional id that's not shared with other peers.
        - trackerid: Optional. A previously recieved string that should be sent on next announcements
        - event: Optional.
        - ip: Optional. The true ip of the client
        - numwant: Optional. The number of peers the client wants to recieve. Defaults to NEW_CONNECTION_LIMIT.
    """
    get_params = {
        "info_hash": torrent.data.info_hash,
        "peer_id": peer_id,
        "port": port,
        "uploaded": str(torrent.total_uploaded),
        "downloaded": str(torrent.total_downloaded),
        "left": str(torrent.left),
        "key": torrent.key,
        "compact": compact,
        "no_peer_id": no_peer_id
    }

    if event is not None:
        get_params["event"] = event.name

    if ip is not None:
        get_params["ip"] = ip

    if numwant is not None:
        get_params["numwant"] = numwant

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

"""
    async def announce(self, port: int, peer_id: bytes):
        self._logger.info("Beginning anounce...")

        # TODO: Add support for backups
        # Normally, you go through the first sub-list of URLs and then move to the second sub-list only if all the announces
        # fail in the first list. Then, the sub-lists are rearragned so that the first successful trackers are first in
        # their sub-lists. http://bittorrent.org/beps/bep_0012.html
        for announce_url in self.data.announce[0]:
            self._logger.info("Announcing on " + announce_url)

            peer_count_request = max(peer.NEW_CONNECTION_LIMIT - len(self.peers), 0)
            self._logger.info("Requesting {} peers".format(peer_count_request))

            try:
                response = await tracker.announce_tracker(self, peer_id, announce_url, port, numwant=peer_count_request)

                if not response.sucessful:
                    self._logger.warning("Announce on {} not successful. {}".format(announce_url, str(response)))
                    continue

                self._logger.info("Announce successful.")

                if peer_count_request > 0:
                    # Dump all the peers into the swarm
                    new_peers = [p for p in response.peers if p not in self.swarm]
                    self.swarm.extend(new_peers)
                    self._logger.info("Adding {} new peers into the swarm. (Now {})".format(len(new_peers), len(self.swarm)))
            except aiohttp.client_exceptions.ClientConnectionError:
                self._logger.error("Failed to connect to tracker {}".format(announce_url))
                continue
"""
