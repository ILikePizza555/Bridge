"""Classes for managing bit torrent data"""
from functools import reduce
from collections import namedtuple
from pizza_utils.listutils import split
from . import bencoding
import hashlib
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
    """

    def __init__(self, filename):
        self.filename = filename
        self.files = tuple()

        with open(self.filename, "rb") as f:
            self._meta = bencoding.decode(f.read())[0]
            self.info_hash = hashlib.sha1(bencoding.encode(self["info"])).digest()

            self._load_files()

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