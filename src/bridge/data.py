"""Classes for managing per-torrent data"""
from collections import namedtuple
from pizza_utils.listutils import chunk
from pizza_utils.bitfield import Bitfield
from pizza_utils.decs import enforce_state
from typing import Tuple
from . import bencoding, peer, tracker
import aiohttp.client_exceptions
import enum
import hashlib
import logging
import math
import random

BLOCK_REQUEST_SIZE = 2**15  # Bytes


TorrentFile = namedtuple("TorrentFile", ["path", "filename", "size", "piece_pointer"])
TorrentFile.__doc__ = """A file indicated by the torrent metadata"""
TorrentFile.path.__doc__ = """The path (relative to the working directory) or the file."""
TorrentFile.filename.__doc__ = """The name of the file on disk."""
TorrentFile.size.__doc__ = """The size of the file in bytes."""
TorrentFile.piece_pointer.__doc__ = "The index of the first piece that holds data for this file."


def calculate_rarity(peer_list: list, piece_count: int):
    """Maps rarity to a list of piece indexes"""
    pieces = {}

    for i in range(0, piece_count):
        rarity = 0
        for p in peer_list:
            if p.piecefield[i] > 0:
                rarity = rarity + 1

        if rarity in pieces:
            pieces[rarity].append(i)
        else:
            pieces[rarity] = [i]

    return pieces


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

    def __str__(self):
        return "TorrentMeta {} infohash: {}".format(self.filename, self.info_hash)

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
        data            The TorrentData of the Torrent
        swarm           A list of all the peers.
        peers           A list of the peers the client is connected too
        pieces          A list of the pieces
        file_indexes    A map of piece indexes and files
    """

    def __init__(self, filename: str):
        self.data = TorrentMeta(filename)
        self.swarm = []
        self.peers = []

        self.total_uploaded = 0
        self.total_downloaded = 0

        self.pieces = tuple(Piece(ph, self.data["info.piece length"]) for ph in self.data.pieces)
        self.downloading = []
        # File indexes are basically pointers to items in the pieces list
        # They're indicators of which pieces correspond to which files
        self.file_indexes = self._calculate_file_indexes()

        # Unique key to identify the torrent
        self.key = bytes(random.sample(range(0, 256), 8))

        self._logger = logging.getLogger("bridge.torrent." + self.data.name)
        self._announce_time = []
        self._celebrate = False

    def __str__(self):
        return "Torrent(name: {}, swarm: {}, peers: {})".format(self.data.name, len(self.swarm), len(self.peers))

    @property
    def downloaded(self) -> int:
        rv = 0
        for p in self.pieces:
            if p.saved:
                rv = rv + p.piece_size
        return rv

    @property
    def left(self) -> int:
        rv = 0
        for p in self.pieces:
            if not p.verified:
                rv = rv + p.piece_size
        return rv
    
    def _calculate_file_indexes(self):
        rv = {}
        next_index = 0

        for file in self.data.files:
            rv[next_index] = file
            next_index = next_index + math.ceil(file.size / self.data["info.piece length"])

    @property
    def bitfield(self) -> Bitfield:
        rv = Bitfield()
        for p in self.pieces:
            if p.saved:
                rv[0] = 1
            else:
                rv = rv << 1
        
        return rv

    def get_piece_file(self, i: int) -> Tuple[int, TorrentFile]:
        for index, file in reversed(self.file_indexes):
            if i > index:
                return (index, file)

    def ask_for_block(self, remote_peer) -> peer.PeerMessage:
        for i in self.downloading:
            if remote_peer.piecefield[i] > 0:
                offset = len(self.pieces[i].buffer)
                self._logger.debug("Asking for piece {} at offset {} from {}".format(i, offset, remote_peer))
                return peer.RequestPeerMessage(i, offset, BLOCK_REQUEST_SIZE)

        rp = calculate_rarity(self.swarm, len(self.pieces))
        rarity = sorted(rp.keys(), reverse=True)

        for r in rarity:
            for i in rp[r]:
                if remote_peer.piecefield[i] > 0 and i not in self.downloading and not self.pieces[i].verified:
                    self._logger.debug("Asking for piece {} from {}".format(i, remote_peer))
                    return peer.RequestPeerMessage(i, 0, BLOCK_REQUEST_SIZE)

    async def recieve_block(self, piece_index: int, offset: int, data: bytes):
        """Handler for recieving a block of data"""
        p: Piece = self.pieces[piece_index]
        self.downloading.append(piece_index)
        self.total_downloaded = self.total_downloaded + len(data)

        await p.download(offset, data)

        if p.downloaded:
            self._logger.debug("Downloaded {}".format(p))

            if await p.verify():
                # The piece has been fully downloaded and verified, save to disk
                self._logger.debug("Verified {}".format(p))

                f_index, f = self.get_piece_file(piece_index)
                piece_offset = piece_index - f_index

                self._logger.debug("Saving {} to {} offset {}".format(p, f, piece_offset))

                try:
                    p.save(f, piece_offset)
                    self._logger.info("Successfully downloaded piece {}.".format_map(piece_index))

                    # Because why not
                    if self._celebrate is False:
                        print("Congrats! You just downloaded your first piece! :)")
                        print("Here it is:")
                        print(p.buffer)

                        self._celebrate = True
                except OSError:
                    self._logger.warn("Error downloading piece {}. Discarding.")
                    p.recycle()
                finally:
                    self.downloading.remove(piece_index)
            else:
                self._logger.debug("Piece {} failed to verify. Recycling.".format(p))
                p.recycle()

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
