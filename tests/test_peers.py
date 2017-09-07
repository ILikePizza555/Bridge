from bridge import peer
import asyncio
import pytest

_test_data = [
    (peer.KeepAlivePeerMessage(), bytes(4)),
    (peer.ChokePeerMessage(), bytes([0, 0, 0, 1, 0])),
    (peer.UnchokePeerMessage(), bytes([0, 0, 0, 1, 1])),
    (peer.InterestedPeerMessage(), bytes([0, 0, 0, 1, 2])),
    (peer.NotInterestedPeerMessage(), bytes([0, 0, 0, 1, 3])),
    (peer.HavePeerMessage(4), bytes([0, 0, 0, 5, 4, 0, 0, 0, 4])),
    (peer.BitfieldPeerMessage(bytes([1, 2, 3])), bytes([0, 0, 0, 4, 5, 1, 2, 3])),
    (peer.RequestPeerMessage(4, 5, 6), bytes([0, 0, 0, 13, 6, 0, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0, 6])),
    (peer.BlockPeerMessage(7, 8, b"abc"), bytes([0, 0, 0, 12, 7, 0, 0, 0, 7, 0, 0, 0, 8, 97, 98, 99])),
    (peer.CancelPeerMessage(9, 10, 11), bytes([0, 0, 0, 13, 8, 0, 0, 0, 9, 0, 0, 0, 10, 0, 0, 0, 11])),
    (peer.PortPeerMessage(128), bytes([0, 0, 0, 3, 9, 0, 128]))
]


@pytest.mark.parametrize("message,expected", [
    pytest.param(*_test_data[0], id="encode_keep_alive"),
    pytest.param(*_test_data[1], id="encode_choke"),
    pytest.param(*_test_data[2], id="encode_unchoke"),
    pytest.param(*_test_data[3], id="encode_interested"),
    pytest.param(*_test_data[4], id="encode_not_interested"),
    pytest.param(*_test_data[5], id="encode_have"),
    pytest.param(*_test_data[6], id="encode_bitfield"),
    pytest.param(*_test_data[7], id="encode_request"),
    pytest.param(*_test_data[8], id="encode_block"),
    pytest.param(*_test_data[9], id="encode_cancel"),
    pytest.param(*_test_data[10], id="encode_port")
])
def test_encoding(message: peer.PeerMessage, expected: bytes):
    assert message.encode() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("buffer_data,expected", [
    pytest.param(*_test_data[0][::-1], id="decode_keep_alive"),
    pytest.param(*_test_data[1][::-1], id="decode_choke"),
    pytest.param(*_test_data[2][::-1], id="decode_unchoke"),
    pytest.param(*_test_data[3][::-1], id="decode_interested"),
    pytest.param(*_test_data[4][::-1], id="decode_not_interested"),
    pytest.param(*_test_data[5][::-1], id="decode_have"),
    pytest.param(*_test_data[6][::-1], id="decode_bitfield"),
    pytest.param(*_test_data[7][::-1], id="decode_request"),
    pytest.param(*_test_data[8][::-1], id="decode_block"),
    pytest.param(*_test_data[9][::-1], id="decode_cancel"),
    pytest.param(*_test_data[10][::-1], id="decode_port")
])
async def test_single_stream_iteration(monkeypatch, buffer_data: bytes, expected: peer.PeerMessage):
    # Setting up mock tools
    mockbuffer = bytearray(buffer_data)

    async def mockread(b):
        if len(mockbuffer) == 0:
            raise StopAsyncIteration()

        data = bytes(mockbuffer[:b])
        del mockbuffer[:b]
        return data

    test_reader = asyncio.StreamReader()
    monkeypatch.setattr(test_reader, 'read', mockread)

    # Actual test
    async for message in peer.PeerMessageIterator(test_reader):
        assert message == expected
