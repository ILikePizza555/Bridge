from functools import reduce
from collections import namedtuple
import bencoding
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


class Torrent:
    """
    Helper class for dealing with torrent files.

    Can access torrent metadata using the [] operator.
    """

    def __init__(self, filename):
        self.filename = filename
        self.files = tuple()

        with open(self.filename, 'rb') as f:
            self.meta = bencoding.decode(f.read())
            self.info_hash = hashlib.sha1(bencoding.encode(self.meta['info'])).digest()

            self._load_files()

    def __getitem__(self, key: str):
        if not isinstance(key, str):
            raise TypeError("Key must be string")
        
        key_split = key.split(".")

        return reduce(operator.getitem, key_split, self.meta)

    def _load_files(self):
        if "files" in self["info"]:
            rv = []

            for item in self["info.files"]:
                decoded_path = [s.decode("utf-8") for s in item["path"]]
                rv.append(TorrentFile(decoded_path[:-1], decoded_path[-1], item["length"]))
            
            self.files = tuple(rv)
        elif "file" in self.meta["info"]:
            self.files = (TorrentFile(self.meta["info.file.name"], self.meta["info.file.length"]),)
        else:
            raise InvalidTorrentError(self.filename, "File does not contain file data in 'info'")