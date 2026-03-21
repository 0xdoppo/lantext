#!/usr/bin/env python3
"""
lantext.py — lightweight LAN text channel
─────────────────────────────────────────
Start:   python3 lantext.py
Send:    python3 send.py "hello"
         curl -X POST http://<ip>:12345/send -d "hello" -H "X-Sender: mypc"
Dashboard: http://<your-ip>:12345
"""

import json
import queue
import socket
import threading
import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT     = 12345
MAX_MSGS = 500

messages    = []
subscribers = []
lock        = threading.Lock()

# ── broadcast to all SSE listeners ──────────────────────────────────────────

def broadcast(msg):
    data = f"data: {json.dumps(msg)}\n\n".encode()
    with lock:
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            subscribers.remove(q)

# ── HTML dashboard (embedded) ────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>lantext</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:      #0a0c0e;
    --surface: #0f1316;
    --border:  #1e2428;
    --border2: #2a3038;
    --dim:     #3a4450;
    --muted:   #5a6878;
    --text:    #c8d6e0;
    --bright:  #e8f4f8;
    --green:   #4ade80;
    --cyan:    #22d3ee;
    --red:     #f87171;
    --accent:  #38bdf8;
    --mono:    'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
    --safe-bottom: env(safe-area-inset-bottom, 0px);
  }

  html { height: 100%; }

  body {
    height: 100%;
    /* fix for mobile browsers where 100vh includes browser chrome */
    height: 100dvh;
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.6;
    overflow: hidden;
  }

  /* scanline overlay — disabled on mobile for perf */
  @media (min-width: 600px) {
    body::before {
      content: '';
      position: fixed; inset: 0;
      background: repeating-linear-gradient(
        0deg, transparent, transparent 2px,
        rgba(0,0,0,.07) 2px, rgba(0,0,0,.07) 4px
      );
      pointer-events: none;
      z-index: 999;
    }
  }

  /* ── layout ── */
  #app {
    display: flex;
    flex-direction: column;
    height: 100%;
    max-width: 960px;
    margin: 0 auto;
  }

  /* ── header ── */
  #header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  #logo {
    font-size: 14px;
    font-weight: 700;
    color: var(--bright);
    letter-spacing: .15em;
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 7px;
    white-space: nowrap;
  }
  #logo span { color: var(--accent); }

  #status-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 0;
  }
  #dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--dim);
    transition: background .4s;
    flex-shrink: 0;
  }
  #dot.ok  { background: var(--green); box-shadow: 0 0 6px var(--green); }
  #dot.err { background: var(--red);   box-shadow: 0 0 6px var(--red); }
  #status-txt {
    color: var(--muted);
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  #name-wrap { display: flex; align-items: center; gap: 6px; }
  #name-label { color: var(--muted); font-size: 11px; white-space: nowrap; }
  #name-input {
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: 3px;
    color: var(--cyan);
    font-family: var(--mono);
    font-size: 12px;
    padding: 4px 8px;
    width: 120px;
    outline: none;
    transition: border-color .2s;
    /* prevent iOS zoom on focus (font-size must be ≥16px or we set this) */
    font-size: max(12px, 16px);
  }
  #name-input:focus { border-color: var(--accent); }

  #msg-count { color: var(--dim); font-size: 11px; white-space: nowrap; }

  /* hide count on very small screens */
  @media (max-width: 380px) { #msg-count { display: none; } }

  /* ── messages ── */
  #feed {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 8px 0;
    scroll-behavior: smooth;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
  }
  #feed::-webkit-scrollbar { width: 4px; }
  #feed::-webkit-scrollbar-track { background: transparent; }
  #feed::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

  .msg {
    display: flex;
    align-items: flex-start;
    padding: 4px 14px;
    border-left: 2px solid transparent;
    transition: background .12s;
    cursor: default;
    /* larger tap target on mobile */
    min-height: 32px;
  }

  /* desktop: show copy on hover */
  @media (hover: hover) {
    .msg:hover {
      background: rgba(255,255,255,.025);
      border-left-color: var(--accent);
    }
    .msg:hover .copy-btn { opacity: 1; }
    .copy-btn { opacity: 0; }
  }

  /* mobile/touch: copy button always visible, smaller */
  @media (hover: none) {
    .copy-btn {
      opacity: 1 !important;
      font-size: 9px !important;
      padding: 0 4px !important;
      height: 16px !important;
    }
    .msg:active { background: rgba(255,255,255,.04); }
  }

  .ts {
    color: var(--dim);
    font-size: 11px;
    white-space: nowrap;
    padding-top: 1px;
    min-width: 58px;
    flex-shrink: 0;
  }
  @media (max-width: 400px) {
    /* show HH:MM only, drop seconds on small screens */
    .ts { min-width: 40px; }
  }

  .sender {
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
    padding: 0 8px 0 8px;
    font-size: 12px;
    max-width: 100px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @media (max-width: 400px) { .sender { max-width: 72px; } }

  .body {
    flex: 1;
    color: var(--bright);
    word-break: break-word;
    white-space: pre-wrap;
    line-height: 1.55;
    user-select: text;
    -webkit-user-select: text;
    min-width: 0;
  }

  .copy-btn {
    background: none;
    border: 1px solid var(--border2);
    border-radius: 2px;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 10px;
    padding: 0 5px;
    cursor: pointer;
    white-space: nowrap;
    margin-left: 8px;
    margin-top: 2px;
    flex-shrink: 0;
    transition: color .15s, border-color .15s;
    height: 18px;
    /* good touch target size */
    min-width: 36px;
    -webkit-tap-highlight-color: transparent;
  }
  .copy-btn:hover  { color: var(--bright); border-color: var(--accent); }
  .copy-btn:active { color: var(--bright); border-color: var(--accent); }
  .copy-btn.flash  { color: var(--green);  border-color: var(--green); }

  .day-divider {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px 6px;
    color: var(--dim);
    font-size: 10px;
    letter-spacing: .1em;
    text-transform: uppercase;
  }
  .day-divider::before, .day-divider::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
  }

  .sys-msg {
    padding: 2px 14px;
    color: var(--muted);
    font-size: 11px;
    font-style: italic;
  }

  /* ── input bar ── */
  #input-bar {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 10px 14px;
    padding-bottom: calc(10px + var(--safe-bottom));
    border-top: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
  }

  #prompt {
    color: var(--accent);
    padding-bottom: 8px;
    font-size: 14px;
    flex-shrink: 0;
    line-height: 1;
  }
  @media (max-width: 480px) { #prompt { display: none; } }

  #msg-input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border2);
    border-radius: 4px;
    color: var(--bright);
    font-family: var(--mono);
    /* ≥16px prevents iOS auto-zoom on focus */
    font-size: 16px;
    padding: 8px 10px;
    outline: none;
    transition: border-color .2s;
    resize: none;
    min-height: 38px;
    max-height: 120px;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    line-height: 1.4;
  }
  #msg-input:focus { border-color: var(--accent); }
  #msg-input::placeholder { color: var(--dim); }

  #send-btn {
    background: var(--accent);
    border: none;
    border-radius: 4px;
    color: #000;
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 700;
    /* minimum 44px touch target */
    min-width: 64px;
    min-height: 44px;
    padding: 0 16px;
    cursor: pointer;
    letter-spacing: .05em;
    transition: background .15s, transform .1s;
    flex-shrink: 0;
    -webkit-tap-highlight-color: transparent;
  }
  #send-btn:hover  { background: var(--cyan); }
  #send-btn:active { transform: scale(.96); background: var(--cyan); }

  /* sender colours */
  .c0{color:#38bdf8}.c1{color:#a78bfa}.c2{color:#34d399}
  .c3{color:#fb923c}.c4{color:#f472b6}.c5{color:#facc15}
  .c6{color:#22d3ee}.c7{color:#818cf8}

  @keyframes rowIn {
    from { opacity: 0; transform: translateX(-4px); }
    to   { opacity: 1; transform: translateX(0); }
  }
  .msg.new { animation: rowIn .18s ease; }
</style>
</head>
<body>
<div id="app">

  <div id="header">
    <div id="logo">&#9632; <span>LAN</span>TEXT</div>
    <div id="status-wrap">
      <div id="dot"></div>
      <span id="status-txt">connecting…</span>
    </div>
    <div id="name-wrap">
      <span id="name-label">you →</span>
      <input id="name-input" type="text" placeholder="your name" maxlength="20"
             autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
    </div>
    <span id="msg-count">0 msgs</span>
  </div>

  <div id="feed"></div>

  <div id="input-bar">
    <div id="prompt">&gt;</div>
    <textarea id="msg-input" rows="1"
              placeholder="message…"
              autocorrect="off" autocapitalize="sentences" spellcheck="true"></textarea>
    <button id="send-btn">SEND</button>
  </div>

</div>
<script>
(() => {
  const feed      = document.getElementById('feed');
  const input     = document.getElementById('msg-input');
  const sendBtn   = document.getElementById('send-btn');
  const nameInput = document.getElementById('name-input');
  const dot       = document.getElementById('dot');
  const statusTxt = document.getElementById('status-txt');
  const msgCount  = document.getElementById('msg-count');

  // ── detect touch device ──
  const isTouch = () => window.matchMedia('(hover: none)').matches;

  // ── clipboard: modern API with fallback for mobile ──
  function copyText(text, btn) {
    const finish = (ok) => {
      btn.textContent = ok ? 'copied!' : 'failed';
      btn.classList.toggle('flash', ok);
      setTimeout(() => {
        btn.textContent = 'copy';
        btn.classList.remove('flash');
      }, 1200);
    };

    // Modern clipboard API (works on HTTPS + localhost; blocked on plain HTTP mobile)
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => finish(true)).catch(() => fallback());
    } else {
      fallback();
    }

    function fallback() {
      // execCommand fallback — works on mobile browsers over plain HTTP
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        // iOS needs this extra step
        ta.setSelectionRange(0, ta.value.length);
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        finish(ok);
      } catch(e) {
        finish(false);
      }
    }
  }

  // ── sender colours ──
  const palette = {};
  let colIdx = 0;
  function colorFor(sender) {
    if (!palette[sender]) palette[sender] = `c${colIdx++ % 8}`;
    return palette[sender];
  }

  // ── name persistence ──
  nameInput.value = localStorage.getItem('lantext-name') || '';
  nameInput.addEventListener('change', () =>
    localStorage.setItem('lantext-name', nameInput.value.trim()));

  // ── auto-resize textarea ──
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  // ── message rendering ──
  let lastDate   = null;
  let totalCount = 0;

  function renderMsg(msg, isNew = false) {
    if (msg.date && msg.date !== lastDate) {
      lastDate = msg.date;
      const div = document.createElement('div');
      div.className = 'day-divider';
      div.textContent = msg.date;
      feed.appendChild(div);
    }

    const row = document.createElement('div');
    row.className = 'msg' + (isNew ? ' new' : '');

    // on touch: long-press row copies message body
    if (isTouch()) {
      let pressTimer;
      row.addEventListener('touchstart', () => {
        pressTimer = setTimeout(() => copyText(msg.text || '', btn), 600);
      }, { passive: true });
      row.addEventListener('touchend',   () => clearTimeout(pressTimer), { passive: true });
      row.addEventListener('touchmove',  () => clearTimeout(pressTimer), { passive: true });
    }

    const ts = document.createElement('span');
    ts.className = 'ts';
    // show HH:MM only on narrow screens
    const timeStr = msg.time || '';
    ts.textContent = timeStr;
    ts.title = msg.date + ' ' + timeStr;

    const sender = document.createElement('span');
    sender.className = 'sender ' + colorFor(msg.sender || '?');
    sender.textContent = (msg.sender || '?').substring(0, 16);

    const body = document.createElement('span');
    body.className = 'body';
    body.textContent = msg.text || '';

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'copy';
    btn.title = 'Copy message';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      copyText(msg.text || '', btn);
    });

    row.appendChild(ts);
    row.appendChild(sender);
    row.appendChild(body);
    row.appendChild(btn);
    feed.appendChild(row);

    totalCount++;
    msgCount.textContent = totalCount + ' msg' + (totalCount === 1 ? '' : 's');
  }

  function scrollBottom(force = false) {
    const thresh = 120;
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < thresh;
    if (atBottom || force) feed.scrollTop = feed.scrollHeight;
  }

  // ── SSE connection ──
  let es;
  function connect() {
    es = new EventSource('/events');

    es.addEventListener('open', () => {
      dot.className = 'ok';
      statusTxt.textContent = 'connected · ' + location.host;
    });

    es.addEventListener('message', (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'history') {
        msg.messages.forEach(m => renderMsg(m, false));
        scrollBottom(true);
      } else {
        renderMsg(msg, true);
        scrollBottom();
        if (!document.hasFocus()) {
          const old = document.title;
          document.title = '● ' + old;
          window.addEventListener('focus', () => { document.title = old; }, { once: true });
        }
      }
    });

    es.addEventListener('error', () => {
      dot.className = 'err';
      statusTxt.textContent = 'disconnected — retrying…';
      es.close();
      setTimeout(connect, 3000);
    });
  }
  connect();

  // ── send ──
  function getSender() {
    return nameInput.value.trim() || 'dashboard';
  }

  async function sendMsg() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = 'auto';

    // keep keyboard open on mobile after send
    if (!isTouch()) input.focus();

    try {
      await fetch('/send', {
        method: 'POST',
        headers: { 'X-Sender': getSender() },
        body: text
      });
    } catch(e) {
      const row = document.createElement('div');
      row.className = 'sys-msg';
      row.textContent = '⚠ send failed';
      feed.appendChild(row);
    }
  }

  sendBtn.addEventListener('click', sendMsg);

  input.addEventListener('keydown', (e) => {
    // desktop: Enter sends, Shift+Enter = newline
    // mobile: let Enter behave normally (soft keyboard return)
    if (e.key === 'Enter' && !e.shiftKey && !isTouch()) {
      e.preventDefault();
      sendMsg();
    }
  });

  // on mobile, Send button is the primary send path — works fine as-is
})();
</script>
</body>
</html>"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sender")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self._cors()
            self.end_headers()

            q = queue.Queue(maxsize=200)
            with lock:
                subscribers.append(q)
                history = list(messages)

            # send history as one synthetic event
            hist_event = f"data: {json.dumps({'type':'history','messages':history})}\n\n"
            try:
                self.wfile.write(hist_event.encode())
                self.wfile.flush()
            except BrokenPipeError:
                with lock:
                    if q in subscribers:
                        subscribers.remove(q)
                return

            # stream new messages + heartbeat
            while True:
                try:
                    data = q.get(timeout=25)
                    self.wfile.write(data)
                    self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, OSError):
                        break
                except (BrokenPipeError, OSError):
                    break

            with lock:
                if q in subscribers:
                    subscribers.remove(q)

        elif self.path == "/messages":
            with lock:
                body = json.dumps(messages).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/send":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length).decode("utf-8", errors="replace").strip()

            if body:
                sender = self.headers.get("X-Sender", "") or self.client_address[0]
                now    = datetime.datetime.now()
                msg    = {
                    "time":   now.strftime("%H:%M:%S"),
                    "date":   now.strftime("%Y-%m-%d"),
                    "sender": sender[:32],
                    "text":   body,
                }
                with lock:
                    messages.append(msg)
                    if len(messages) > MAX_MSGS:
                        messages.pop(0)
                broadcast(msg)
                resp = b"ok"
            else:
                resp = b"empty"

            self.send_response(200)
            self.send_header("Content-Length", str(len(resp)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        # suppress per-request noise; show only startup info
        pass

# ── main ──────────────────────────────────────────────────────────────────────

def get_local_ip():
    """Get the real outbound IP — works on WSL, Linux, Mac."""
    try:
        # UDP connect doesn't send packets; just reveals which interface the OS would use
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    local_ip = get_local_ip()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True

    print(f"""
  ██╗      █████╗ ███╗   ██╗████████╗███████╗██╗  ██╗████████╗
  ██║     ██╔══██╗████╗  ██║╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝
  ██║     ███████║██╔██╗ ██║   ██║   █████╗   ╚███╔╝    ██║   
  ██║     ██╔══██║██║╚██╗██║   ██║   ██╔══╝   ██╔██╗    ██║   
  ███████╗██║  ██║██║ ╚████║   ██║   ███████╗██╔╝ ██╗   ██║   
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝   
  lightweight local network text channel · port {PORT}
  ──────────────────────────────────────────────
  Dashboard  →  http://localhost:{PORT}  (this machine)
               http://{local_ip}:{PORT}  (other devices)
  Send (CLI) →  python3 send.py "your message"
  Send (curl)→  curl -X POST http://{local_ip}:{PORT}/send \\
                     -d "hello" -H "X-Sender: mypc"
  ──────────────────────────────────────────────
  Ctrl+C to stop
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  lantext stopped.")
        server.server_close()
