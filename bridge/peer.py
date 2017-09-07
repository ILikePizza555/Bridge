import struct
import socket


class PeerMessage():
    """
    Base Peer Message class. Simply contains a message id and a length. It's really simple.
    """
    id_map = {}

    def __init_subclass__(cls, message_id: int, length: int = 1, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.message_id = message_id
        cls.length = length

        PeerMessage.id_map[message_id] = cls

        return cls

    def __str__(self):
        return "PeerMessage(id: {}, length: {})".format(self.message_id, self.length)

    @classmethod
    def decode(cls, data: bytes):
        """Decodes a string of bytes into a message"""
        cls()

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

    @classmethod
    def decode(cls, data: bytes):
        return cls(struct.unpack(">I", data)[0])

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">I", self.piece_index)


class BitfieldPeerMessage(PeerMessage, message_id=5):
    def __init__(self, bitfield: bytes):
        self.length = 1 + len(bitfield)
        self.bitfield = bitfield

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

    @classmethod
    def decode(cls, data: bytes):
        i, b = struct.unpack(">II", data[:9])
        return cls(i, b, data[9:])

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">II", self.index, self.begin) + self.block


class CancelPeerMessage(PeerMessage, message_id=8, length=13):
    def __init__(self, index: int, begin: int, size: int):
        self.index = index
        self.begin = begin
        self.size = size

    @classmethod
    def decode(cls, data: bytes):
        return cls(*struct.unpack(">III", data))

    def encode(self) -> bytes:
        return super().encode() + struct.pack(">III", self.index, self.begin, self.size)


class PortPeerMessage(PeerMessage, message_id=9, length=3):
    def __init__(self, port):
        self.port = port

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
            message_id, = struct.unpack('>b', data[0])

            return PeerMessage.id_map[message_id].decode(data[1:])

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