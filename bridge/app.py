from . import torrent, tracker
import asyncio
import random

peer_id = tracker.generate_peer_id(debug=True)
listen_port = random.randrange(6881, 6889)

if __name__ == "__main__":
    
