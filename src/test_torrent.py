from torrent import Torrent, TorrentFile


def test_single_torrent_create():
    torrent = Torrent("test.torrent")

    assert torrent.filename == "test.torrent"
    assert torrent["info.name"] == b'ubuntu-17.04-desktop-amd64.iso'
    assert len(torrent.files) == 1
    assert torrent.files[0] == TorrentFile("", "ubuntu-17.04-desktop-amd64.iso", 1609039872)


def test_multi_torrent_create():
    torrent = Torrent("test2.torrent")

    assert torrent.filename == "test2.torrent"
    assert torrent["info.name"] == b'slackware64-14.2-iso'
    assert len(torrent.files) == 4
    assert torrent.files == (TorrentFile("", "slackware64-14.2-install-dvd.iso", 2773483520),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.asc", 181),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.md5", 67),
                             TorrentFile("", "slackware64-14.2-install-dvd.iso.txt", 202849))
