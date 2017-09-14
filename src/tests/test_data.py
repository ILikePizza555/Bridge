from bridge.data import TorrentData, TorrentFile


def test_single_torrent_create():
    torrent = TorrentData("test.torrent")

    assert torrent.filename == "test.torrent"
    assert torrent["info.name"] == b'ubuntu-17.04-desktop-amd64.iso'

    assert len(torrent.announce) == 2
    assert len(torrent.announce[0]) == 1
    assert torrent.announce[0][0] == "http://torrent.ubuntu.com:6969/announce"
    assert len(torrent.announce[1]) == 1
    assert torrent.announce[1][0] == "http://ipv6.torrent.ubuntu.com:6969/announce"

    assert len(torrent.files) == 1
    assert torrent.files[0] == TorrentFile("", "ubuntu-17.04-desktop-amd64.iso", 1609039872)


def test_multi_torrent_create():
    torrent = TorrentData("test2.torrent")

    assert torrent.filename == "test2.torrent"
    assert torrent["info.name"] == b'slackware64-14.2-iso'

    assert len(torrent.announce) == 2
    assert len(torrent.announce[0]) == 3
    assert torrent.announce[0][0] == "http://tracker1.transamrit.net:8082/announce"
    assert torrent.announce[0][1] == "http://tracker2.transamrit.net:8082/announce"
    assert torrent.announce[0][2] == "http://tracker3.transamrit.net:8082/announce"
    assert len(torrent.announce[1]) == 1
    assert torrent.announce[1][0] == "http://linuxtracker.org:2710/00000000000000000000000000000000/announce"

    assert len(torrent.files) == 4
    assert torrent.files == (TorrentFile("", "slackware64-14.2-install-dvd.iso", 2773483520),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.asc", 181),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.md5", 67),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.txt", 202849))
