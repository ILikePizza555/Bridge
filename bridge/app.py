from . import torrent, tracker, peer
import asyncio
import logging
import random

DEBUG = True

peer_id = tracker.generate_peer_id(debug=DEBUG)
listen_port = random.randrange(6881, 6889)


async def start_app(loop: asyncio.AbstractEventLoop):
    pass


if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    if DEBUG:
        loop.set_debug(DEBUG)
        logging.getLogger('asyncio').setLevel(logging.DEBUG)
    
    loop.create_task(start_app())
    loop.run_forever()
