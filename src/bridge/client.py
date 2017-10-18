from . import data, peer, tracker
from pizza_utils.bitfield import Bitfield
from typing import List
import asyncio
import aiohttp
import logging
import math


message_handlers = {}


def message_handler(message_type):
    """
    Decorator used to bind message handler functions to PeerClient
    :param message_type:
    :return:
    """
    def decorator(func):
        message_handlers[message_type] = func
    return decorator


class PeerClient:
    """
    Represents a connection to a peer. Handles incoming messages and sends out messages.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 p: peer.Peer, torrent: data.Torrent):
        self.peer = p
        self.torrent = torrent
        self.writer = writer

        self.message_iter = peer.PeerMessageIterator(reader)
        self._logger = logging.getLogger("bridge.PeerClient.{}".format(p.peer_id))

    def __repr__(self):
        return "PeerClient to: {}:{}; for {}".format(self.peer.ip,
                                                     self.peer.port,
                                                     self.torrent.meta.info_hash)

    async def handle(self):
        """
        Handles incoming peer messages and responds.
        """
        async for message in self.message_iter.buffer():
            if type(message) == peer.KeepAlivePeerMessage:
                self.writer.write(peer.KeepAlivePeerMessage().encode())

            message_handlers[type(message)](self, message)


@message_handler(peer.ChokePeerMessage)
async def _handle_choke(pc: PeerClient, m: peer.ChokePeerMessage):
    pc._logger.debug("Got choke message.")
    pc.peer.is_choking = True


@message_handler(peer.UnchokePeerMessage)
async def _handle_unchoke(pc: PeerClient, m: peer.UnchokePeerMessage):
    pc._logger.debug("Got unchoke message.")
    pc.peer.is_choking = False


@message_handler(peer.InterestedPeerMessage)
async def _handle_interested(pc: PeerClient, m: peer.InterestedPeerMessage):
    pc._logger.debug("Got interested message.")
    pc.peer.is_interested = True


@message_handler(peer.NotInterestedPeerMessage)
async def _handle_not_interested(pc: PeerClient, m: peer.NotInterestedPeerMessage):
    pc._logger.debug("Got not interested message.")
    pc.peer.is_interested = False


@message_handler(peer.HavePeerMessage)
async def _handle_have(pc: PeerClient, m: peer.HavePeerMessage):
    pc._logger.debug("Got have message, piece {}.".format(m.piece_index))
    pc.peer.piecefield[m.piece_index] = 1


@message_handler(peer.BitfieldPeerMessage)
async def _handle_bitfield(pc: PeerClient, m: peer.BitfieldPeerMessage):
    b = Bitfield(int.from_bytes(m.bitfield, byteorder="big"))
    pc.peer.piecefield = b
    pc._logger.debug("Got bitfield message: {}".format(b))


@message_handler(peer.RequestPeerMessage)
async def _handle_request(pc: PeerClient, m: peer.RequestPeerMessage):
    pass


@message_handler(peer.BlockPeerMessage)
async def _handle_block(pc: PeerClient, m: peer.BlockPeerMessage):
    pass


@message_handler(peer.PortPeerMessage)
async def _handle_port(pc: PeerClient, m: peer.PortPeerMessage):
    pass


class Client:
    """
    Manages torrents and establishes connections to peers
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, peer_id: bytes, listen_port: int):
        self.loop = loop
        self.peer_id = peer_id
        self.listen_port = listen_port

        self._torrents: List[data.Torrent] = []
        self._logger = logging.getLogger("bridge.client")

        self._torrent_announce_tasks = []
        self._peer_clients = []
        self._peer_client_tasks = []

        self._server_task = loop.create_task(asyncio.start_server(self.on_incoming, port=listen_port, loop=loop))

    def add_torrent(self, torrent: data.Torrent, client_session: aiohttp.ClientSession):
        async def torrent_announce_loop():
            tr = tracker.TrackerRequest(client_session, torrent, self.peer_id, self.listen_port)

            while True:
                resp = await tr.announce(numwant=torrent.needed_peer_amount)
                torrent.insert_peers(resp.peers)
                await asyncio.sleep(resp.interval)

        self._torrent_announce_tasks.append(self.loop.create_task(torrent_announce_loop()))
        self._torrents.append(torrent)

    async def on_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Performs the proper connection initalization for incoming peer connections.
        """
        # Get connection data
        ip, port = writer.get_extra_info("socket").getpeername()
        # Wait for the handshake
        try:
            handshake = peer.HandshakeMessage.decode(await reader.read(49 + len(peer.PROTOCOL_STRING)))
        except UnicodeDecodeError:
            # There was an error decoding the handshake
            # (likly the handshake was invalid)
            self._logger.debug("Dropped connection with {}. (Invalid handshake)".format(ip))
            writer.close()
            return

        # Create a peer object to hold data
        remote_peer = peer.Peer.from_str(handshake.peer_id, ip, port)
        remote_peer.connected = True
        self._logger.debug("Incoming connection with peer [{}] requesting torrent {}".format(remote_peer, handshake.info_hash))

        # Handshake recieved, lets make sure we're serving the torrent
        torrent = next((t for t in self._torrents if t.meta.info_hash == handshake.info_hash), None)
        if torrent is None:
            # Sorry we don't have that in stock right now
            # Please come again
            self._logger.info(
                "Dropped connection with peer [{}]. (Don't have torrent {})".format(remote_peer, handshake.info_hash))
            writer.close()
            return

        # Make sure we don't have too many connections
        if len(torrent.swarm) >= peer.MAX_PEERS:
            # Torrent machine broke
            self._logger.debug(
                "Dropped connection with peer [{}]. (Reached MAX_PEERS)".format(remote_peer)
            )
            # Understandable have a nice day
            writer.close()
            return

        # Add the new peer to the list
        torrent.insert_peer(remote_peer)
        torrent.claim_peer(len(torrent.swarm) - 1)

        # Send our handshake
        writer.write(peer.HandshakeMessage(torrent.meta.info_hash, self.peer_id).encode())

        # It's customary to send a bitfield message right afterwards
        a = (len(torrent.pieces) - len(torrent.bitfield) - 1)
        padding = bytes([0] * int(math.floor(a / 8)))
        payload = bytes(torrent.bitfield) + padding
        self._logger.debug("Sending {} + {} NULL (size: {})".format(torrent.bitfield, len(padding), len(payload)))
        writer.write(peer.BitfieldPeerMessage(payload).encode())

        # Create a PeerClient to handle the rest of the connection
        pc = PeerClient(reader, writer, remote_peer, torrent)
        self._peer_clients.append(pc)
        self._peer_client_tasks.append(self.loop.create_task(pc.handle()))
