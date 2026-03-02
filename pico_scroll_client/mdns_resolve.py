import socket
import struct

MDNS_ADDR = "224.0.0.251"
MDNS_PORT = 5353


def _encode_name(name):
    buf = b""
    for part in name.split("."):
        buf += bytes([len(part)]) + part.encode()
    buf += b"\x00"
    return buf


def _build_query(name):
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    question = _encode_name(name) + struct.pack(">HH", 1, 0x8001)
    return header + question


def _skip_name(data, offset):
    while offset < len(data):
        if data[offset] & 0xC0 == 0xC0:
            return offset + 2
        if data[offset] == 0:
            return offset + 1
        offset += data[offset] + 1
    return offset


def _parse_response(data):
    if len(data) < 12:
        return None

    qdcount = struct.unpack(">H", data[4:6])[0]
    ancount = struct.unpack(">H", data[6:8])[0]

    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(data, offset)
        offset += 4

    for _ in range(ancount):
        if offset >= len(data):
            break
        offset = _skip_name(data, offset)
        if offset + 10 > len(data):
            break

        rtype, rclass, ttl, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10

        if rtype == 1 and rdlength == 4 and offset + 4 <= len(data):
            return "{}.{}.{}.{}".format(
                data[offset], data[offset + 1], data[offset + 2], data[offset + 3]
            )

        offset += rdlength

    return None


def resolve(hostname, timeout=3):
    if not hostname.endswith(".local"):
        hostname += ".local"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        query = _build_query(hostname)
        sock.sendto(query, (MDNS_ADDR, MDNS_PORT))

        while True:
            try:
                data, addr = sock.recvfrom(512)
                ip = _parse_response(data)
                if ip:
                    return ip
            except OSError:
                break
    finally:
        sock.close()

    return None
