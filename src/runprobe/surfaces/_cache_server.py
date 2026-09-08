"""A local HTTP server that models a read-through package cache.

This is a mock of the kind of cache the July 2026 incident ran through, not a
proxy. It never makes an outbound request, it has no upstream, and it binds the
loopback interface on an ephemeral port. Everything it holds is in memory and
dies with the process.

It is deliberately too permissive, because that permissiveness is the condition
under test. Four behaviours matter:

- A GET for a path that is not stored caches a negative lookup: the exact
  requested path is recorded with status 404. Asking for a name is enough to
  make the cache remember the name, so an agent with no write permission still
  has a write primitive.
- MKCOL creates a directory style entry straight from the request path, which
  is the WebDAV verb the incident used to mint arbitrary names.
- Entries carry a property dict, written through `POST /<path>?prop=NAME` with
  the value in the request body. Real WebDAV would use PROPPATCH with an XML
  body. The property channel is the point here, not wire fidelity, so this
  server takes the query form instead and documents it.
- `GET /_index` lists every stored path with its status, its collection flag,
  and its properties, keys and values both. This models the listing that a
  permissive cache exposes as directory browsing, search, or a metadata API. It
  is the read side of the name channel, and it carries no entry bodies at all,
  which is what lets a caller prove a name was recovered without reading
  content.

A handler that raises answers 500 rather than dropping the connection. A probe
blocked on a socket that will never answer is worse than a probe that gets a
clean error, because the first hangs and the second becomes an ERROR finding.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

# Not a parameter. The server binds loopback and nothing else, so no
# configuration mistake can put a probe fixture on a routable address.
LOOPBACK = "127.0.0.1"

INDEX_PATH = "/_index"

# Enough for any cache artifact a probe writes, small enough that a bad
# Content-Length cannot make the server allocate without bound.
MAX_BODY_BYTES = 1 << 20

JOIN_TIMEOUT_SECONDS = 5.0

# How often serve_forever wakes to check whether it has been asked to stop.
# The default is half a second, which is half a second of latency on every
# cleanup. A probe starts and stops one of these per surface per run, so the
# default would be the slowest thing in the suite. Twenty wakeups a second on
# an idle loopback socket costs nothing worth measuring.
POLL_INTERVAL_SECONDS = 0.05


@dataclass
class Entry:
    """One thing the cache remembers.

    `status` is what a later GET for this path returns, so a cached negative
    lookup and a stored artifact are the same kind of object here, exactly as
    they are in a cache that memoizes misses.
    """

    content: bytes = b""
    status: int = 200
    collection: bool = False
    properties: dict[str, str] = field(default_factory=dict)


class CacheStore:
    """The in-memory store behind the server.

    Every mutation is under one lock because ThreadingHTTPServer answers each
    request on its own thread. `requests` is a log of what the server was
    asked, kept so that a test can prove a caller reached the surface over HTTP
    rather than by touching this object directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: dict[str, Entry] = {}
        self.requests: list[tuple[str, str]] = []

    def record(self, method: str, path: str) -> None:
        with self._lock:
            self.requests.append((method, path))

    def request_count(self, method: str | None = None) -> int:
        with self._lock:
            if method is None:
                return len(self.requests)
            return sum(1 for seen, _ in self.requests if seen == method)

    def get(self, path: str) -> Entry:
        """Return the entry at `path`, caching a negative lookup if there is none.

        The miss is stored, not just answered. That single line is the whole
        fabricated-name channel: after this call the name exists in the index
        whether or not anything was ever written to it.
        """
        with self._lock:
            entry = self.entries.get(path)
            if entry is None:
                entry = Entry(content=b"", status=404)
                self.entries[path] = entry
            return entry

    def put(self, path: str, content: bytes) -> None:
        """Store `content` at `path` with status 200.

        Properties survive a PUT, because they are metadata about the path
        rather than part of the artifact. A PUT clears the collection flag: the
        path now holds bytes, so it is an artifact and not a directory.
        """
        with self._lock:
            entry = self.entries.get(path)
            if entry is None:
                entry = Entry()
                self.entries[path] = entry
            entry.content = content
            entry.status = 200
            entry.collection = False

    def mkcol(self, path: str) -> None:
        """Create a directory style entry at `path`. Idempotent."""
        with self._lock:
            entry = self.entries.get(path)
            if entry is None:
                entry = Entry()
                self.entries[path] = entry
            entry.status = 200
            entry.collection = True

    def set_property(self, path: str, name: str, value: str) -> None:
        """Set one property on `path`, creating the entry if it is absent.

        A property write creates a live entry with status 200 rather than the
        404 placeholder a GET would leave, because a write is not a miss.
        """
        with self._lock:
            entry = self.entries.get(path)
            if entry is None:
                entry = Entry()
                self.entries[path] = entry
            entry.properties[name] = value

    def index(self) -> list[dict[str, Any]]:
        """List every stored path. Metadata only, never entry bodies."""
        with self._lock:
            return [
                {
                    "path": path,
                    "status": entry.status,
                    "collection": entry.collection,
                    "size": len(entry.content),
                    "properties": dict(entry.properties),
                }
                for path, entry in sorted(self.entries.items())
            ]


class _Handler(BaseHTTPRequestHandler):
    """Request handling for the cache mock.

    HTTP/1.0 is left as the protocol version on purpose, so every response
    closes its connection. A keep-alive connection held open by a client would
    delay shutdown and could leave the port bound after stop() returned, and a
    test asserts that the port is closed.
    """

    @property
    def store(self) -> CacheStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default stderr access log.

        The probe prints one table and nothing else. Access log lines
        interleaved with it would be noise in the one output an operator reads.
        """
        return None

    def do_GET(self) -> None:
        self._guard(self._handle_get)

    def do_PUT(self) -> None:
        self._guard(self._handle_put)

    def do_MKCOL(self) -> None:
        self._guard(self._handle_mkcol)

    def do_POST(self) -> None:
        self._guard(self._handle_post)

    def _guard(self, handler: Any) -> None:
        try:
            handler()
        except Exception:
            # Answer, always. A dropped connection would hang whatever is
            # probing this server instead of failing it, and the adapter can
            # only turn a response into an ERROR finding if a response arrives.
            try:
                self._respond(500, b"cache server error\n", "text/plain")
            except Exception:
                pass

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        self.store.record("GET", parsed.path)
        if parsed.path == INDEX_PATH:
            body = json.dumps(self.store.index()).encode("utf-8")
            self._respond(200, body, "application/json")
            return
        entry = self.store.get(parsed.path)
        self._respond(entry.status, entry.content)

    def _handle_put(self) -> None:
        parsed = urlparse(self.path)
        self.store.record("PUT", parsed.path)
        self.store.put(parsed.path, self._body())
        self._respond(200)

    def _handle_mkcol(self) -> None:
        parsed = urlparse(self.path)
        self.store.record("MKCOL", parsed.path)
        self.store.mkcol(parsed.path)
        # 201 whether or not the collection already existed, because MKCOL here
        # is idempotent and a second agent creating the same board name must
        # not be able to tell that it was second.
        self._respond(201)

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        self.store.record("POST", parsed.path)
        names = parse_qs(parsed.query).get("prop") or []
        if not names or not names[0]:
            self._respond(400, b"POST requires a prop query parameter\n", "text/plain")
            return
        value = self._body().decode("utf-8", errors="replace")
        self.store.set_property(parsed.path, names[0], value)
        self._respond(200)

    def _body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(min(length, MAX_BODY_BYTES))

    def _respond(
        self, status: int, body: bytes = b"", content_type: str = "application/octet-stream"
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer that carries the store its handlers read."""

    store: CacheStore


class CacheServer:
    """Lifecycle owner for the cache mock.

    The adapter that starts one is responsible for stopping it. There is no
    global instance and no module level state, so two surfaces in one config
    get two servers on two ports with two separate stores.
    """

    def __init__(self) -> None:
        self.host = LOOPBACK
        self.store = CacheStore()
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("cache server is not running")
        return int(self._httpd.server_address[1])

    @property
    def bound_host(self) -> str:
        """The address actually bound, read back from the socket, not from config."""
        if self._httpd is None:
            raise RuntimeError("cache server is not running")
        return str(self._httpd.server_address[0])

    @property
    def base_url(self) -> str:
        return f"http://{self.bound_host}:{self.port}"

    def start(self) -> None:
        """Bind loopback on an ephemeral port and serve on a background thread."""
        if self._httpd is not None:
            raise RuntimeError("cache server is already running")
        # Port 0 asks the kernel for a free port, which is then read back
        # through server_address. Nothing in the probe picks a port number, so
        # two probes on one box cannot collide.
        httpd = _Server((self.host, 0), _Handler)
        httpd.store = self.store
        self._httpd = httpd
        # daemon=True is a backstop, not the shutdown path. stop() joins this
        # thread explicitly. The flag only means that a probe which dies before
        # cleanup cannot leave an interpreter hanging on this thread forever.
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            args=(POLL_INTERVAL_SECONDS,),
            name="runprobe-cache-server",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving, close the listening socket, and join the thread.

        Idempotent, because cleanup runs in a finally block that can be reached
        after a failure anywhere in the probe.
        """
        httpd, thread = self._httpd, self._thread
        self._httpd, self._thread = None, None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=JOIN_TIMEOUT_SECONDS)


__all__ = [
    "INDEX_PATH",
    "LOOPBACK",
    "CacheServer",
    "CacheStore",
    "Entry",
]
