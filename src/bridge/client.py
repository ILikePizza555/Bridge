from . import data, peer
import asyncio
import logging


class Client():
    """
    Manages peers, the connections to those peers, and the messages from those peers
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, peer_id: bytes, listen_port: int):
        self.loop = loop
        self.peer_id = peer_id
        self.listen_port = listen_port

        self._torrents: list[data.Torrent] = []
        self._logger = logging.getLogger("bridge.peermanager")

        loop.create_task(asyncio.start_server(self.on_incoming, port=listen_port, loop=loop))

    async def add_torrent(self, torrent: data.Torrent):
        self._torrents.append(torrent)
        await torrent.announce(self.listen_port, self.peer_id)

    async def handle_peer(self, torrent: data.Torrent, remote_peer: peer.Peer,
                          reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Handles a peer client after proper initation procedures have been completed.
        """
        async for message in peer.PeerMessageIterator(reader):
            if type(message) == peer.KeepAlivePeerMessage:
                self._logger.debug("{}:{} <-- Keepalive".format(remote_peer.ip, remote_peer.port))
                writer.write(peer.KeepAlivePeerMessage().encode())

            message_string = "{}:{} --> {}".format(remote_peer.ip, remote_peer.port, message)
            print(message_string)
            self._logger.debug(message_string)

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
        self._logger.info("Incoming connection with peer [{}] requesting torrent {}".format(remote_peer, handshake.info_hash))

        # Handshake recieved, lets make sure we're serving the torrent
        torrent = next((t for t in self._torrents if t.data.info_hash == handshake.info_hash), None)
        if torrent is None:
            # Sorry we don't have that in stock right now
            # Please come again
            self._logger.info(
                "Dropped connection with peer [{}]. (Don't have torrent {})".format(remote_peer, handshake.info_hash))
            writer.close()
            return

        # Make sure we don't have too many connections
        if len(torrent.peers) >= peer.MAX_PEERS:
            # Torrent machine broke
            self._logger.info(
                "Dropped connection with peer [{}]. (Reached MAX_PEERS)".format(remote_peer)
            )
            # Understandable have a nice day
            writer.close()
            return

        # Remove any duplicate peers
        torrent.swarm = [p for p in torrent.swarm if p != remote_peer]
        # Add the new peer to the list
        torrent.peers.append(remote_peer)

        # Send our handshake
        writer.write(peer.HandshakeMessage(torrent.data.info_hash, self.peer_id).encode())

        self.loop.create_task(self.handle_peer(torrent, remote_peer, reader, writer))
