"""Contains functions and coroutines for the bit torrent protocol"""
from . import bencoding
from .torrent import Torrent, NEW_CONNECTION_LIMIT
from typing import Any, Optional
from random import choices
from urllib.parse import urlencode
from pizza_utils.listutils import chunk
import aiohttp
import enum
import socket
import struct


PEER_ID_PREFIX = "-BI0001-"


@enum.unique
class PeerMessage(enum.IntEnum):
    keep_alive = -1
    choke = 0
    unchoke = 1
    interested = 2
    not_interested = 3
    have = 4
    bitfield = 5
    request = 6
    piece = 7
    cancel = 8
    port = 9


class PeerMessageIterator():
    def __init__(self, reader):
        self._reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            fd = await self._reader.read(4)

            # Check if more data is present
            if fd == b"":
                raise StopAsyncIteration()

            # Length is a 4-byte big endian integer, and the first of the message
            length = struct.unpack(">I", fd)[0]

            # If the length is 0, no need to read data, it's a keep alive
            if length == 0:
                return (PeerMessage.keep_alive, None)

            #Read out only the length of the message, parse the message id, then parse the message
            data = await self._reader.read(length)
            message_id = struct.unpack('>b', data[0])[0]

            if message_id < 4 and message_id >= 0:
                return (PeerMessage(message_id), None)

            if message_id == 4:
                return (PeerMessage.have, struct.unpack(">I", data[1:]))

            if message_id == 5:
                # TODO: Add bitfield verification here
                return (PeerMessage.bitfield, data[1:])

            if message_id == 6:
                # The request message has 3 integers as it's payload
                i = struct.unpack(">I", data[1:5])[0]
                b = struct.unpack(">I", data[5:9])[0]
                l = struct.unpack(">I", data[9:13])[0]

                return (PeerMessage.request, (i, b, l))

            if message_id == 7 or message_id == 8:
                # The piece (block) message has 2 integers and data as it's payload
                # The cancel message has a payload identical to the piece message
                i = struct.unpack(">I", data[1:5])[0]
                b = struct.unpack(">I", data[5:9])[0]
                block = data[9:]

                return (PeerMessage(message_id), (i, b, block))

            if message_id == 9:
                return (PeerMessage.port, struct.unpack(">H", data[1:])[0])

        except ConnectionResetError:
            raise StopAsyncIteration()


class Peer():
    """
    Represents a Peer and the necessary connection state.
    
    Attributes:
        - peer_id           The peer id recieved from the tracker, if any exists
        - ip                The ip address of the peer
        - port              The port the peer is listening on
        - am_choking        Is this client choking the peer
        - am_interested     Is this client interested in the peer
        - peer_choking      Is the peer choking the client
        - peer_interested   Is the peer interested in the client
    """

    @classmethod
    def from_bin(cls, binrep: bytes):
        """Builds a peer from the binary representation"""
        rv = cls(None, None, 0)

        rv.ip = socket.inet_ntoa(binrep[:4])
        # Port is a 2-byte big endian integer
        rv.port = struct.unpack(">H", binrep[4:])[0]

        return rv

    def __init__(self, peer_id: bytes, ip: bytes, port: int):
        self.peer_id = peer_id.decode("utf-8") if peer_id is not None else None
        self.ip = ip.decode("utf-8") if ip is not None else None
        self.port = port

        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False

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


class TrackerEvent(enum.Enum):
    started = enum.auto()
    stopped = enum.auto()
    completed = enum.auto()


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


def encode_peer_message(m: PeerMessage, data: Any = None) -> bytes:
    """
    Encodes a PeerMessage and a payload into a bytes object to be sent over the network.
    All payloads should be represented in the same way they're recieved from PeerMessageIterator

    Keep-alive, chock, unchok, interested, and not interested ignore the data parameter
    Have takes a single integer
    Bitfield takes a bytes object as it's payload
    Request takes a tuple of 3 integers
    Piece and cancel takes a tuple (int, int, bytes)
    Port takes an integer
    """

    if m is PeerMessage.keep_alive:
        return struct.pack(">I", 0)
    # choke, unchoke, interested, and not interested are all similar except for id
    elif m.value >= 0 and m.value <= 3:
        return struct.pack(">I", 1) + struct.pack('>b', m.value)
    elif m is PeerMessage.have:
        return struct.pack(">I", 5) + struct.pack('>b', m.value) + struct.pack(">I", data)
    elif m is PeerMessage.bitfield:
        return struct.pack(">I", 1 + len(data)) + struct.pack('>b', m.value) + data
    elif m is PeerMessage.request:
        return struct.pack(">I", 13) + struct.pack('>b', m.value) + struct.pack(">I", data[0]) + struct.pack(">I", data[1]) + struct.pack(">I", data[2])
    elif m is PeerMessage.piece or PeerMessage.cancel:
        header = struct.pack(">I", 9 + len(data[2])) if m is PeerMessage.piece else struct.pack(">I", 13)
        return header + struct.pack('>b', m.value) + struct.pack(">I", data[0]) + struct.pack(">I", data[1]) + data[2]
    elif m is PeerMessage.port:
        return struct.pack(">I", 3) + struct.pack('>b', m.value) + struct.pack(">H", data)


def generate_peer_id(debug=False):
    if debug:
        return PEER_ID_PREFIX + "4" + "".join(map(str, choices(range(0, 10), k=11)))
    else:
        return PEER_ID_PREFIX + "1" + "".join(map(str, choices(range(0, 10), k=11)))
