// ── CSRF token auto-injection ────────────────────────────────────
// Injects the Flask-WTF CSRF token into every POST form automatically.
document.addEventListener('DOMContentLoaded', function () {
  var meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  var token = meta.getAttribute('content');
  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
    if (!form.querySelector('[name="csrf_token"]')) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = 'csrf_token';
      inp.value = token;
      form.appendChild(inp);
    }
  });
});

// ── Global modal helpers ─────────────────────────────────────────
// Used by base.html's generic confirmModal and any future modal.

function closeModal(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

// Close modal when clicking the backdrop (the .modal-overlay itself)
document.addEventListener('click', function (e) {
  if (e.target && e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
  }
});

// ── Friend-delete confirm modal ──────────────────────────────────
// openConfirm(form) — called from friends.html delete button.
// Sets the generic confirmModal title/body, then shows it.
var _confirmForm = null;

function openConfirm(form, title, body) {
  _confirmForm = form;
  var titleEl = document.getElementById('confirmTitle');
  var bodyEl  = document.getElementById('confirmBody');
  if (titleEl) titleEl.textContent = title || 'Remove friend?';
  if (bodyEl)  bodyEl.textContent  = body  || 'Are you sure you want to remove this friend?';
  document.getElementById('confirmModal').style.display = 'flex';
  return false; // prevent form default submit
}

function closeConfirm() {
  closeModal('confirmModal');
  _confirmForm = null;
}

document.addEventListener('DOMContentLoaded', function () {
  var yesBtn = document.getElementById('confirmYes');
  if (yesBtn) {
    yesBtn.addEventListener('click', function () {
      if (_confirmForm) {
        _confirmForm.submit();
      }
      closeConfirm();
    });
  }
});

// ── Anti double-submit + loading spinner ─────────────────────────
function submitOnce(form) {
  var btns = form.querySelectorAll('button[type="submit"], button:not([type="button"])');
  btns.forEach(function (b) {
    b.disabled = true;
    b._orig = b.innerHTML;
    b.innerHTML =
      '<span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,0.4);' +
      'border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;' +
      'vertical-align:middle;margin-right:4px;"></span>Loading…';
  });
  // Re-enable after 8 s as a safety net (network timeout / error)
  setTimeout(function () {
    btns.forEach(function (b) {
      b.disabled = false;
      if (b._orig) b.innerHTML = b._orig;
    });
  }, 8000);
}

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('form[method="post"]').forEach(function (form) {
    if (form.id === 'sendForm') return;
    
    // Skip forms that already have an onsubmit handler
    if (!form.getAttribute('onsubmit')) {
      form.addEventListener('submit', function () { submitOnce(form); });
    }
  });
});

// ── Notification banner ──────────────────────────────────────────
var _notifBanner = null;

function ensureBanner() {
  if (_notifBanner) return _notifBanner;
  _notifBanner = document.createElement('div');
  _notifBanner.className = 'notif-banner';
  _notifBanner.style.display = 'none';
  var span = document.createElement('span');
  span.id = 'notifText';
  var link = document.createElement('a');
  link.href = '/friends';
  link.className = 'notif-link';
  link.textContent = 'Open chats';
  _notifBanner.appendChild(span);
  _notifBanner.appendChild(link);
  document.body.appendChild(_notifBanner);
  return _notifBanner;
}

function updateBanner(count, senders) {
  var b = ensureBanner();
  var textEl = b.querySelector('#notifText');
  if (!count || count <= 0) { b.style.display = 'none'; return; }
  var msg = count === 1 ? '1 new message' : count + ' new messages';
  if (senders && senders.length > 0) {
    var names = senders.slice(0, 2).map(function (s) { return '@' + s; }).join(', ');
    if (senders.length > 2) names += ' +' + (senders.length - 2) + ' more';
    msg += ' from ' + names;
  }
  textEl.textContent = msg;   // textContent — safe against XSS
  b.style.display = 'flex';
}

// ── Global socket — created immediately so chat.js can use it ────
// Socket.io CDN is loaded before this script in base.html.
// We create one socket per page load, join the personal room
// "user_{username}", and listen for unread_update events.
// Exposed as window._xenoSocket for chat.js and call.js to reuse.
(function () {
  var userMeta = document.querySelector('meta[name="current-user"]');
  if (!userMeta || typeof io === 'undefined') return;
  var username = userMeta.getAttribute('content');
  if (!username) return;

  var socket = io({ transports: ['websocket', 'polling'] });
  window._xenoSocket = socket;

  socket.on('connect', function () {
    // Always join personal room for cross-page notifications + calls
    socket.emit('join', { room: 'user_' + username });
  });

  // Banner update — pushed by server on every incoming DM
  socket.on('unread_update', function (d) {
    updateBanner(d.unread || 0, d.senders || []);
  });

  // Ping to keep last_seen fresh (online dot on friends page)
  function pingOnline() { fetch('/ping', { method: 'POST' }).catch(function () {}); }
  document.addEventListener('DOMContentLoaded', function () {
    pingOnline();
    setInterval(pingOnline, 20000);
  });
}());
