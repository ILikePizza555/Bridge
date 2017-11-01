from . import data, peer, tracker
from pizza_utils.bitfield import Bitfield
from typing import List
import asyncio
import aiohttp
import logging
import math


BLOCK_REQUEST_SIZE = 2**15


class PeerClient:
    """
    Represents a connection to a peer. Handles incoming messages and sends out messages.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 p: peer.Peer, torrent: data.Torrent):
        self.peer = p
        self.piece = None
        self.torrent = torrent
        self.writer = writer

        self.message_iter = peer.PeerMessageIterator(reader)
        self._logger = logging.getLogger("bridge.PeerClient.{}".format(p.peer_id))

    def __repr__(self):
        return "PeerClient to: {}:{}; for {}".format(self.peer.ip,
                                                     self.peer.port,
                                                     self.torrent.meta.info_hash)

    async def _handle_choke(self, m: peer.ChokePeerMessage):
        self._logger.debug("Got choke message.")
        self.peer.is_choking = True

    async def _handle_unchoke(self, m: peer.UnchokePeerMessage):
        self._logger.debug("Got unchoke message.")
        self.peer.is_choking = False

    async def _handle_interested(self, m: peer.InterestedPeerMessage):
        self._logger.debug("Got interested message.")
        self.peer.is_interested = True

    async def _handle_not_interested(self, m: peer.NotInterestedPeerMessage):
        self._logger.debug("Got not interested message.")
        self.peer.is_interested = False

    async def _handle_have(self, m: peer.HavePeerMessage):
        self._logger.debug("Got have message, piece {}.".format(m.piece_index))
        self.peer.piecefield[m.piece_index] = 1

    async def _handle_bitfield(self, m: peer.BitfieldPeerMessage):
        b = Bitfield(int.from_bytes(m.bitfield, byteorder="big"))
        self.peer.piecefield = b
        self._logger.debug("Got bitfield message: {}".format(b))

    async def _handle_request(self, m: peer.RequestPeerMessage):
        pass

    async def _handle_block(self, m: peer.BlockPeerMessage):
        if m.index == self.piece.piece_index:
            await self.piece.load(m.begin, m.block)

    async def _handle_port(self, m: peer.PortPeerMessage):
        pass

    async def respond(self):
        """Generator that returns messages."""
        while True:
            # Ensure the peer isn't choking us
            if self.peer.is_choking:
                yield peer.InterestedPeerMessage()
                break

            self.piece = self.torrent.claim_piece(self.peer.piecefield)

            while self.piece.state != data.Piece.State.SAVED:
                if self.piece.state == data.Piece.State.EMPTY:
                    # Continue downloaded the piece
                    yield peer.RequestPeerMessage(*self.piece.get_block(), BLOCK_REQUEST_SIZE)
                    continue
                elif self.piece.state == data.Piece.State.FULL:
                    if not await self.piece.verify():
                        # Piece did not verify, add it back to the pool & reset state machine
                        self.piece.reset()
                        break
                elif self.piece.state == data.Piece.State.VERIFIED:
                    torrent_file = self.torrent.find_file(self.piece)
                    await self.piece.save(torrent_file)

            self.torrent.return_piece(self.piece)
            self.piece = None

    async def handle(self):
        """
        Handles incoming peer messages and responds.
        """
        respond_sm = self.respond()

        while True:
            for message in await self.message_iter.load_iterator():
                if type(message) == peer.KeepAlivePeerMessage:
                    self.writer.write(peer.KeepAlivePeerMessage().encode())

                await {
                    peer.HavePeerMessage: self._handle_have,
                    peer.ChokePeerMessage: self._handle_choke,
                    peer.UnchokePeerMessage: self._handle_unchoke,
                    peer.InterestedPeerMessage: self._handle_interested,
                    peer.NotInterestedPeerMessage: self._handle_not_interested,
                    peer.BitfieldPeerMessage: self._handle_bitfield,
                    peer.RequestPeerMessage: self._handle_request,
                    peer.BlockPeerMessage: self._handle_block,
                    peer.PortPeerMessage: self._handle_port
                }[type(message)](message)

            # Send a response
            response = await respond_sm.asend()
            if response is not None:
                await self.writer.write(response.encode())

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
        async def torrent_announce_task():
            tr = tracker.TrackerRequest(client_session, torrent, self.peer_id, self.listen_port)

            while True:
                resp = await tr.announce()
                await asyncio.sleep(resp.interval)

        self._torrent_announce_tasks.append(self.loop.create_task(torrent_announce_task()))
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
        except UnicodeDecodeError or IndexError:
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
