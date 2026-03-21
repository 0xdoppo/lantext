#!/usr/bin/env python3
"""
send.py — lantext CLI sender
─────────────────────────────
Usage:
  python3 send.py "hello everyone"
  echo "hello" | python3 send.py
  python3 send.py --server 192.168.1.10 "message"
  python3 send.py --name mypc "message"

Environment vars (optional):
  LANTEXT_SERVER   server IP (default: localhost)
  LANTEXT_NAME     sender name (default: hostname)
"""

import sys
import os
import socket
import urllib.request
import urllib.error

# ── config ──
DEFAULT_SERVER = os.environ.get("LANTEXT_SERVER", "localhost")
DEFAULT_NAME   = os.environ.get("LANTEXT_NAME",   socket.gethostname())
PORT           = 12345

def send(text, server=DEFAULT_SERVER, name=DEFAULT_NAME):
    url  = f"http://{server}:{PORT}/send"
    data = text.strip().encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"X-Sender": name, "Content-Type": "text/plain"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except urllib.error.URLError as e:
        print(f"  ✗ error: {e.reason}", file=sys.stderr)
        return False

def main():
    args   = sys.argv[1:]
    server = DEFAULT_SERVER
    name   = DEFAULT_NAME

    # parse --server / --name flags
    filtered = []
    i = 0
    while i < len(args):
        if args[i] in ("--server", "-s") and i + 1 < len(args):
            server = args[i + 1]; i += 2
        elif args[i] in ("--name", "-n") and i + 1 < len(args):
            name = args[i + 1]; i += 2
        else:
            filtered.append(args[i]); i += 1

    if filtered:
        text = " ".join(filtered)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("Usage: python3 send.py \"your message\"", file=sys.stderr)
        sys.exit(1)

    text = text.strip()
    if not text:
        print("  ✗ empty message", file=sys.stderr)
        sys.exit(1)

    ok = send(text, server=server, name=name)
    if ok:
        print(f"  ✓ [{name}] → {text[:60]}{'…' if len(text)>60 else ''}")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
