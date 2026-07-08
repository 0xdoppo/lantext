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

## Private SSH tunnel access

If you do not want a public HTTP URL, keep `lantext` bound locally and
forward it through SSH. The browser still opens HTTP, but only on the
client machine's loopback address.

### Step 1 - create a client key

Run this on the client machine, for example a Mac:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/id_ed25519_lantext_client_mac \
  -C "lantext-client-mac" \
  -N ""
cat ~/.ssh/id_ed25519_lantext_client_mac.pub
```

Copy only the `.pub` line to the host. Do not copy the private key.

### Step 2 - authorize the client key on the host

On the machine running `lantext`, add the client public key to
`~/.ssh/authorized_keys`. To allow only the `lantext` port forward and no
normal shell, prefix the key like this:

```text
command="/bin/false",restrict,port-forwarding,permitopen="127.0.0.1:12345" ssh-ed25519 <client-public-key> lantext-client-mac
```

Make sure permissions are strict:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

### Step 3 - enable SSH on a WSL host

If the host is Debian in WSL, install and start SSH:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo service ssh start
```

Then forward a Windows LAN port to WSL SSH. Run PowerShell as
Administrator and replace the WSL IP with `hostname -I` from WSL:

```powershell
netsh interface portproxy add v4tov4 `
  listenport=2222 listenaddress=0.0.0.0 `
  connectport=22 connectaddress=172.30.201.49

New-NetFirewallRule -DisplayName "WSL SSH 2222" `
  -Direction Inbound -Protocol TCP -LocalPort 2222 `
  -Action Allow -Profile Any
```

### Step 4 - open the tunnel from the client

Use the Windows LAN IP, not the WSL IP. Example:

```bash
chmod 600 ~/.ssh/id_ed25519_lantext_client_mac

ssh -i ~/.ssh/id_ed25519_lantext_client_mac \
  -p 2222 \
  -N \
  -L 12345:127.0.0.1:12345 \
  fudgy@192.168.0.43
```

The SSH command normally prints nothing and keeps running. Leave that
terminal open, then browse on the client machine to:

```text
http://127.0.0.1:12345
```

Do not open `192.168.0.43:2222` in a browser. Port `2222` is SSH, so a
browser will only show an SSH banner such as `SSH-2.0-OpenSSH...`.

### Accessing from abroad

Addresses like `192.168.0.43` only work on the same LAN. For access from
outside the network, use one of these:

- Router port forwarding: forward an external TCP port to the Windows LAN
  IP on port `2222`, then SSH to your home public IP.
- A private mesh VPN such as Tailscale.
- A reverse SSH tunnel through a VPS.

With router forwarding in place, the client tunnel looks like:

```bash
ssh -i ~/.ssh/id_ed25519_lantext_client_mac \
  -p 2222 \
  -N \
  -L 12345:127.0.0.1:12345 \
  fudgy@<home-public-ip>
```

Then open `http://127.0.0.1:12345` on the client.

---

## Remote Codex command over SSH

You can also run Codex on the home PC from another machine by using SSH
as the transport. This is separate from the browser tunnel above because
it grants a stronger permission: the client can ask Codex to edit approved
projects on the host.

Do not shadow the real `codex` CLI on the client. Codex already uses `-p`
for profile and `-m` for model, so this repo uses a small wrapper named
`home-codex` instead:

```bash
home-codex -pc home_pc -p lantext -m "do some codex query"
```

### Step 1 - install the host dispatcher

On the home PC, install the forced-command dispatcher outside the repo:

```bash
mkdir -p ~/.local/bin
install -m 755 scripts/lantext-codex-ssh ~/.local/bin/lantext-codex-ssh
```

The dispatcher currently allows this project alias:

| Alias | Directory |
|---|---|
| `lantext` | `/home/fudgy/random/lantext` |

It runs:

```bash
codex exec -C /home/fudgy/random/lantext -s workspace-write -a never
```

The prompt is sent over stdin to avoid shell quoting problems.

### Step 2 - create a separate Codex SSH key

Use a different key from the `lantext` browser tunnel key. On the client:

```bash
ssh-keygen -t ed25519 \
  -f ~/.ssh/id_ed25519_home_codex_client \
  -C "home-codex-client-mac" \
  -N ""
cat ~/.ssh/id_ed25519_home_codex_client.pub
```

Copy only the `.pub` line to the host.

### Step 3 - authorize the Codex key on the host

Add the public key to `~/.ssh/authorized_keys` with a forced command:

```text
command="/home/fudgy/.local/bin/lantext-codex-ssh",restrict ssh-ed25519 <client-public-key> home-codex-client-mac
```

This key does not get a normal shell; every SSH command is routed through
`lantext-codex-ssh`.

### Step 4 - add a client SSH alias

On the client, add a host alias to `~/.ssh/config`:

```sshconfig
Host home_pc
  HostName 192.168.0.43
  User fudgy
  Port 2222
  IdentityFile ~/.ssh/id_ed25519_home_codex_client
  IdentitiesOnly yes
```

Use the current Windows LAN IP for `HostName`.

### Step 5 - install the client wrapper

If this repo is available on the client:

```bash
mkdir -p ~/.local/bin
install -m 755 scripts/home-codex ~/.local/bin/home-codex
```

Otherwise, the raw SSH command is:

```bash
ssh home_pc home-codex -p lantext -m "do some codex query"
```

The wrapper just turns this:

```bash
home-codex -pc home_pc -p lantext -m "do some codex query"
```

into the raw SSH command above.

---

## Files

| File | Purpose |
|---|---|
| `lantext.py` | Server — run this on one machine |
| `send.py` | CLI sender — use from any machine |
| `scripts/home-codex` | Client wrapper for remote Codex over SSH |
| `scripts/lantext-codex-ssh` | Host forced-command dispatcher for remote Codex |
| `README.md` | This file |

## Technical notes

- Uses **SSE** (Server-Sent Events) for real-time push — plain HTTP, no WebSocket
- `ThreadingHTTPServer` from stdlib — one thread per SSE client
- Holds last **500 messages** in memory (no disk, no database)
- New clients receive full history on connect
- Heartbeat ping every 25s keeps connections alive through routers
- Messages are lost when the server restarts (by design — it's a channel, not a log)
