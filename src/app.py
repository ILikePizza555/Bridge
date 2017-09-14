from bridge import data, tracker, peer
import asyncio
import glob
import logging
import random

DEBUG = True

logger = logging.getLogger("bridge.app")
peer_id = tracker.generate_peer_id(debug=DEBUG)
listen_port = random.randrange(6881, 6889)


async def load_files() -> data.Torrent:
    torrent_list = glob.glob(".", "*.torrent")
    return [data.Torrent(f, peer_id, listen_port) for f in torrent_list]


async def start_app(loop: asyncio.AbstractEventLoop):
    logger.info("Starting app..")

    peer_manager = peer.PeerManager(loop)
    asyncio.start_server(peer_manager.on_incoming, port=listen_port, loop=loop)

    for t in await load_files():
        await t.announce()
        peer_manager.add_torrent(t)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    if DEBUG:
        loop.set_debug(DEBUG)
        logging.getLogger('asyncio').setLevel(logging.DEBUG)
    
    loop.create_task(start_app(loop))
    loop.run_forever()
