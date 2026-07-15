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
import mimetypes
import urllib.parse
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT     = 12345
MAX_MSGS = 500
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

messages    = []
files       = {}
subscribers = []
lock        = threading.Lock()

# ── message/file helpers ─────────────────────────────────────────────────────

def prune_messages():
    while len(messages) > MAX_MSGS:
        old = messages.pop(0)
        for att in old.get("attachments", []):
            file_id = att.get("id")
            if file_id:
                files.pop(file_id, None)


def make_message(sender, text="", attachments=None):
    now = datetime.datetime.now()
    return {
        "time":        now.strftime("%H:%M:%S"),
        "date":        now.strftime("%Y-%m-%d"),
        "sender":      sender[:32],
        "text":        text,
        "attachments": attachments or [],
    }


def add_message(msg):
    with lock:
        messages.append(msg)
        prune_messages()
    broadcast(msg)


def safe_filename(name):
    name = (name or "file").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:160] or "file"


def parse_multipart(headers, body):
    content_type = headers.get("Content-Type", "")
    raw = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    form = BytesParser(policy=email_policy).parsebytes(raw)
    if not form.is_multipart():
        raise ValueError("expected multipart/form-data")

    text = ""
    upload_parts = []
    for part in form.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue

        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if name == "text" and not filename:
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace").strip()
        elif name == "file" and filename and payload:
            clean_name = safe_filename(filename)
            mime = part.get_content_type() or mimetypes.guess_type(clean_name)[0]
            if not mime or mime == "application/octet-stream":
                mime = mimetypes.guess_type(clean_name)[0] or "application/octet-stream"
            upload_parts.append({
                "name": clean_name,
                "mime": mime,
                "data": payload,
                "size": len(payload),
            })

    return text, upload_parts


def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler._cors()
    handler.end_headers()
    handler.wfile.write(body)

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

  #nav-actions {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .nav-btn {
    width: 28px;
    height: 28px;
    border: 1px solid var(--border2);
    border-radius: 3px;
    background: var(--bg);
    color: var(--muted);
    font-family: var(--mono);
    font-size: 14px;
    cursor: pointer;
  }
  .nav-btn:hover { color: var(--bright); border-color: var(--accent); }

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

  #drop-overlay {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 1000;
    align-items: center;
    justify-content: center;
    background: rgba(10, 12, 14, .78);
    border: 2px dashed var(--accent);
    color: var(--bright);
    font-size: 16px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    pointer-events: none;
  }
  body.dragging-files #drop-overlay {
    display: flex;
  }

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
  .msg.menu-open {
    background: rgba(255,255,255,.035);
    border-left-color: var(--accent);
  }

  /* desktop: show copy on hover */
  @media (hover: hover) {
    .msg:hover {
      background: rgba(255,255,255,.025);
      border-left-color: var(--accent);
    }
    .msg:hover .copy-btn, .msg:hover .collapse-btn { opacity: 1; }
    .copy-btn, .collapse-btn { opacity: 0; }
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
    .collapse-btn {
      opacity: 1 !important;
      font-size: 11px !important;
      padding: 0 4px !important;
      height: 16px !important;
      min-width: 24px !important;
    }
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

  .content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

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

  .body:empty { display: none; }

  .collapsed-summary {
    display: none;
    color: var(--muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .msg.collapsed .body,
  .msg.collapsed .attachments { display: none; }
  .msg.collapsed .collapsed-summary { display: block; }

  .attachments {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: min(100%, 560px);
  }
  .attachment {
    border: 1px solid var(--border2);
    border-radius: 4px;
    background: rgba(255,255,255,.02);
    overflow: hidden;
  }
  .image-attachment a { display: block; }
  .image-attachment img {
    display: block;
    width: 100%;
    max-height: 360px;
    object-fit: contain;
    background: #050607;
  }
  .attachment-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 6px 8px;
    color: var(--muted);
    font-size: 11px;
    border-top: 1px solid var(--border);
  }
  .attachment-meta span:first-child,
  .file-attachment a span:first-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .file-attachment a {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px;
    color: var(--bright);
    text-decoration: none;
  }
  .file-attachment a:hover { color: var(--cyan); }
  .file-size { color: var(--muted); white-space: nowrap; }

  .copy-btn, .collapse-btn {
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
  .copy-btn:active, .collapse-btn:active { color: var(--bright); border-color: var(--accent); }
  .copy-btn.flash  { color: var(--green);  border-color: var(--green); }
  .collapse-btn { min-width: 24px; }
  .collapse-btn:hover { color: var(--bright); border-color: var(--accent); }

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

  #ctx-menu {
    display: none;
    position: fixed;
    z-index: 1001;
    min-width: 180px;
    padding: 4px;
    border: 1px solid var(--border2);
    border-radius: 4px;
    background: #080a0c;
    box-shadow: 0 10px 30px rgba(0,0,0,.4);
  }
  #ctx-menu.open {
    display: block;
  }
  #ctx-menu button {
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 30px;
    padding: 6px 8px;
    border: 0;
    border-radius: 3px;
    background: transparent;
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    text-align: left;
    cursor: pointer;
  }
  #ctx-menu button:hover,
  #ctx-menu button:focus {
    background: rgba(56,189,248,.12);
    color: var(--bright);
    outline: none;
  }
  #ctx-menu button[disabled] {
    color: var(--dim);
    cursor: default;
  }
  #ctx-menu button[disabled]:hover {
    background: transparent;
  }
  .ctx-sep {
    height: 1px;
    margin: 4px 2px;
    background: var(--border);
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
    flex-wrap: wrap;
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

  #file-tray {
    flex-basis: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  #file-tray[hidden] { display: none; }
  .file-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    border: 1px solid var(--border2);
    border-radius: 3px;
    background: var(--bg);
    color: var(--text);
    padding: 4px 6px;
    font-size: 11px;
  }
  .file-chip span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-chip button {
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
  }
  #attach-btn {
    width: 44px;
    min-width: 44px;
    height: 44px;
    border: 1px solid var(--border2);
    border-radius: 4px;
    background: var(--bg);
    color: var(--accent);
    font-family: var(--mono);
    font-size: 18px;
    cursor: pointer;
  }
  #attach-btn:hover { border-color: var(--accent); color: var(--cyan); }

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
  #send-btn:disabled, #attach-btn:disabled { opacity: .45; cursor: wait; }
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
    <div id="nav-actions">
      <button class="nav-btn" id="top-btn" title="Go to top" aria-label="Go to top">↑</button>
      <button class="nav-btn" id="bottom-btn" title="Go to bottom" aria-label="Go to bottom">↓</button>
    </div>
  </div>

  <div id="feed"></div>
  <div id="drop-overlay">Drop files to attach</div>
  <div id="ctx-menu" role="menu" aria-hidden="true"></div>

  <div id="input-bar">
    <div id="file-tray" hidden></div>
    <div id="prompt">&gt;</div>
    <input id="file-input" type="file" multiple hidden>
    <button id="attach-btn" title="Attach files" aria-label="Attach files">+</button>
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
  const attachBtn = document.getElementById('attach-btn');
  const fileInput = document.getElementById('file-input');
  const fileTray  = document.getElementById('file-tray');
  const dropOverlay = document.getElementById('drop-overlay');
  const ctxMenu   = document.getElementById('ctx-menu');
  const nameInput = document.getElementById('name-input');
  const dot       = document.getElementById('dot');
  const statusTxt = document.getElementById('status-txt');
  const msgCount  = document.getElementById('msg-count');
  const topBtn    = document.getElementById('top-btn');
  const bottomBtn = document.getElementById('bottom-btn');

  // ── detect touch device ──
  const isTouch = () => window.matchMedia('(hover: none)').matches;

  // ── clipboard: modern API with fallback for mobile ──
  function copyText(text, btn, restoreText) {
    const originalText = restoreText || btn.textContent || 'copy';
    const finish = (ok) => {
      btn.textContent = ok ? 'copied!' : 'failed';
      btn.classList.toggle('flash', ok);
      setTimeout(() => {
        btn.textContent = originalText;
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

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let idx = 0;
    while (size >= 1024 && idx < units.length - 1) {
      size /= 1024;
      idx++;
    }
    return (idx === 0 ? size : size.toFixed(size >= 10 ? 0 : 1)) + ' ' + units[idx];
  }

  function messageCopyText(msg) {
    const parts = [];
    if (msg.text) parts.push(msg.text);
    (msg.attachments || []).forEach(att => {
      parts.push(`${att.name} ${location.origin}${att.url}`);
    });
    return parts.join('\n');
  }

  let selectedFiles = [];
  function renderFileTray() {
    fileTray.replaceChildren();
    fileTray.hidden = selectedFiles.length === 0;
    selectedFiles.forEach((file, idx) => {
      const chip = document.createElement('div');
      chip.className = 'file-chip';
      const label = document.createElement('span');
      label.textContent = `${file.name} · ${formatBytes(file.size)}`;
      label.title = file.name;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.title = 'Remove file';
      remove.addEventListener('click', () => {
        selectedFiles.splice(idx, 1);
        renderFileTray();
      });
      chip.appendChild(label);
      chip.appendChild(remove);
      fileTray.appendChild(chip);
    });
  }

  function addFiles(files) {
    const incoming = Array.from(files || []).filter(file => file && file.size > 0);
    if (!incoming.length) return;
    selectedFiles = selectedFiles.concat(incoming);
    renderFileTray();
  }

  attachBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    addFiles(fileInput.files);
    fileInput.value = '';
  });

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

  function renderAttachments(attachments) {
    if (!attachments || !attachments.length) return null;
    const wrap = document.createElement('div');
    wrap.className = 'attachments';

    attachments.forEach(att => {
      const item = document.createElement('div');
      item.className = 'attachment ' + (att.isImage ? 'image-attachment' : 'file-attachment');

      if (att.isImage) {
        const link = document.createElement('a');
        link.href = att.url;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = att.url;
        img.alt = att.name;
        img.loading = 'lazy';
        link.appendChild(img);
        item.appendChild(link);
      } else {
        const link = document.createElement('a');
        link.href = att.url;
        link.download = att.name;
        const name = document.createElement('span');
        name.textContent = att.name;
        const size = document.createElement('span');
        size.className = 'file-size';
        size.textContent = formatBytes(att.size);
        link.appendChild(name);
        link.appendChild(size);
        item.appendChild(link);
      }

      const meta = document.createElement('div');
      meta.className = 'attachment-meta';
      const label = document.createElement('span');
      label.textContent = att.name;
      label.title = att.name;
      const size = document.createElement('span');
      size.textContent = formatBytes(att.size);
      meta.appendChild(label);
      meta.appendChild(size);
      if (att.isImage) item.appendChild(meta);

      wrap.appendChild(item);
    });
    return wrap;
  }

  function summaryFor(msg) {
    const parts = [];
    const text = (msg.text || '').replace(/\s+/g, ' ').trim();
    if (text) parts.push(text.length > 90 ? text.slice(0, 90) + '…' : text);
    const count = (msg.attachments || []).length;
    if (count) parts.push(count + ' file' + (count === 1 ? '' : 's'));
    return parts.join(' · ') || '(empty)';
  }

  function saveAttachment(att) {
    const link = document.createElement('a');
    link.href = att.url;
    link.download = att.name || 'lantext-file';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function saveAttachments(attachments) {
    attachments.forEach((att, idx) => {
      setTimeout(() => saveAttachment(att), idx * 80);
    });
  }

  function setCollapsed(row, collapseBtn, collapsed) {
    row.classList.toggle('collapsed', collapsed);
    collapseBtn.textContent = collapsed ? '+' : '−';
    collapseBtn.title = collapsed ? 'Expand message' : 'Collapse message';
    collapseBtn.setAttribute('aria-label', collapseBtn.title);
  }

  function toggleCollapsed(row, collapseBtn) {
    setCollapsed(row, collapseBtn, !row.classList.contains('collapsed'));
  }

  let activeMenuRow = null;

  function closeContextMenu() {
    ctxMenu.classList.remove('open');
    ctxMenu.setAttribute('aria-hidden', 'true');
    ctxMenu.replaceChildren();
    if (activeMenuRow) activeMenuRow.classList.remove('menu-open');
    activeMenuRow = null;
  }

  function menuButton(label, handler, disabled = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.disabled = disabled;
    if (!disabled) {
      button.addEventListener('click', (e) => {
        e.stopPropagation();
        handler(button);
      });
    }
    return button;
  }

  function menuSeparator() {
    const sep = document.createElement('div');
    sep.className = 'ctx-sep';
    return sep;
  }

  function showContextMenu(e, msg, row, collapseBtn) {
    e.preventDefault();
    closeContextMenu();

    const attachments = msg.attachments || [];
    const collapsed = row.classList.contains('collapsed');
    const saveLabel = attachments.length === 0
      ? 'Save attachment'
      : attachments.length === 1
        ? 'Save ' + (attachments[0].isImage ? 'image' : 'file')
        : 'Save all files';

    ctxMenu.appendChild(menuButton(saveLabel, () => {
      saveAttachments(attachments);
      closeContextMenu();
    }, attachments.length === 0));
    ctxMenu.appendChild(menuButton('Copy message', (button) => {
      copyText(messageCopyText(msg), button, 'Copy message');
    }));
    ctxMenu.appendChild(menuSeparator());
    ctxMenu.appendChild(menuButton(collapsed ? 'Expand message' : 'Collapse message', () => {
      toggleCollapsed(row, collapseBtn);
      closeContextMenu();
    }));

    row.classList.add('menu-open');
    activeMenuRow = row;
    ctxMenu.classList.add('open');
    ctxMenu.setAttribute('aria-hidden', 'false');
    ctxMenu.style.left = '0px';
    ctxMenu.style.top = '0px';
    const rect = ctxMenu.getBoundingClientRect();
    const left = Math.max(8, Math.min(e.clientX, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(e.clientY, window.innerHeight - rect.height - 8));
    ctxMenu.style.left = left + 'px';
    ctxMenu.style.top = top + 'px';
  }

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
        pressTimer = setTimeout(() => copyText(messageCopyText(msg), btn), 600);
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

    const content = document.createElement('div');
    content.className = 'content';

    const body = document.createElement('span');
    body.className = 'body';
    body.textContent = msg.text || '';

    const summary = document.createElement('span');
    summary.className = 'collapsed-summary';
    summary.textContent = summaryFor(msg);

    content.appendChild(body);
    const attachments = renderAttachments(msg.attachments);
    if (attachments) content.appendChild(attachments);
    content.appendChild(summary);

    const collapseBtn = document.createElement('button');
    collapseBtn.className = 'collapse-btn';
    collapseBtn.textContent = '−';
    collapseBtn.title = 'Collapse message';

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'copy';
    btn.title = 'Copy message';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      copyText(messageCopyText(msg), btn);
    });

    collapseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleCollapsed(row, collapseBtn);
    });
    collapseBtn.setAttribute('aria-label', 'Collapse message');

    row.appendChild(ts);
    row.appendChild(sender);
    row.appendChild(content);
    row.appendChild(collapseBtn);
    row.appendChild(btn);
    feed.appendChild(row);

    row.addEventListener('contextmenu', (e) => showContextMenu(e, msg, row, collapseBtn));

    totalCount++;
    msgCount.textContent = totalCount + ' msg' + (totalCount === 1 ? '' : 's');
  }

  function scrollBottom(force = false) {
    const thresh = 120;
    const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < thresh;
    if (atBottom || force) feed.scrollTop = feed.scrollHeight;
  }

  topBtn.addEventListener('click', () => feed.scrollTo({ top: 0, behavior: 'smooth' }));
  bottomBtn.addEventListener('click', () => scrollBottom(true));

  // ── drag/drop files ──
  let dragDepth = 0;
  function hasDraggedFiles(dt) {
    return dt && Array.from(dt.types || []).includes('Files');
  }

  window.addEventListener('dragenter', (e) => {
    if (!hasDraggedFiles(e.dataTransfer)) return;
    e.preventDefault();
    dragDepth++;
    document.body.classList.add('dragging-files');
  });

  window.addEventListener('dragover', (e) => {
    if (!hasDraggedFiles(e.dataTransfer)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });

  window.addEventListener('dragleave', (e) => {
    if (!hasDraggedFiles(e.dataTransfer)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) document.body.classList.remove('dragging-files');
  });

  window.addEventListener('drop', (e) => {
    if (!hasDraggedFiles(e.dataTransfer)) return;
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragging-files');
    addFiles(e.dataTransfer.files);
  });

  // ── context menu lifecycle ──
  window.addEventListener('click', (e) => {
    if (!ctxMenu.contains(e.target)) closeContextMenu();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeContextMenu();
  });
  window.addEventListener('resize', closeContextMenu);
  feed.addEventListener('scroll', closeContextMenu, { passive: true });

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
    const filesToSend = selectedFiles.slice();
    if (!text && filesToSend.length === 0) return;

    sendBtn.disabled = true;
    attachBtn.disabled = true;

    try {
      if (filesToSend.length) {
        const form = new FormData();
        form.append('text', text);
        filesToSend.forEach(file => form.append('file', file, file.name));
        const resp = await fetch('/upload', {
          method: 'POST',
          headers: { 'X-Sender': getSender() },
          body: form
        });
        if (!resp.ok) throw new Error(await resp.text());
      } else {
        const resp = await fetch('/send', {
          method: 'POST',
          headers: { 'X-Sender': getSender() },
          body: text
        });
        if (!resp.ok) throw new Error(await resp.text());
      }

      input.value = '';
      input.style.height = 'auto';
      selectedFiles = [];
      renderFileTray();

      // keep keyboard open on mobile after send
      if (!isTouch()) input.focus();
    } catch(e) {
      const row = document.createElement('div');
      row.className = 'sys-msg';
      row.textContent = '⚠ send failed';
      feed.appendChild(row);
    } finally {
      sendBtn.disabled = false;
      attachBtn.disabled = false;
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
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        elif path == "/events":
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

        elif path.startswith("/file/"):
            file_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            with lock:
                item = files.get(file_id)
            if not item:
                self.send_response(404)
                self.end_headers()
                return

            name = item["name"].replace('"', "'")
            data = item["data"]
            self.send_response(200)
            self.send_header("Content-Type", item["mime"])
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'inline; filename="{name}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        elif path == "/messages":
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
        path = urllib.parse.urlparse(self.path).path
        if path == "/send":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length).decode("utf-8", errors="replace").strip()

            if body:
                sender = self.headers.get("X-Sender", "") or self.client_address[0]
                msg    = make_message(sender, body)
                add_message(msg)
                resp = b"ok"
            else:
                resp = b"empty"

            self.send_response(200)
            self.send_header("Content-Length", str(len(resp)))
            self._cors()
            self.end_headers()
            self.wfile.write(resp)
        elif path == "/upload":
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD_BYTES:
                json_response(self, 413, {"ok": False, "error": "upload too large"})
                return

            body = self.rfile.read(length)
            try:
                text, upload_parts = parse_multipart(self.headers, body)
            except Exception as exc:
                json_response(self, 400, {"ok": False, "error": str(exc)})
                return

            if not text and not upload_parts:
                json_response(self, 400, {"ok": False, "error": "empty upload"})
                return

            sender = self.headers.get("X-Sender", "") or self.client_address[0]
            attachments = []
            stored = {}
            for item in upload_parts:
                file_id = uuid.uuid4().hex
                stored[file_id] = item
                attachments.append({
                    "id":      file_id,
                    "name":    item["name"],
                    "mime":    item["mime"],
                    "size":    item["size"],
                    "url":     f"/file/{file_id}",
                    "isImage": item["mime"].startswith("image/"),
                })

            msg = make_message(sender, text, attachments)
            with lock:
                files.update(stored)
                messages.append(msg)
                prune_messages()
            broadcast(msg)
            json_response(self, 200, {"ok": True, "message": msg})
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
