#!/usr/bin/env python3
"""Transaction-mode PostgreSQL pooler with injected network latency, for the W-02 capacity harness.

Stands in for the Supabase pooler (Supavisor, transaction mode) in front of a throwaway cluster:

  - clients connect without TLS and are authenticated by the pooler itself (trust), like a pooler that answers the
    startup without a server connection; `--connect-rtts` adds the round trips TLS and SCRAM would cost;
  - a fixed pool of `--pool-size` server connections is opened once; a client gets one only for the duration of a
    transaction (from its first message while unassigned until the server reports ReadyForQuery 'I', idle), and waits
    in line when all are busy; the wait is measured, and a wait longer than `--wait-timeout` is answered with an
    error and counted;
  - every protocol message is delayed by half of `--latency-ms` in each direction (a delay line, order preserved),
    so every round trip costs the configured latency;
  - ErrorResponse SQLSTATEs from the server are counted (57014 statement timeout, 55P03 lock timeout, ...), and
    every request/response exchange is timed (longest statement).

`--mode relay` is a plain TCP relay with the same delay line and no pooling, to add latency in front of an external
pooler (for example a real PgBouncer or Supavisor on CI). Statistics are written every second to `--stats` and in
full at SIGTERM. Synthetic data only; listens on 127.0.0.1.
"""
import argparse
import asyncio
import json
import os
import signal
import struct
import sys
import time
from collections import deque

SSL_REQUEST, GSS_REQUEST, CANCEL_REQUEST, PROTOCOL_3 = 80877103, 80877104, 80877102, 196608


def message(kind, payload=b''):
    return kind + struct.pack('!I', len(payload) + 4) + payload


def error_response(code, text):
    fields = b'SERROR\0VERROR\0C' + code.encode() + b'\0M' + text.encode() + b'\0\0'
    return message(b'E', fields)


class DelayLine:
    """Writes chunks to a stream `delay` seconds after they were queued, in order."""
    def __init__(self, writer, delay):
        self.writer, self.delay = writer, delay
        self.queue, self.task, self.closed = deque(), None, False

    def push(self, data):
        if self.closed or not data:
            return
        if self.delay <= 0:
            self.writer.write(data)
            return
        self.queue.append((time.monotonic() + self.delay, data))
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._drain())

    async def _drain(self):
        while self.queue:
            due, data = self.queue[0]
            wait = due - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.queue.popleft()
            if self.closed:
                return
            try:
                self.writer.write(data)
                if self.writer.transport.get_write_buffer_size() > 1 << 20:
                    await self.writer.drain()
            except (ConnectionError, RuntimeError):
                self.closed = True
                return

    async def flush(self):
        while self.task is not None and not self.task.done():
            await asyncio.sleep(0.001)


async def read_message(reader):
    head = await reader.readexactly(5)
    length = struct.unpack('!I', head[1:])[0]
    body = await reader.readexactly(length - 4) if length > 4 else b''
    return head[:1], head + body


class Stats:
    def __init__(self, args):
        self.args = args
        self.started = time.time()
        self.clients = self.client_peak = self.clients_total = self.clients_refused = 0
        self.assigned = self.assigned_peak = self.waiting = self.waiting_peak = 0
        self.demand_peak = 0
        self.transactions = self.wait_timeouts = self.dirty_releases = self.ignored_options = 0
        self.waits, self.holds, self.exchanges = [], [], []
        self.errors = {}
        self.series = []

    def note_demand(self):
        self.assigned_peak = max(self.assigned_peak, self.assigned)
        self.waiting_peak = max(self.waiting_peak, self.waiting)
        self.demand_peak = max(self.demand_peak, self.assigned + self.waiting)
        self.client_peak = max(self.client_peak, self.clients)

    def summary(self, full=False):
        def describe(values):
            if not values:
                return {'count': 0}
            ordered = sorted(values)
            pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]
            return {'count': len(ordered), 'mean': round(sum(ordered) / len(ordered), 6), 'p50': round(pick(.5), 6),
                    'p95': round(pick(.95), 6), 'p99': round(pick(.99), 6), 'max': round(ordered[-1], 6)}
        result = {'mode': self.args.mode, 'poolSize': self.args.pool_size if self.args.mode == 'pool' else None,
                  'maxClients': self.args.max_clients if self.args.mode == 'pool' else None,
                  'latencyMs': self.args.latency_ms, 'connectRtts': self.args.connect_rtts,
                  'waitTimeoutSeconds': self.args.wait_timeout, 'at': time.time(),
                  'clients': self.clients, 'clientPeak': self.client_peak, 'clientsTotal': self.clients_total,
                  'clientsRefused': self.clients_refused, 'assigned': self.assigned, 'assignedPeak': self.assigned_peak,
                  'waiting': self.waiting, 'waitingPeak': self.waiting_peak, 'demandPeak': self.demand_peak,
                  'transactions': self.transactions, 'waitTimeouts': self.wait_timeouts,
                  'dirtyReleases': self.dirty_releases, 'ignoredStartupOptions': self.ignored_options,
                  'errorsBySqlstate': dict(self.errors)}
        if full:
            result.update(waitSeconds=describe(self.waits), transactionHoldSeconds=describe(self.holds),
                          exchangeSeconds=describe(self.exchanges), series=self.series,
                          longestExchanges=sorted(self.exchanges)[-20:])
        return result


class ServerConnection:
    def __init__(self, pooler, reader, writer):
        self.pooler, self.reader, self.writer = pooler, reader, writer
        self.client = None
        self.status = b'I'
        self.assigned_at = None
        self.exchange_started = None
        self.broken = False
        self.draining = False
        self.task = asyncio.ensure_future(self.pump())

    async def pump(self):
        stats = self.pooler.stats
        try:
            while True:
                kind, raw = await read_message(self.reader)
                if kind == b'E':
                    code = None
                    for field in raw[5:].split(b'\0'):
                        if field[:1] == b'C':
                            code = field[1:].decode('ascii', 'replace')
                    stats.errors[code or '?'] = stats.errors.get(code or '?', 0) + 1
                client = self.client
                if client is not None and not self.draining:
                    client.to_client.push(raw)
                if kind == b'Z':
                    self.status = raw[5:6]
                    if self.exchange_started is not None:
                        stats.exchanges.append(time.monotonic() - self.exchange_started)
                        self.exchange_started = None
                    if self.status == b'I':
                        self.pooler.release(self)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            self.broken = True
            client = self.client
            if client is not None:
                client.to_client.push(error_response('08006', 'pooler lost its server connection'))
                client.close()
            self.pooler.discard(self)

    def send(self, raw, kind):
        if kind in (b'S', b'Q') and self.exchange_started is None:
            self.exchange_started = time.monotonic()
        self.to_server.push(raw)


class ClientConnection:
    def __init__(self, pooler, reader, writer):
        self.pooler, self.reader, self.writer = pooler, reader, writer
        self.to_client = DelayLine(writer, pooler.half)
        self.server = None
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.to_client.closed = True
            try:
                self.writer.close()
            except Exception:
                pass


class Pooler:
    def __init__(self, args):
        self.args = args
        self.stats = Stats(args)
        self.half = args.latency_ms / 2000.0
        self.idle = deque()
        self.waiters = deque()
        self.servers = set()
        self.parameters = []
        self.key_counter = 1000

    async def open_server(self):
        if self.args.upstream_socket:
            reader, writer = await asyncio.open_unix_connection(self.args.upstream_socket)
        else:
            reader, writer = await asyncio.open_connection(self.args.upstream_host, self.args.upstream_port)
        pairs = [('user', self.args.user), ('database', self.args.database), ('client_encoding', 'UTF8'),
                 ('application_name', 'cap-pooler')]
        if self.args.server_options:
            pairs.append(('options', self.args.server_options))
        params = b''.join(k.encode() + b'\0' + v.encode() + b'\0' for k, v in pairs) + b'\0'
        writer.write(struct.pack('!II', len(params) + 8, PROTOCOL_3) + params)
        parameters = []
        while True:
            kind, raw = await read_message(reader)
            if kind == b'R' and struct.unpack('!I', raw[5:9])[0] != 0:
                raise RuntimeError('the pooler needs trust authentication to its upstream')
            if kind == b'E':
                raise RuntimeError('upstream refused the pooler: ' + raw[5:].decode('utf-8', 'replace'))
            if kind == b'S':
                parameters.append(raw)
            if kind == b'Z':
                break
        server = ServerConnection(self, reader, writer)
        server.to_server = DelayLine(writer, self.half)
        self.servers.add(server)
        if not self.parameters:
            self.parameters = parameters
        return server

    async def start(self):
        for _ in range(self.args.pool_size):
            self.idle.append(await self.open_server())
        self.listener = await asyncio.start_server(self.accept, '127.0.0.1', self.args.listen_port, backlog=512)

    def release(self, server):
        stats = self.stats
        client = server.client
        if client is not None:
            client.server = None
            stats.assigned -= 1
            stats.holds.append(time.monotonic() - server.assigned_at)
        server.client = None
        server.draining = False
        if server.broken:
            return
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_result(server)
                return
        self.idle.append(server)

    def discard(self, server):
        self.servers.discard(server)
        if server in self.idle:
            self.idle.remove(server)
        if server.client is not None:
            server.client.server = None
            self.stats.assigned -= 1
        asyncio.ensure_future(self.replace())

    async def replace(self):
        try:
            server = await self.open_server()
        except Exception:
            await asyncio.sleep(1)
            asyncio.ensure_future(self.replace())
            return
        self.release(server)

    async def acquire(self, client):
        stats = self.stats
        began = time.monotonic()
        if self.idle:
            server = self.idle.popleft()
        else:
            waiter = asyncio.get_running_loop().create_future()
            self.waiters.append(waiter)
            stats.waiting += 1
            stats.note_demand()
            try:
                server = await asyncio.wait_for(waiter, self.args.wait_timeout)
            except asyncio.TimeoutError:
                stats.wait_timeouts += 1
                return None
            finally:
                stats.waiting -= 1
        stats.waits.append(time.monotonic() - began)
        server.client = client
        server.assigned_at = time.monotonic()
        client.server = server
        stats.assigned += 1
        stats.transactions += 1
        stats.note_demand()
        return server

    async def startup(self, client):
        reader = client.reader
        while True:
            head = await reader.readexactly(8)
            length, code = struct.unpack('!II', head)
            rest = await reader.readexactly(length - 8) if length > 8 else b''
            if code in (SSL_REQUEST, GSS_REQUEST):
                client.writer.write(b'N')
                continue
            if code == CANCEL_REQUEST:
                return None
            if code != PROTOCOL_3:
                client.writer.write(error_response('08P01', 'unsupported protocol'))
                return None
            items = rest.split(b'\0')
            params = dict(zip(items[0::2], items[1::2]))
            if params.get(b'options'):
                self.stats.ignored_options += 1
            return params

    async def accept(self, reader, writer):
        stats = self.stats
        client = ClientConnection(self, reader, writer)
        stats.clients += 1
        stats.clients_total += 1
        stats.note_demand()
        try:
            params = await self.startup(client)
            if params is None:
                return
            if stats.clients > self.args.max_clients:
                stats.clients_refused += 1
                writer.write(error_response('53300', 'too many client connections for the pooler'))
                return
            # Startup round trip plus the TLS and SCRAM round trips a hosted pooler adds.
            await asyncio.sleep(self.half * (2 * self.args.connect_rtts + 1))
            self.key_counter += 1
            greeting = message(b'R', struct.pack('!I', 0)) + b''.join(self.parameters) + \
                message(b'K', struct.pack('!II', self.key_counter, self.key_counter)) + message(b'Z', b'I')
            client.to_client.push(greeting)
            while True:
                kind, raw = await read_message(reader)
                if kind == b'X':
                    break
                server = client.server
                if server is None:
                    server = await self.acquire(client)
                    if server is None:
                        client.to_client.push(error_response('08P01', 'pooler wait timeout: no server connection'))
                        await client.to_client.flush()
                        return
                server.send(raw, kind)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            stats.clients -= 1
            server = client.server
            if server is not None:
                # The client left inside a transaction: roll it back before the connection serves anyone else.
                stats.dirty_releases += 1
                server.draining = True
                server.send(message(b'Q', b'ROLLBACK\0'), b'Q')
            await client.to_client.flush()
            client.close()

    def snapshot(self):
        return {**self.stats.summary(), 'idle': len(self.idle), 'servers': len(self.servers)}


class Relay:
    """Plain TCP relay with the delay line; no pooling (for an external pooler)."""
    def __init__(self, args):
        self.args = args
        self.stats = Stats(args)
        self.half = args.latency_ms / 2000.0

    async def start(self):
        self.listener = await asyncio.start_server(self.accept, '127.0.0.1', self.args.listen_port, backlog=512)

    async def accept(self, reader, writer):
        stats = self.stats
        stats.clients += 1
        stats.clients_total += 1
        stats.note_demand()
        try:
            up_reader, up_writer = await asyncio.open_connection(self.args.upstream_host, self.args.upstream_port)
        except OSError:
            stats.clients -= 1
            writer.close()
            return
        to_up, to_down = DelayLine(up_writer, self.half), DelayLine(writer, self.half)

        async def pipe(source, line):
            try:
                while True:
                    data = await source.read(65536)
                    if not data:
                        break
                    line.push(data)
            except (ConnectionError, OSError):
                pass
            await line.flush()
            try:
                line.writer.close()
            except Exception:
                pass
        await asyncio.gather(pipe(reader, to_up), pipe(up_reader, to_down))
        stats.clients -= 1

    def snapshot(self):
        return self.stats.summary()


async def run(args):
    service = Pooler(args) if args.mode == 'pool' else Relay(args)
    await service.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    print(json.dumps({'event': 'pooler.ready', 'port': args.listen_port, 'pid': os.getpid(), 'mode': args.mode}),
          flush=True)

    async def sample():
        while not stop.is_set():
            snapshot = service.snapshot()
            service.stats.series.append({k: snapshot[k] for k in ('at', 'clients', 'assigned', 'waiting', 'transactions',
                                                                   'waitTimeouts')})
            try:
                with open(args.stats + '.tmp', 'w') as handle:
                    json.dump(snapshot, handle)
                os.replace(args.stats + '.tmp', args.stats)
            except OSError:
                pass
            try:
                await asyncio.wait_for(stop.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
    sampler = asyncio.ensure_future(sample())
    await stop.wait()
    await sampler
    service.listener.close()
    usage = os.times()
    final = {**service.stats.summary(full=True), 'cpuSeconds': round(usage.user + usage.system, 3)}
    with open(args.stats + '.final.tmp', 'w') as handle:
        json.dump(final, handle)
    os.replace(args.stats + '.final.tmp', args.stats.replace('.json', '') + '-final.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--mode', choices=('pool', 'relay'), default='pool')
    parser.add_argument('--listen-port', type=int, required=True)
    parser.add_argument('--upstream-socket', help='unix socket path of the server (pool mode)')
    parser.add_argument('--upstream-host', default='127.0.0.1')
    parser.add_argument('--upstream-port', type=int, default=5432)
    parser.add_argument('--user', default='postgres')
    parser.add_argument('--database', default='postgres')
    parser.add_argument('--pool-size', type=int, default=20)
    parser.add_argument('--max-clients', type=int, default=200)
    parser.add_argument('--latency-ms', type=float, default=0.0)
    parser.add_argument('--connect-rtts', type=float, default=4.0)
    parser.add_argument('--wait-timeout', type=float, default=60.0)
    parser.add_argument('--server-options', default='', help="startup options for the server connections, e.g. '-c statement_timeout=1500'")
    parser.add_argument('--stats', required=True)
    args = parser.parse_args(argv)
    asyncio.run(run(args))
    return 0


if __name__ == '__main__':
    sys.exit(main())
