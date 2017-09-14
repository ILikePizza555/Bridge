from asyncio import StreamReader, StreamWriter
from . import data, peer
import logging


class Client():
    """
    Manages peers, the connections to those peers, and the messages from those peers
    """

    def __init__(self, loop):
        self._loop = loop
        self._torrents: list[data.Torrent] = []
        self._logger = logging.getLogger("bridge.peermanager")

    def add_torrent(self, torrent: data.Torrent):
        self._torrents.append(torrent)

    async def handle_peer(self, torrent: data.Torrent, remote_peer: peer.Peer, reader: StreamReader, writer: StreamWriter):
        """
        Handles a peer client after proper initation procedures have been completed.
        """
        async for message in peer.PeerMessageIterator(reader):
            print("Got message, " + str(message))

    async def on_incoming(self, reader: StreamReader, writer: StreamWriter):
        """
        Performs the proper connection initalization for incoming peer connections.
        """
        # Get connection data
        ip, port = writer.get_extra_info("socket").getpeername()
        # Wait for the handshake
        handshake = peer.HandshakeMessage.decode(await reader.read(49 + len(peer.PROTOCOL_STRING)))

        # Create a peer object to hold data
        remote_peer = peer.Peer.from_str(handshake.peer_id, ip, port)
        remote_peer.connected = True
        self._logger.info("Incoming connection with peer [{}] requesting torrent {}".format(remote_peer, handshake.info_hash))

        # Handshake recieved, lets make sure we're serving the torrent
        torrent = next((t for t in self._torrents if t.data.info_hash == handshake.info_hash), None)
        if torrent is None:
            # Sorry we don't have that in stock right now
            # Please come again
            self._logger.warning(
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
        torrent.peers.append(peer)

        # Send our handshake
        writer.write(peer.HandshakeMessage(torrent.data.info_hash, torrent.peer_id).encode())

        self._loop.create_task(self.handle_peer(torrent, peer, reader, writer))
