"""Classes for managing bit torrent data"""
from functools import reduce
from collections import namedtuple
from pizza_utils.listutils import split, chunk
from pizza_utils.bitfield import Bitfield
from typing import Optional, Tuple
from . import bencoding, peer, tracker
import aiohttp.client_exceptions
import hashlib
import logging
import math
import operator

TorrentFile = namedtuple("TorrentFile", ["path", "filename", "size"])


class InvalidTorrentError(Exception):
    """Exception for errors involving malformed torrent files.

    Attributes:
        filename -- the file that caused this error
        message -- explaination of error
    """

    def __init__(self, filename, message):
        self.filename = filename
        self.message = message


class TorrentData:
    """
    Helper class for dealing with torrent files.

    Can access raw torrent metadata using the [] operator.

    Atrributes:
        filename    The file where the data was loaded from.
        files       A tuple of the files this torrent represents.
        name        Name of the torrent.
        info_hash   A sha1 hash of the "info" dict.
        pieces      A tuple of the sha1 hashes of all the pieces.
        announce    A list of lists of the announce urls.
    """

    def __init__(self, filename):
        self.filename = filename
        self.files = tuple()

        with open(self.filename, "rb") as f:
            self._meta = bencoding.decode(f.read())[0]
            self.info_hash = hashlib.sha1(bencoding.encode(self["info"])).digest()
            self.name = self["info.name"].decode()

            self._load_files()
            self._load_pieces()
            self._load_announce()

    def __getitem__(self, key):
        if not isinstance(key, str):
            raise TypeError("Key must be string")
        
        # We try and preserve the raw byte strings as much as possible
        # So we convert strings to byte strings to index the dictionaries
        key_split = [k.encode("utf-8") for k in key.split(".")]

        return reduce(operator.getitem, key_split, self._meta)

    def __contains__(self, key):
        if not isinstance(key, str):
            raise TypeError("Key must be string")

        key_split, k = split([k.encode("utf-8") for k in key.split(".")], -1)

        return k[0] in reduce(operator.getitem, key_split, self._meta)

    def __str__(self):
        return "TorrentData - Filename: {}, Info Hash: {}".format(self.filename, self.info_hash)

    def _load_files(self):
        if "info.files" in self:
            rv = []

            for item in self["info.files"]:
                # Decode the byte strings to strings
                decoded_path = [s.decode("utf-8") for s in item[b'path']]
                rv.append(TorrentFile("/".join(decoded_path[:-1]), decoded_path[-1], item[b'length']))
            
            self.files = tuple(rv)
        elif "info.name" in self and "info.length" in self:
            self.files = (TorrentFile("", self["info.name"].decode("utf-8"), self["info.length"]),)
        else:
            raise InvalidTorrentError(self.filename, "File does not contain file data in 'info'")
    
    def _load_pieces(self):
        if "info.pieces" in self:
            self.pieces = tuple(chunk(self["info.pieces"], 20))
        else:
            raise InvalidTorrentError(self.filename, "File does not contain piece data in 'info'")

    def _load_announce(self):
        self.announce = []

        if "announce-list" in self:
            for announce_list in self["announce-list"]:
                self.announce.append([url.decode("utf-8") for url in announce_list])
        elif "announce" in self:
            self.announce.append([self["announce"].decode()])
        else:
            raise InvalidTorrentError(self.filename, "File does not contain announce.")


class Piece():
    """
    Class that represents a piece, and provides a buffer for downloading.

    Attributes:
        downloaded      The piece's data has been downloaded, but not saved
        verified        The piece's data has been downloaded and verified, but not saved
        saved           The piece has been downloaded, verified, and saved.
    """

    def __init__(self, piece_hash: bytes, piece_size: Optional[int]):
        self.piece_hash = piece_hash
        self.piece_size = piece_size

        self.buffer = bytearray()

        self.downloaded = False
        self.verified = False
        self.saved = False

    def __repr__(self):
        if self.downloaded:
            return "Piece {hash}: {buffer}".format(self.piece_hash, self.buffer)
        elif self.verified:
            return "Piece (v) {hask}: {buffer}".format(self.piece_hash, self.buffer)
        elif self.downloaded:
            return "Piece (v,s) {hask}: {buffer}".format(self.piece_hash, self.buffer)
        else:
            return "Piece {hash}".format(self.piece_hash)

    async def download(self, offset: int, data: bytes):
        self.buffer[offset:offset + len(data)] = data

        if len(self.buffer) == self.piece_size:
            self.downloaded = True
    
    async def verify(self) -> bool:
        if hashlib.sha1(self.buffer).digest() == self.piece_hash:
            self.verified = True
            return True
        else:
            return False

    async def save(self, file: TorrentFile, offset: int = 0):
        byte_offset = offset * self.piece_size

        with open(file.path + file.name, mode="w+b") as fh:
            fh.seek(byte_offset)
            fh.write(self.buffer)
        
        # Clean up and free memory
        del self.buffer
        self.buffer = bytearray()

        self.saved = True


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
        self.data = TorrentData(filename)
        self.swarm = []
        self.peers = []

        self.pieces = (Piece(ph, self.data["piece length"]) for ph in self.data.pieces)
        # File indexes are basically pointers to items in the pieces list
        # They're indicators of which pieces correspond to which files
        self.file_indexes = self._calculate_file_indexes()

        self._logger = logging.getLogger("bridge.torrent." + self.data.name)
        self._announce_time = []

    def __str__(self):
        return "Torrent(name: {}, swarm: {}, peers: {})".format(self.data.name, len(self.swarm), len(self.peers))

    def _calculate_file_indexes(self):
        rv = {}
        next_index = 0

        for file in self.data.files:
            rv[next_index] = file
            next_index = next_index + math.ceil(file.size / self.data["piece length"])

    @property
    def uploaded(self) -> str:
        # TODO: Implement
        return str(0)

    @property
    def downloaded(self) -> str:
        # TODO: Implement
        return str(0)

    @property
    def left(self) -> str:
        # TODO: Implement
        return str(1)

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

    async def recieve_piece(self, piece_index: int, offset: int, data: bytes):
        p: Piece = self.pieces[piece_index]

        await p.download(offset, data)

        if p.downloaded:
            self._logger.debug("Downloaded {}".format(p))

            if await p.verify():
                self._logger.debug("Verified {}".format(p))

                f_index, f = self.get_piece_file(piece_index)
                piece_offset = piece_index - f_index

                self._logger.debug("Saving {} to {} offset {}".format(p, f, piece_offset))
                p.save(f, piece_offset)

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
