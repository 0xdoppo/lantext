# lantext

Lightweight LAN text channel. Zero dependencies — pure Python 3 stdlib.  
Port: **12345**

---

## Quick start

```bash
python3 lantext.py
```

Open the dashboard at `http://localhost:12345` (this machine) or the IP
printed in the terminal (other devices).

---

## Sending messages

**From the browser** — type in the input bar, hit SEND or press Enter.

**From terminal (same or another machine):**
```bash
python3 send.py "hello everyone"

# target a specific server
python3 send.py --server 192.168.1.42 "hey"

# set your display name
python3 send.py --name hal9000 "I'm afraid I can't do that"

# pipe stdin
echo "build done" | python3 send.py

# env vars instead of flags
export LANTEXT_SERVER=192.168.1.42
export LANTEXT_NAME=mypc
python3 send.py "message"
```

**Raw curl (no Python needed on sender):**
```bash
curl -X POST http://192.168.1.42:12345/send \
     -d "your message" -H "X-Sender: mypc"
```

---

## Connecting from other devices

Other machines on the same WiFi just open:
```
http://<server-ip>:12345
```

The server IP is printed at startup. Works on phones and tablets too —
the dashboard is fully responsive. On mobile, the **copy** button is
always visible, and you can also **long-press** any message to copy it.

---

## WSL setup (if running on Windows Subsystem for Linux)

WSL sits behind a Windows NAT. Your WSL IP (`172.x.x.x`) is not reachable
from other devices on your LAN. You need to forward the port through Windows.

### Step 1 — get your addresses

In WSL terminal:
```bash
hostname -I
# first result is your WSL IP, e.g. 172.30.201.49
```

In Windows PowerShell:
```powershell
ipconfig
# find "Wireless LAN adapter Wi-Fi" → IPv4 Address, e.g. 192.168.1.42
# this is what other devices on your LAN will connect to
```

### Step 2 — create the port proxy

Run in **PowerShell as Administrator** (replace the WSL IP with yours):

```powershell
netsh interface portproxy add v4tov4 `
  listenport=12345 listenaddress=0.0.0.0 `
  connectport=12345 connectaddress=172.30.201.49
```

### Step 3 — allow through Windows Firewall

Also in **PowerShell as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "lantext" `
  -Direction Inbound -Protocol TCP -LocalPort 12345 `
  -Action Allow -Profile Any
```

> `-Profile Any` is important — WiFi is often classified as "Public"
> which blocks rules without it.

### Step 4 — verify it's working

```powershell
# confirm the proxy exists
netsh interface portproxy show all

# confirm the firewall rule is enabled
Get-NetFirewallRule -DisplayName "lantext" | Select Enabled, Direction, Action

# test from Windows itself
curl http://localhost:12345
```

Other devices on your LAN now connect to your **Windows IP**:
```
http://192.168.1.42:12345
```

### WSL IP changes after reboot

WSL assigns a new IP on every reboot. When it stops working, run:

```bash
# in WSL — get new IP
hostname -I
```

```powershell
# in PowerShell (Admin) — delete old proxy and re-add with new IP
netsh interface portproxy delete v4tov4 listenport=12345 listenaddress=0.0.0.0

netsh interface portproxy add v4tov4 `
  listenport=12345 listenaddress=0.0.0.0 `
  connectport=12345 connectaddress=<new-wsl-ip>
```

The firewall rule doesn't need to be recreated — it's permanent until deleted.

### Clean up (remove everything)

```powershell
netsh interface portproxy delete v4tov4 listenport=12345 listenaddress=0.0.0.0
Remove-NetFirewallRule -DisplayName "lantext"
```

---

## Files

| File | Purpose |
|---|---|
| `lantext.py` | Server — run this on one machine |
| `send.py` | CLI sender — use from any machine |
| `README.md` | This file |

## Technical notes

- Uses **SSE** (Server-Sent Events) for real-time push — plain HTTP, no WebSocket
- `ThreadingHTTPServer` from stdlib — one thread per SSE client
- Holds last **500 messages** in memory (no disk, no database)
- New clients receive full history on connect
- Heartbeat ping every 25s keeps connections alive through routers
- Messages are lost when the server restarts (by design — it's a channel, not a log)
