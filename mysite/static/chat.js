// ── chat.js — Xeno Chat Page Logic ──────────────────────────────
// Requires: window._xenoSocket (set by app.js), CHAT_FRIEND,
//           CHAT_ROOM, CHAT_ME, IS_GROUP (set inline in template)

'use strict';

// ── Socket setup ─────────────────────────────────────────────────
var socket = window._xenoSocket;
var typingTimer = null;

if (socket) {
  // Join chat room — wait for connection to be ready
  if (socket.connected) {
    socket.emit('join', { room: CHAT_ROOM });
  } else {
    socket.on('connect', function () {
      socket.emit('join', { room: CHAT_ROOM });
    });
  }

  // ── Incoming message ──────────────────────────────────────────
  socket.on('new_message', function (m) {
    // Skip own messages — already shown optimistically by AJAX send
    if (m.sender === CHAT_ME) return;
    removeEmptyState();
    var row    = buildBubble(m, 'them');
    var box    = document.getElementById('chatBox');
    var typing = document.getElementById('typingRow');
    if (box) {
      box.insertBefore(row, typing);
      scrollToBottom();
    }
  });

  // ── Typing indicator ──────────────────────────────────────────
  socket.on('typing', function (data) {
    if (data.sender === CHAT_ME) return;
    var tr = document.getElementById('typingRow');
    if (tr) tr.style.display = '';
    scrollToBottom();
    clearTimeout(typingTimer);
    typingTimer = setTimeout(function () {
      if (tr) tr.style.display = 'none';
    }, 3500);
  });

  // ── Seen update ───────────────────────────────────────────────
  socket.on('seen_update', function () {
    document.querySelectorAll('.msg-tick').forEach(function (el) {
      el.classList.add('seen');
      el.textContent = '✓✓';
    });
  });
}

// ── Build a new message bubble (for socket new_message) ──────────
var IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];
var AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'ogg', 'oga', 'aac'];
var VIDEO_EXTS = ['mp4', 'webm', 'mov', 'm4v'];

function buildBubble(m, align) {
  var row    = document.createElement('div');
  row.className = 'msg-row ' + align;
  if (m.id) { row.id = 'msg-' + m.id; row.dataset.id = m.id; }

  var bubble = document.createElement('div');
  bubble.className = 'msg-bubble ' + align;
  if (m.id) bubble.dataset.id = String(m.id);
  bubble.setAttribute('oncontextmenu',
    'showMsgMenu(event,' + m.id + ',"' + align + '")');

  // Sender name in groups
  if (IS_GROUP && align === 'them') {
    var author = document.createElement('div');
    author.className = 'msg-author';
    author.textContent = m.sender;
    bubble.appendChild(author);
  }

  // Media
  if (m.ftype === 'file' && m.url) {
    var ext      = (m.filename || '').split('.').pop().toLowerCase();
    var mediaDiv = document.createElement('div');
    if (IMAGE_EXTS.indexOf(ext) !== -1) {
      mediaDiv.className = 'msg-media';
      var a   = document.createElement('a');
      a.href  = m.url; a.target = '_blank';
      var img = document.createElement('img');
      img.src = m.url; img.loading = 'lazy';
      a.appendChild(img); mediaDiv.appendChild(a);
    } else if (VIDEO_EXTS.indexOf(ext) !== -1) {
      mediaDiv.className = 'msg-media';
      var vid      = document.createElement('video');
      vid.src      = m.url; vid.controls = true;
      vid.preload  = 'none'; vid.setAttribute('playsinline', '');
      mediaDiv.appendChild(vid);
    } else if (AUDIO_EXTS.indexOf(ext) !== -1) {
      mediaDiv.className = 'msg-audio';
      var icon  = document.createElement('span'); icon.textContent = '🎵';
      var audio = document.createElement('audio');
      audio.controls = true; audio.preload = 'none';
      var src   = document.createElement('source'); src.src = m.url;
      audio.appendChild(src);
      mediaDiv.appendChild(icon); mediaDiv.appendChild(audio);
    } else {
      mediaDiv.className = 'msg-file';
      var icon2 = document.createElement('span'); icon2.textContent = '📎';
      var link  = document.createElement('a');
      link.href = m.url; link.target = '_blank';
      link.textContent = m.filename;            // textContent — safe
      mediaDiv.appendChild(icon2); mediaDiv.appendChild(link);
    }
    bubble.appendChild(mediaDiv);
  }

  // Text
  var txt = document.createElement('div');
  txt.className = 'msg-text';
  txt.textContent = m.text || '';               // textContent — safe
  bubble.appendChild(txt);

  // Meta
  var meta = document.createElement('div');
  meta.className = 'msg-meta';
  var timeEl = document.createElement('span');
  timeEl.className = 'msg-time';
  timeEl.textContent = m.time || 'just now';
  meta.appendChild(timeEl);
  if (align === 'me') {
    var tick = document.createElement('span');
    tick.className = 'msg-tick';
    tick.textContent = '✓';
    meta.appendChild(tick);
  }
  bubble.appendChild(meta);

  row.appendChild(bubble);
  return row;
}

// ── Scroll helpers ────────────────────────────────────────────────
function scrollToBottom() {
  var box = document.getElementById('chatBox');
  if (box) box.scrollTop = box.scrollHeight;
}

function scrollToMsg(msgId) {
  var el = document.getElementById('msg-' + msgId);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  var bubble = el.querySelector('.msg-bubble');
  if (bubble) {
    bubble.classList.add('flash');
    setTimeout(function () { bubble.classList.remove('flash'); }, 1200);
  }
}

function removeEmptyState() {
  var e = document.getElementById('emptyMsg');
  if (e) e.remove();
}

// Auto-scroll on load
document.addEventListener('DOMContentLoaded', function () {
  scrollToBottom();
});

// ── Enter to send ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  var inp = document.getElementById('msgInput');
  if (!inp) return;
  inp.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      document.getElementById('sendForm').submit();
    }
  });
  // Typing event
  inp.addEventListener('input', function () {
    if (socket) socket.emit('typing', { room: CHAT_ROOM });
  });
});

// ── Three-dot menu ────────────────────────────────────────────────
function toggleChatMenu() {
  var d = document.getElementById('chatDropdown');
  if (d) d.classList.toggle('open');
}
document.addEventListener('click', function (e) {
  var btn = document.getElementById('menuBtn');
  var dd  = document.getElementById('chatDropdown');
  if (dd && !dd.contains(e.target) && e.target !== btn) {
    dd.classList.remove('open');
  }
});

// ── In-chat search ────────────────────────────────────────────────
var searchMatches = [];
var searchIndex   = 0;

function openChatSearch() {
  document.getElementById('chatDropdown').classList.remove('open');
  var bar = document.getElementById('chatSearchBar');
  if (bar) { bar.style.display = 'flex'; document.getElementById('chatSearchInput').focus(); }
}

function closeChatSearch() {
  var bar = document.getElementById('chatSearchBar');
  if (bar) bar.style.display = 'none';
  var inp = document.getElementById('chatSearchInput');
  if (inp) inp.value = '';
  clearSearchHighlights();
  searchMatches = []; searchIndex = 0;
  var cnt = document.getElementById('searchResultCount');
  if (cnt) cnt.textContent = '0 of 0';
}

function clearSearchHighlights() {
  document.querySelectorAll('.msg-text').forEach(function (el) {
    // Safe: replace with own plain text — strips highlight marks
    el.textContent = el.textContent;
  });
}

function searchMessages(query) {
  clearSearchHighlights();
  searchMatches = []; searchIndex = 0;
  var cnt = document.getElementById('searchResultCount');
  if (!query.trim()) { if (cnt) cnt.textContent = '0 of 0'; return; }

  var q     = query.toLowerCase();
  var regex = new RegExp(
    '(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')',
    'gi'
  );

  document.querySelectorAll('.msg-text:not(.deleted)').forEach(function (el) {
    var text = el.textContent;
    if (text.toLowerCase().indexOf(q) !== -1) {
      // Highlight — only plain text goes in, so innerHTML is safe here
      el.innerHTML = text.replace(regex, '<mark class="msg-highlight">$1</mark>');
      searchMatches.push(el.closest('.msg-row'));
    }
  });

  if (cnt) {
    cnt.textContent = searchMatches.length ? '1 of ' + searchMatches.length : '0 results';
  }
  if (searchMatches.length) scrollToSearchMatch(0);
}

function scrollToSearchMatch(idx) {
  document.querySelectorAll('.msg-highlight-current').forEach(function (el) {
    el.classList.remove('msg-highlight-current');
  });
  if (!searchMatches[idx]) return;
  searchMatches[idx].querySelectorAll('.msg-highlight').forEach(function (el) {
    el.classList.add('msg-highlight-current');
  });
  searchMatches[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
  var cnt = document.getElementById('searchResultCount');
  if (cnt) cnt.textContent = (idx + 1) + ' of ' + searchMatches.length;
}

function nextSearchResult() {
  if (!searchMatches.length) return;
  searchIndex = (searchIndex + 1) % searchMatches.length;
  scrollToSearchMatch(searchIndex);
}
function prevSearchResult() {
  if (!searchMatches.length) return;
  searchIndex = (searchIndex - 1 + searchMatches.length) % searchMatches.length;
  scrollToSearchMatch(searchIndex);
}

// ── Reply ─────────────────────────────────────────────────────────
function setReply(msgId, author, text) {
  document.getElementById('replyToInput').value    = msgId;
  document.getElementById('replyBarAuthor').textContent = author;
  document.getElementById('replyBarText').textContent   = text.slice(0, 80);
  document.getElementById('replyBar').style.display     = 'flex';
  var inp = document.getElementById('msgInput');
  if (inp) inp.focus();
}

function cancelReply() {
  document.getElementById('replyToInput').value = '';
  document.getElementById('replyBar').style.display = 'none';
}

// ── Context menu (right-click / long-press) ───────────────────────
var _longPressTimer = null;

function showMsgMenu(event, msgId, align) {
  event.preventDefault();
  var existing = document.getElementById('msgContextMenu');
  if (existing) existing.remove();

  // Get text for copy
  var rowEl  = document.getElementById('msg-' + msgId);
  var txtEl  = rowEl ? rowEl.querySelector('.msg-text') : null;
  var txtVal = txtEl ? txtEl.textContent : '';

  // Get sender for reply label
  var authorEl  = rowEl ? rowEl.querySelector('.msg-author') : null;
  var authorVal = authorEl ? authorEl.textContent.trim() : CHAT_FRIEND;

  var menu = document.createElement('div');
  menu.id        = 'msgContextMenu';
  menu.className = 'msg-context-menu';

  // Reply button
  var replyBtn = document.createElement('button');
  replyBtn.textContent = '↩ Reply';
  replyBtn.onclick = function () {
    menu.remove();
    setReply(msgId, authorVal, txtVal);
  };
  menu.appendChild(replyBtn);

  // Copy button
  var copyBtn = document.createElement('button');
  copyBtn.textContent = '📋 Copy';
  copyBtn.onclick = function () {
    menu.remove();
    if (navigator.clipboard) navigator.clipboard.writeText(txtVal);
  };
  menu.appendChild(copyBtn);

  // Delete (own messages only)
  if (align === 'me') {
    var delBtn = document.createElement('button');
    delBtn.textContent = '🗑 Delete';
    delBtn.className   = 'danger';
    delBtn.onclick = function () {
      menu.remove();
      deleteMsg(msgId);
    };
    menu.appendChild(delBtn);
  }

  // Position
  var x = event.clientX || 0;
  var y = event.clientY || 0;
  menu.style.top  = y + 'px';
  menu.style.left = Math.min(x, window.innerWidth - 180) + 'px';
  document.body.appendChild(menu);

  // Close on any click outside
  setTimeout(function () {
    document.addEventListener('click', function rm() {
      menu.remove();
      document.removeEventListener('click', rm);
    });
  }, 10);
}

function handleTouchStart(event, msgId, align) {
  _longPressTimer = setTimeout(function () {
    var touch = event.touches[0];
    showMsgMenu(
      { preventDefault: function(){}, clientY: touch.clientY, clientX: touch.clientX },
      msgId, align
    );
  }, 500);
}
document.addEventListener('touchend', function () { clearTimeout(_longPressTimer); });

// ── Delete message ────────────────────────────────────────────────
function deleteMsg(msgId) {
  var f = document.createElement('form');
  f.method = 'post'; f.style.display = 'none';
  var a = document.createElement('input'); a.name = 'action'; a.value = 'delete';
  var i = document.createElement('input'); i.name = 'msg_id'; i.value = msgId;
  var meta   = document.querySelector('meta[name="csrf-token"]');
  var csrf   = document.createElement('input');
  csrf.type  = 'hidden'; csrf.name = 'csrf_token';
  csrf.value = meta ? meta.getAttribute('content') : '';
  f.appendChild(a); f.appendChild(i); f.appendChild(csrf);
  document.body.appendChild(f); f.submit();
}

// ── Clear chat modal ──────────────────────────────────────────────
function openClearModal() {
  document.getElementById('chatDropdown').classList.remove('open');
  document.getElementById('confirmTitle').textContent = 'Clear this chat?';
  document.getElementById('confirmBody').textContent  = 'All messages deleted permanently for you.';
  document.getElementById('confirmYes').onclick = function () {
    closeModal('confirmModal');
    fetch('/chat/' + CHAT_FRIEND + '/clear', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() }
    }).then(function () { location.reload(); });
  };
  document.getElementById('confirmModal').style.display = 'flex';
}

// ── Block modal ───────────────────────────────────────────────────
function openBlockModal() {
  document.getElementById('chatDropdown').classList.remove('open');
  document.getElementById('confirmTitle').textContent = 'Block ' + CHAT_FRIEND + '?';
  document.getElementById('confirmBody').textContent  = "They won't be able to message you.";
  document.getElementById('confirmYes').onclick = function () {
    closeModal('confirmModal');
    fetch('/user/' + CHAT_FRIEND + '/block', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf() }
    }).then(function () { location.href = '/friends'; });
  };
  document.getElementById('confirmModal').style.display = 'flex';
}

// ── Report modal ──────────────────────────────────────────────────
function openReportModal() {
  document.getElementById('chatDropdown').classList.remove('open');
  document.getElementById('reportModal').style.display = 'flex';
}

function submitReport() {
  var reason = document.getElementById('reportReason').value.trim();
  var body   = new FormData();
  body.append('reason', reason);
  fetch('/user/' + CHAT_FRIEND + '/report', { method: 'POST', body: body })
    .then(function () {
      closeModal('reportModal');
      document.getElementById('reportReason').value = '';
    });
}

// ── Media panel ───────────────────────────────────────────────────
function openMediaPanel() {
  document.getElementById('chatDropdown').classList.remove('open');
  document.getElementById('mediaPanel').style.display = 'flex';
}
function closeMediaPanel() {
  document.getElementById('mediaPanel').style.display = 'none';
}
function switchMediaTab(btn, tab) {
  document.querySelectorAll('.mpanel-tab').forEach(function (b) {
    b.classList.remove('active');
  });
  btn.classList.add('active');
  // Future: load content per tab
}

// ── CSRF helper ───────────────────────────────────────────────────
function getCsrf() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

// ── AJAX send — no page reload ────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('sendForm');
  if (!form) return;
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var inp  = document.getElementById('msgInput');
    var text = inp ? inp.value.trim() : '';
    if (!text) return;
    var data = new FormData(form);
    var msgText = text;
    inp.value = '';
    cancelReply();
    // Optimistically append bubble immediately
    removeEmptyState();
    var row = buildBubble({text: msgText, time: 'just now', ftype: 'text'}, 'me');
    var box = document.getElementById('chatBox');
    var typing = document.getElementById('typingRow');
    if (box) { box.insertBefore(row, typing); scrollToBottom(); }
    fetch(window.location.pathname, {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest',
                 'X-CSRFToken': getCsrf() },
      body: data
    }).catch(function () { form.submit(); });
  });
});
