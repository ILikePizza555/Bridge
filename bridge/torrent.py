"""Classes for managing bit torrent data"""
from functools import reduce
from collections import namedtuple
from pizza_utils.listutils import split, chunk
from . import bencoding, tracker, peer
import hashlib
import logging
import operator

MAX_PEERS = 55
NEW_CONNECTION_LIMIT = 30

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
        announce    A tuple of the announce urls.
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
        if "announce" in self:
            if "announce-list" in self:
                full_list = self["announce"] + self["announce-list"]
                self.announce = tuple(url.decode() for url in full_list)
            else:
                self.announce = (self["announce"].decode(),)
        else:
            raise InvalidTorrentError(self.filename, "File does not contain announce.")

    def __str__(self):
        return "TorrentData - Filename: {}, Info Hash: {}".format(self.filename, self.info_hash)


class Torrent:
    """
    Class for storing Torrent state.

    Attributes:
        data        The TorrentData of the Torrent
        peer_id     A bytes object that holds the peer_id for transmission
        port        The port this client is listening on
        peers       A list of all the peers this torrent is connected too
        swarm       A list of all the peers the tracker has reported
    """

    def __init__(self, filename: str, peer_id: str, port: int):
        self.data = TorrentData(filename)
        self.peer_id = peer_id.encode()
        self.port = port

        self.peers = []
        self.swarm = []

        self.logger = logging.getLogger("bridge.torrent." + self.data.name[:8])

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

    async def annnounce(self):
        self.logger.info("Beginning anounce...")

        for announce_url in self.data.announce:
            self.logger.info("Announcing on " + announce_url)

            tracker.announce_tracker(self, announce_url )
