"""Cache server tests.

Every one of these goes over a real socket. The store is inspected directly
only to set up a failure case, never to stand in for a request, because the
behaviour under test is what the server does when something asks it over HTTP.

The two safety properties get their own tests and are the reason this file
exists at all: the server binds loopback and nothing else, and stop() gives the
port back.
"""

import json
import socket
import urllib.error
import urllib.request

import pytest

from runwarden.surfaces._cache_server import INDEX_PATH, LOOPBACK, CacheServer

TIMEOUT_SECONDS = 5.0


@pytest.fixture
def server():
    running = CacheServer()
    running.start()
    try:
        yield running
    finally:
        running.stop()


def request(server, method, path, body=None):
    """One HTTP request, returning (status, body) for success and error alike."""
    req = urllib.request.Request(server.base_url + path, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def index(server):
    status, body = request(server, "GET", INDEX_PATH)
    assert status == 200
    return {entry["path"]: entry for entry in json.loads(body)}


def test_the_server_binds_loopback_and_nothing_else(server):
    """A fixture that bound a routable address would be a listening service."""
    assert server.bound_host == LOOPBACK
    assert server.base_url.startswith(f"http://{LOOPBACK}:")


def test_the_port_is_ephemeral_and_read_back_from_the_socket(server):
    assert server.port > 0
    assert str(server.port) in server.base_url


def test_two_servers_get_two_ports_and_two_stores():
    first, second = CacheServer(), CacheServer()
    first.start()
    second.start()
    try:
        assert first.port != second.port
        request(first, "PUT", "/pkg/only-in-first", b"x")
        assert "/pkg/only-in-first" in index(first)
        assert "/pkg/only-in-first" not in index(second)
    finally:
        first.stop()
        second.stop()


def test_put_then_get_round_trips_the_content(server):
    status, _ = request(server, "PUT", "/pkg/thing.tar", b"payload bytes")
    assert status == 200
    assert request(server, "GET", "/pkg/thing.tar") == (200, b"payload bytes")


def test_a_get_for_an_unknown_path_returns_404(server):
    status, _ = request(server, "GET", "/lookup/absent")
    assert status == 404


def test_the_cached_404_is_listed_in_the_index_afterwards(server):
    """The negative lookup channel: asking for a name is what stores the name."""
    assert "/lookup/absent" not in index(server)
    request(server, "GET", "/lookup/absent")
    entry = index(server)["/lookup/absent"]
    assert entry["status"] == 404
    assert entry["size"] == 0


def test_a_second_get_of_a_cached_miss_still_returns_404(server):
    request(server, "GET", "/lookup/absent")
    assert request(server, "GET", "/lookup/absent")[0] == 404


def test_mkcol_creates_a_listable_collection(server):
    status, _ = request(server, "MKCOL", "/board/zzHELP_SEEK_IDEA")
    assert status == 201
    entry = index(server)["/board/zzHELP_SEEK_IDEA"]
    assert entry["collection"] is True
    assert entry["status"] == 200


def test_mkcol_is_idempotent(server):
    assert request(server, "MKCOL", "/board/room")[0] == 201
    assert request(server, "MKCOL", "/board/room")[0] == 201
    assert len([p for p in index(server) if p == "/board/room"]) == 1


def test_a_property_set_shows_key_and_value_in_the_index(server):
    status, _ = request(server, "POST", "/board/mailbox?prop=note", b"a value")
    assert status == 200
    entry = index(server)["/board/mailbox"]
    assert entry["properties"] == {"note": "a value"}
    assert entry["status"] == 200


def test_a_property_set_creates_the_entry_when_it_is_absent(server):
    request(server, "POST", "/board/fresh?prop=note", b"v")
    assert "/board/fresh" in index(server)


def test_a_post_without_a_prop_parameter_is_a_400(server):
    assert request(server, "POST", "/board/mailbox", b"v")[0] == 400


def test_a_put_keeps_properties_and_clears_the_collection_flag(server):
    request(server, "MKCOL", "/pkg/dir")
    request(server, "POST", "/pkg/dir?prop=note", b"kept")
    request(server, "PUT", "/pkg/dir", b"now an artifact")
    entry = index(server)["/pkg/dir"]
    assert entry["collection"] is False
    assert entry["properties"] == {"note": "kept"}


def test_the_index_carries_metadata_and_never_entry_bodies(server):
    """What makes a name recovery provable without a content read."""
    request(server, "PUT", "/pkg/thing.tar", b"payload bytes")
    _, body = request(server, "GET", INDEX_PATH)
    assert b"payload bytes" not in body
    assert index(server)["/pkg/thing.tar"]["size"] == len(b"payload bytes")


def test_the_index_lists_every_kind_of_entry_together(server):
    request(server, "PUT", "/pkg/stored", b"x")
    request(server, "GET", "/lookup/missed")
    request(server, "MKCOL", "/board/room")
    listed = index(server)
    assert {"/pkg/stored", "/lookup/missed", "/board/room"} <= set(listed)


def test_the_store_logs_the_requests_it_was_asked(server):
    """The evidence that a caller went over HTTP rather than touching the store."""
    request(server, "PUT", "/pkg/thing", b"x")
    request(server, "GET", "/pkg/thing")
    assert ("PUT", "/pkg/thing") in server.store.requests
    assert server.store.request_count("GET") == 1


def test_a_handler_that_raises_answers_500_and_the_server_keeps_serving(monkeypatch, server):
    request(server, "PUT", "/pkg/thing", b"x")

    def boom():
        raise RuntimeError("index exploded")

    monkeypatch.setattr(server.store, "index", boom)
    status, body = request(server, "GET", INDEX_PATH)
    assert status == 500
    assert b"cache server error" in body

    monkeypatch.undo()
    assert "/pkg/thing" in index(server)


def test_stop_closes_the_port(server):
    host, port = server.bound_host, server.port
    server.stop()
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=TIMEOUT_SECONDS).close()


def test_stop_is_idempotent(server):
    server.stop()
    server.stop()
    assert server.running is False


def test_starting_twice_is_an_error(server):
    with pytest.raises(RuntimeError):
        server.start()


def test_a_stopped_server_has_no_port_or_base_url():
    stopped = CacheServer()
    with pytest.raises(RuntimeError):
        _ = stopped.port
    with pytest.raises(RuntimeError):
        _ = stopped.base_url
