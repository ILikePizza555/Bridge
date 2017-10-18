"""Classes for managing per-torrent data"""
from collections import namedtuple
from pizza_utils.listutils import chunk
from pizza_utils.bitfield import Bitfield
from pizza_utils.decs import enforce_state
from . import bencoding, peer
from typing import Union, List, Optional
import enum
import hashlib
import logging
import math
import random

BLOCK_REQUEST_SIZE = 2**15  # Bytes

class TorrentFile:
    """
    A file indicated by the torrent metadata
    """
    __slots__ = ("path", "filename", "size", "piece_pointer")

    def __init__(self, path, filename, size, piece_pointer):
        """
        :param path: The path (relative to the working directory) or the file.
        :param filename: The name of the file on disk.
        :param size: The size of the file in bytes.
        :param piece_pointer: The index of the first piece that holds data for this file.
        """
        self.path = path
        self.filename = filename
        self.size = size
        self.piece_pointer = piece_pointer

    def piece_in_range(self, piece_index: int, piece_length: int) -> bool:
        end = self.piece_pointer + math.ceil(self.size / piece_length)

        return piece_index >= self.piece_pointer and piece_length <= end


def calculate_rarity(peer_list: list, piece_index: int) -> int:
    """Maps rarity to a list of piece indexes"""

    rarity = 0
    for p in peer_list:
        if p.piecefield[piece_index] > 0:
            rarity = rarity + 1

    return rarity


class InvalidTorrentError(Exception):
    """Exception for errors involving malformed torrent files.

    Attributes:
        filename -- the file that caused this error
        message -- explaination of error
    """

    def __init__(self, filename, message):
        self.filename = filename
        self.message = message


class Piece:
    """
    Class that represents a piece, and provides a buffer for downloading.
    """
    class State(enum.Enum):
        EMPTY = enum.auto(),
        FULL = enum.auto()
        VERIFIED = enum.auto(),
        SAVED = enum.auto()

    def __init__(self, piece_hash: bytes, piece_index: int, piece_size: int):
        self.piece_hash = piece_hash
        self.piece_size = piece_size
        self.piece_index = piece_index

        self.buffer = bytearray()

        self.state: Piece.State = Piece.State.EMPTY

    def __repr__(self):
        return "Piece(state={}, piece_hash={}, piece_index={}, piece_size={})".format(
            self.state, self.piece_hash, self.piece_index, self.piece_size
        )

    @enforce_state("state", State.EMPTY)
    async def load(self, offset: int, data: bytes):
        """Loads data into the buffer"""
        self.buffer[offset:offset + len(data)] = data
        if len(self.buffer) == self.piece_size:
            self.state = Piece.State.FULL

    @enforce_state("state", State.FULL)
    async def verify(self) -> bool:
        if hashlib.sha1(self.buffer).digest() == self.piece_hash:
            self.state = Piece.State.VERIFIED
            return True
        else:
            return False

    @enforce_state("state", State.VERIFIED)
    async def save(self, file: TorrentFile, offset: int = 0):
        byte_offset = offset * self.piece_size

        with open(file.path + file.filename, mode="w+b") as fh:
            fh.seek(byte_offset)
            fh.write(self.buffer)

        # Clean up and free memory
        del self.buffer
        self.buffer = bytearray()

        self.state = Piece.State.SAVED


class TorrentMeta:
    """
    Class for storing torrent metadata

    Attributes:
        filename    The filename this object corresponds to
        info_hash   The sha1 hash of the info dict
        announce    A list of list of announce urls
        pieces      A tuple of the sha1 hashes for each piece
        files       A list of TorrentFile objects
    """

    def __init__(self, filename: str):
        """
        Creates a new TorrentMeta object
        :param filename: path to the torrent file
        """
        self.filename = filename

        with open(filename, mode="rb") as f:
            self._meta = bencoding.decode(f.read())[0]

        self.info_hash = hashlib.sha1(bencoding.encode(self._meta["info"])).digest()

        self._init_announce_urls()
        self._init_pieces()
        self._init_files()

    def __repr__(self):
        return "TorrentMeta(filename={} infohash={})".format(self.filename, self.info_hash)

    def _init_announce_urls(self):
        self.announce = []

        if b"announce-list" in self._meta:
            for announce_list in self._meta[b"announce-list"]:
                self.announce.append([url.decode() for url in announce_list])
        elif b"announce" in self._meta:
            self.announce.append([self._meta[b"announce"].decode()])
        else:
            raise InvalidTorrentError(self.filename, "File does not contain an announce.")

    def _init_pieces(self):
        info: dict = self._meta[b"info"]

        if b"pieces" in info:
            self.pieces = tuple(chunk(info[b"pieces"], 20))
        else:
            raise InvalidTorrentError(self.filename, "File does not contain pieces.")

    def _init_files(self):
        self.files = []
        info: dict = self._meta[b"info"]

        if b"files" in info:
            # Multi-file mode
            piece_pointer = 0

            for item in info[b"files"]:
                path = [s.decode() for s in item["path"]]
                size = item[b"length"]

                self.files.append(TorrentFile("/".join(path[:-1]), path[-1], size, piece_pointer))

                piece_pointer += math.floor(size / self.piece_length)
        elif b"name" in info and b"length" in info:
            self.files = [TorrentFile("", info[b"name"].decode(), info[b"length"], 0)]
        else:
            raise InvalidTorrentError(self.filename, "File does not contain files.")

    @property
    def piece_length(self) -> int:
        """
        :return: The size of the pieces in bytes
        """
        info: dict = self._meta[b"info"]  # Do this to appease Pycharm
        return info[b"piece length"]

    @property
    def creation_date(self) -> int:
        """
        :return: The creation time of the torrent in UNIX epoch format.
        """
        return self._meta[b"creation date"]

    @property
    def comment(self) -> str:
        return self._meta[b"comment"].decode()

    @property
    def created_by(self) -> str:
        return self._meta[b"created by"].decode()

    @property
    def encoding(self) -> str:
        return self._meta[b"encoding"].decode()


class Torrent:
    """
    Class for storing Torrent state.

    Attributes:
        meta                The metadata of the torrent
        swarm               All the peers available
        swarm_holds         A list of different indexes of `swarm` that are being held
        total_uploaded      The total amount of bytes uploaded
        total_downloaded    The total amount of bytes downloaded
        pieces              A list of all pieces that correspond to the torrent
        piece_holds         A list of different indexes of `pieces` that are being "held"
        key                 A unique string of bytes announced to the tracker
    """

    def __init__(self, filename: str):
        self.meta = TorrentMeta(filename)
        self.swarm = []
        self.swarm_holds = []

        self.total_uploaded = 0
        self.total_downloaded = 0

        l = self.meta.piece_length
        self.pieces = tuple(Piece(h, i, l) for h, i in self.meta.pieces)
        self.piece_holds = []

        # Unique key to identify the torrent
        self.key = bytes(random.sample(range(0, 256), 8))

        self._logger = logging.getLogger("bridge.torrent." + self.meta.filename)

    @property
    def downloaded(self) -> int:
        rv = 0
        for p in self.pieces:
            if p.state == Piece.State.SAVED:
                rv = rv + p.piece_size
        return rv

    @property
    def left(self) -> int:
        rv = 0
        for p in self.pieces:
            if p.state != Piece.State.VERIFIED:
                rv = rv + p.piece_size
        return rv

    @property
    def bitfield(self) -> Bitfield:
        rv = Bitfield()
        for p in self.pieces:
            if p.state == Piece.State.SAVED:
                rv[0] = 1
            else:
                rv = rv << 1
        
        return rv

    @property
    def needed_peer_amount(self) -> int:
        return max(peer.NEW_CONNECTION_LIMIT - len(self.swarm), 0)

    @property
    def rare_pieces(self) -> List[Piece]:
        """
        :return: A list of pieces, sorted by rarest first.
        """

        return sorted(self.pieces, key=lambda i: calculate_rarity(self.swarm, i.piece_index))

    def insert_peer(self, p: peer.Peer):
        """
        Inserts a peer into the swarm
        :param p:
        :return:
        """

        if p not in self.swarm:
            self.swarm.append(p)

    def insert_peers(self, peers: List[peer.Peer]):
        for p in peers:
            self.insert_peer(p)

    def claim_peer(self, i: int) -> Optional[peer.Peer]:
        """
        Takes the specified peer from the swarm, places a hold, and returns it.
        :param i:
        :return:
        """

        if i not in self.swarm_holds:
            rv = self.swarm[i]
            rv.index = i
            return rv

        return None

    def return_peer(self, p: peer.Peer):
        """
        Removes any holds from the peer. Raises a KeyError if there are no holds.
        :param p:
        :return:
        """
        self.swarm_holds.remove(p.index)

    def claim_piece(self, i: int) -> Optional[Piece]:
        if i not in self.piece_holds:
            self.piece_holds.append(i)
            return self.pieces[i]

        return None

    def return_piece(self, p: Piece):
        self.piece_holds.remove(p.piece_index)

    def find_file(self, piece: Union[int, Piece]) -> TorrentFile:
        """
        Finds the torrent file that the given piece corresponds to.

        :param piece: Either an int representing a piece index, or a Piece object.
        :return:
        """
        if type(piece) == int:
            if piece < 0 or piece >= len(self.pieces):
                raise IndexError("parameter piece ({}) is out of bounds [0, {})".format(piece, len(self.pieces)))
            index = piece
        elif isinstance(piece, Piece):
            index = piece.piece_index

        for f in self.meta.files:
            if f.piece_in_range(index, self.meta.piece_length):
                return f
