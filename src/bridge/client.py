from . import data, peer, tracker
from typing import List
import asyncio
import aiohttp
import logging
import math


BLOCK_REQUEST_SIZE = 2**15  # Bytes


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
        self.logger = logging.getLogger("bridge.PeerClient.{}".format(p.peer_id))

        self.piece = None

    def __repr__(self):
        return "PeerClient to: {}:{}; for {}".format(self.peer.ip,
                                                     self.peer.port,
                                                     self.torrent.meta.info_hash)

    def respond(self) -> peer.PeerMessage:
        if not self.peer.is_interested:
            self.logger.debug("Sending interest to peer.")
            return peer.InterestedPeerMessage()

        if not self.peer.is_choking:
            if self.piece is None:
                # We have no piece, put in a request for one
                # TODO: This logic belongs in Torrent
                p_i = next(x for x in self.torrent.rare_pieces if self.peer.piecefield[x] != 0)
                self.piece = self.torrent.claim_piece(p_i)

                return peer.RequestPeerMessage(self.piece.piece_index, 0, BLOCK_REQUEST_SIZE)
            else:
                # TODO: This logic belongs in Piece
                return peer.RequestPeerMessage(self.piece.piece_index, len(self.piece.buffer), BLOCK_REQUEST_SIZE)

    async def handle(self):
        """
        Handles incoming peer messages and responds.
        """
        while True:
            async for message in await self.message_iter.load_generator():
                if type(message) == peer.KeepAlivePeerMessage:
                    self.writer.write(peer.KeepAlivePeerMessage().encode())

                try:
                    await message.handle(self)
                except NotImplementedError:
                    self.logger.warning("{} handler not implemented.".format(type(message)))

            response = self.respond()

            if response is not None:
                await self.writer.write(response.encode())

            await asyncio.sleep(0.01)


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
