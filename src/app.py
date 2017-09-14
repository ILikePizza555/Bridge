from bridge import client, data, peer
import asyncio
import glob
import logging
import random

DEBUG = True


logging.basicConfig(filename="run.log", level=logging.INFO)


logger = logging.getLogger("bridge.app")
peer_id = peer.generate_peer_id(debug=DEBUG)
listen_port = random.randrange(6881, 6889)


async def load_files() -> data.Torrent:
    torrent_list = glob.glob("./*.torrent")
    return [data.Torrent(f, peer_id, listen_port) for f in torrent_list]


async def start_app(loop: asyncio.AbstractEventLoop):
    try:
        print("Starting app")

        peer_client = client.Client(loop)
        asyncio.start_server(peer_client.on_incoming, port=listen_port, loop=loop)

        for t in await load_files():
            logger.info("Adding torrent {}".format(t))

            await t.announce()
            peer_client.add_torrent(t)
    except Exception as e:
        logger.critical("Shutdown due to error.", exc_info=True, stack_info=True)
        loop.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    if DEBUG:
        loop.set_debug(DEBUG)
        logging.getLogger('asyncio').setLevel(logging.DEBUG)
    
    loop.create_task(start_app(loop))
    loop.run_forever()
