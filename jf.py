#!/usr/bin/env python3
"""Minimal JellyFish Lighting websocket client (stdlib only).
Usage: ./jf.py '<json>' [host]   e.g. ./jf.py '{"cmd":"toCtlrGet","get":[["zones"]]}'
"""
import base64, json, os, socket, struct, sys

def ws_send(host, msg, port=9000, timeout=5):
    s = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /ws HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    head, buf = buf.split(b"\r\n\r\n", 1)
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise RuntimeError(head.decode(errors="replace"))
    data = msg.encode(); mask = os.urandom(4); n = len(data)
    hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0xFE]) + struct.pack(">H", n) if n < 65536 else bytes([0xFF]) + struct.pack(">Q", n))
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def need(k):
        nonlocal buf
        while len(buf) < k:
            c = s.recv(65536)
            if not c: raise EOFError
            buf += c
        out, buf = buf[:k], buf[k:]; return out
    msg_parts = []
    while True:
        b0, b1 = need(2); ln = b1 & 0x7F
        if ln == 126: ln = struct.unpack(">H", need(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", need(8))[0]
        payload = need(ln); op = b0 & 0x0F
        if op in (0x1, 0x0): msg_parts.append(payload)
        if op == 0x8: break
        if b0 & 0x80 and op in (0x0, 0x1): break
    s.close()
    return b"".join(msg_parts).decode()

if __name__ == "__main__":
    host = sys.argv[2] if len(sys.argv) > 2 else "192.168.0.224"
    r = ws_send(host, sys.argv[1])
    try: print(json.dumps(json.loads(r), indent=2))
    except ValueError: print(r)
