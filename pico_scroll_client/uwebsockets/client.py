import ubinascii
import ustruct
import urandom
import uasyncio as asyncio


class WebSocket:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer
        self._closed = False

    async def _read_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = await self._reader.read(n - len(data))
            if not chunk:
                raise OSError("connection closed")
            data += chunk
        return data

    async def _recv_frame(self):
        hdr = await self._read_exact(2)
        b1 = hdr[0]
        b2 = hdr[1]
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        length = b2 & 0x7F

        if length == 126:
            length = ustruct.unpack("!H", await self._read_exact(2))[0]
        elif length == 127:
            length = ustruct.unpack("!Q", await self._read_exact(8))[0]

        mask = b""
        if masked:
            mask = await self._read_exact(4)

        payload = await self._read_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        return opcode, payload

    async def recv(self):
        while True:
            opcode, payload = await self._recv_frame()
            if opcode == 0x1:
                return payload.decode("utf-8")
            if opcode == 0x8:
                await self.close()
                raise OSError("websocket closed")
            if opcode == 0x9:
                await self._send_frame(payload, opcode=0xA)

    async def _send_frame(self, payload, opcode=0x1):
        if self._closed:
            return
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        length = len(payload)
        header = bytearray()
        header.append(0x80 | opcode)

        if length <= 125:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(ustruct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(ustruct.pack("!Q", length))

        mask = bytes(urandom.getrandbits(8) for _ in range(4))
        masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

        self._writer.write(header)
        self._writer.write(mask)
        self._writer.write(masked_payload)
        await self._writer.drain()

    async def send(self, data):
        await self._send_frame(data, opcode=0x1)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            await self._send_frame(b"", opcode=0x8)
        finally:
            await self._writer.drain()
            self._writer.close()


def _parse_url(url):
    if not url.startswith("ws://"):
        raise ValueError("ws:// only")
    url = url[5:]

    path_start = url.find("/")
    if path_start == -1:
        host_port = url
        path = "/"
    else:
        host_port = url[:path_start]
        path = url[path_start:]

    if ":" in host_port:
        host, port_str = host_port.split(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 80

    return host, port, path


async def connect(url):
    host, port, path = _parse_url(url)
    reader, writer = await asyncio.open_connection(host, port)

    rand_bytes = bytes(urandom.getrandbits(8) for _ in range(16))
    key = ubinascii.b2a_base64(rand_bytes).strip()

    request = (
        "GET {path} HTTP/1.1\r\n"
        "Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).format(path=path, host=host, port=port, key=key.decode("utf-8"))

    writer.write(request.encode("utf-8"))
    await writer.drain()

    status_line = await reader.readline()
    if b"101" not in status_line:
        writer.close()
        raise OSError("websocket handshake failed")

    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break

    return WebSocket(reader, writer)
