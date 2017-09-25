from pizza_utils.bitfield import Bitfield
import logging
import struct
import socket
import random


logger = logging.getLogger("bridge.peer")


PROTOCOL_STRING = "BitTorrent protocol"
MAX_PEERS = 55
NEW_CONNECTION_LIMIT = 30
PEER_ID_PREFIX = "-BI0001-"


class PeerMessage():
    """
    Base Peer Message class. Simply contains a message id and a length. It's really simple.
    """
    id_map = {}

    def __init_subclass__(cls, message_id: int, length: int = 1, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.message_id = message_id
        cls.length = length

        if type(message_id) == int:
            PeerMessage.id_map[message_id] = cls

        return cls

    def __str__(self):
        return "{}(id: {}, length: {})".format(self.__class__.__name__, self.message_id, self.length)

    def __eq__(self, other):
        return self.message_id == other.message_id and self.length == other.length

    @classmethod
    def decode(cls, data: bytes):
        """Decodes a string of bytes into a message"""
        return cls()

    def encode(self) -> bytes:
        """Encodes this message into a string of bytes to be sent over the network"""
        return struct.pack(">Ib", self.length, self.message_id)


class KeepAlivePeerMessage(PeerMessage, message_id=None, length=0):
    """
    KeepAlive is a special type of message. It only has length (of zero), no id nor payload.
    """
    def encode(self) -> bytes:
        return bytes(4)


class ChokePeerMessage(PeerMessage, message_id=0):
    pass


class UnchokePeerMessage(PeerMessage, message_id=1):
    pass


class InterestedPeerMessage(PeerMessage, message_id=2):
    pass


class NotInterestedPeerMessage(PeerMessage, message_id=3):
    pass


class HavePeerMessage(PeerMessage, message_id=4, length=5):
    def __init__(self, piece_index: int):
        self.piece_index = piece_index

    def __eq__(self, other):
        return super().__eq__(other) and self.piece_index == other.piece_index

    @classmethod
    def decode(cls, data: bytes):
        return cls(struct.unpack(">I", data)[0])

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">I", self.piece_index)


class BitfieldPeerMessage(PeerMessage, message_id=5):
    def __init__(self, bitfield: bytes):
        self.length = 1 + len(bitfield)
        self.bitfield = bitfield

    def __eq__(self, other):
        return super().__eq__(other) and self.bitfield == other.bitfield

    @classmethod
    def decode(cls, data: bytes):
        return cls(data)

    def encode(self) -> bytes:
        return super().encode() + self.bitfield


class RequestPeerMessage(PeerMessage, message_id=6, length=13):
    def __init__(self, index: int, begin: int, size: int):
        self.index = index
        self.begin = begin
        self.size = size

    def __eq__(self, other):
        index_test = self.index == other.index
        begin_test = self.begin == other.begin
        size_test = self.size == other.size

        return super().__eq__(other) and index_test and begin_test and size_test

    @classmethod
    def decode(cls, data: bytes):
        return cls(*struct.unpack(">III", data))

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">III", self.index, self.begin, self.size)


class BlockPeerMessage(PeerMessage, message_id=7):
    def __init__(self, index: int, begin: int, block: bytes):
        self.length = 9 + len(block)

        self.index = index
        self.begin = begin
        self.block = block

    def __eq__(self, other):
        index_test = self.index == other.index
        begin_test = self.begin == other.begin
        block_test = self.block == other.block

        return super().__eq__(other) and index_test and begin_test and block_test

    @classmethod
    def decode(cls, data: bytes):
        i, b = struct.unpack(">II", data[:8])
        return cls(i, b, data[8:])

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">II", self.index, self.begin) + self.block


class CancelPeerMessage(PeerMessage, message_id=8, length=13):
    def __init__(self, index: int, begin: int, size: int):
        self.index = index
        self.begin = begin
        self.size = size

    def __eq__(self, other):
        index_test = self.index == other.index
        begin_test = self.begin == other.begin
        size_test = self.size == other.size

        return super().__eq__(other) and index_test and begin_test and size_test

    @classmethod
    def decode(cls, data: bytes):
        return cls(*struct.unpack(">III", data))

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">III", self.index, self.begin, self.size)


class PortPeerMessage(PeerMessage, message_id=9, length=3):
    def __init__(self, port):
        self.port = port

    def __eq__(self, other):
        return super().__eq__(other) and self.port == other.port

    @classmethod
    def decode(cls, data: bytes):
        return cls(struct.unpack(">H", data)[0])

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">H", self.port)


class PeerMessageIterator():
    def __init__(self, reader):
        self._reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            length_prefix = await self._reader.read(4)

            # Check if more data is present
            if length_prefix == b"":
                raise StopAsyncIteration()

            # Length is a 4-byte big endian integer, and the first of the message
            length, = struct.unpack(">I", length_prefix)

            # If the length is 0, no need to read data, it's a keep alive
            if length == 0:
                return KeepAlivePeerMessage()

            # Read out only the length of the message, parse the message id, then decode the message
            data = await self._reader.read(length)
            message_id = data[0]

            return PeerMessage.id_map[message_id].decode(data[1:])
        except KeyError:
            logger.error("No message found with id {}".format(message_id))
            logger.debug("Full packet: {}".format(length_prefix + data))
        except ConnectionResetError:
            raise StopAsyncIteration()

        raise StopAsyncIteration()


class HandshakeMessage():
    """
    Not part of the peer wire protocol, but it's the first message transmitted by the client which
    initatied the connection.
    """
    @classmethod
    def decode(cls, data: bytes):
        pstring_length = data[0]
        reserved_index = 1 + pstring_length
        info_hash_index = reserved_index + 8
        peer_id_index = info_hash_index + 20

        pstring = data[1:reserved_index].decode("ascii")
        reserved = data[reserved_index:info_hash_index]
        info_hash = data[info_hash_index:peer_id_index]
        peer_id = data[peer_id_index:]

        return cls(info_hash, peer_id, protocol_string=pstring, reserved=reserved)

    def __init__(self, info_hash: bytes, peer_id: bytes,
                 protocol_string: str = PROTOCOL_STRING, reserved: bytes = bytes(8)):
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.protocol_string = protocol_string
        self.reserved = reserved

    def encode(self) -> bytes:
        pstr_header = bytes([len(self.protocol_string)]) + self.protocol_string.encode()
        return pstr_header + self.reserved + self.info_hash + self.peer_id


class Peer():
    """
    Represents a Peer and the necessary connection state.
    
    Attributes:
        - peer_id           The peer id recieved from the tracker, if any exists
        - ip                The ip address of the peer
        - port              The port the peer is listening on
        - am_choking        Is this client choking the peer
        - am_interested     Is this client interested in the peer
        - is_choking        Is the peer choking the client
        - is_interested     Is the peer interested in the client
    """

    @classmethod
    def from_bin(cls, binrep: bytes):
        """Builds a peer from the binary representation"""
        rv = cls(bytes(20), None, struct.unpack(">H", binrep[4:])[0])
        rv.ip = socket.inet_ntoa(binrep[:4])
        return rv

    @classmethod
    def from_str(cls, peer_id: bytes, ip: str, port: int):
        rv = cls(peer_id, None, port)
        rv.ip = ip
        return rv

    def __init__(self, peer_id: bytes, ip: bytes, port: int):
        self.peer_id = peer_id
        self.ip = ip.decode("utf-8") if ip is not None else None
        self.port = port

        self.piecefield = Bitfield(0)

        self.connected = False
        
        self.am_choking = True
        self.am_interested = False
        self.is_choking = True
        self.is_interested = False

    def __eq__(self, other):
        return self.ip == other.ip and self.port == other.port

    def __str__(self):
        return "Peer {} {}:{} connected={}".format(self.peer_id, self.ip, self.port, self.connected)


def generate_peer_id(debug=False):
    if debug:
        return PEER_ID_PREFIX + "4" + "".join(map(str, random.choices(range(0, 10), k=11)))
    else:
        return PEER_ID_PREFIX + "1" + "".join(map(str, random.choices(range(0, 10), k=11)))
