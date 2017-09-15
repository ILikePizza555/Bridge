from bridge import client, data, peer
from typing import List
import asyncio
import glob
import logging
import random
import traceback

DEBUG = True

logging_format = "[%(levelname)s]\t{%(asctime)s}\t%(name)s: %(message)s"
logging.basicConfig(filename="run.log", level=logging.INFO, format=logging_format)

bridge_logger = logging.getLogger("bridge")
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter("[%(name)s] - %(message)s"))
ch.setLevel(logging.INFO)
bridge_logger.addHandler(ch)

app_logger = logging.getLogger("bridge.app")
peer_id = peer.generate_peer_id(debug=DEBUG).encode()
listen_port = random.randrange(6881, 6889)


async def load_files() -> List[data.Torrent]:
    torrent_list = glob.glob("./*.torrent")
    return [data.Torrent(f) for f in torrent_list]


async def start_app(loop: asyncio.AbstractEventLoop):
    try:
        print("Starting app. Listening on port {}".format(listen_port))

        peer_client = client.Client(loop, peer_id, listen_port)

        for t in await load_files():
            app_logger.info("Adding torrent {}".format(t))
            await peer_client.add_torrent(t)

    except Exception:
        traceback.print_exc()
        app_logger.critical("Shutdown due to error.")
        loop.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    if DEBUG:
        loop.set_debug(DEBUG)
        logging.getLogger('asyncio').setLevel(logging.DEBUG)
    
    loop.create_task(start_app(loop))
    loop.run_forever()
