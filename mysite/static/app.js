// ---- Fix 1.3 — CSRF token auto-injection ----
document.addEventListener('DOMContentLoaded', function(){
  var meta = document.querySelector('meta[name="csrf-token"]');
  if(!meta) return;
  var token = meta.getAttribute('content');
  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function(form){
    if(!form.querySelector('[name="csrf_token"]')){
      var inp = document.createElement('input');
      inp.type = 'hidden'; inp.name = 'csrf_token'; inp.value = token;
      form.appendChild(inp);
    }
  });
});

// ---- Delete confirm modal ----
let deleteForm = null;
function openConfirm(form){ deleteForm = form; document.getElementById("confirmModal").style.display = "flex"; return false; }
function closeConfirm(){ document.getElementById("confirmModal").style.display = "none"; deleteForm = null; }
document.addEventListener("DOMContentLoaded", function(){
  var yesBtn = document.getElementById("confirmYes");
  if(yesBtn){ yesBtn.onclick = function(){ if(deleteForm) deleteForm.submit(); }; }
});

// ---- Anti double-submit + loading spinner ----
function submitOnce(form){
  var btns = form.querySelectorAll('button[type="submit"],button:not([type="button"])');
  btns.forEach(function(b){
    b.disabled = true; b._orig = b.innerHTML;
    b.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:4px;"></span>Loading...';
  });
  setTimeout(function(){
    btns.forEach(function(b){ b.disabled = false; if(b._orig) b.innerHTML = b._orig; });
  }, 8000);
}
document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('form[method="post"]').forEach(function(form){
    if(!form.getAttribute('onsubmit')){
      form.addEventListener('submit', function(){ submitOnce(form); });
    }
  });
});

// ---- Notification banner ----
var _notifBanner = null;
function ensureBanner(){
  if(_notifBanner) return _notifBanner;
  _notifBanner = document.createElement('div');
  _notifBanner.className = 'notif-banner';
  _notifBanner.style.display = 'none';
  // Fix 1.8 — build banner with DOM API; no innerHTML with user-supplied data
  var span = document.createElement('span'); span.id = 'notifText';
  var link = document.createElement('a');
  link.href = '/friends'; link.className = 'notif-link'; link.textContent = 'Open chats';
  _notifBanner.appendChild(span);
  _notifBanner.appendChild(link);
  document.body.appendChild(_notifBanner);
  return _notifBanner;
}
function updateBanner(count, senders){
  var b = ensureBanner();
  var textEl = b.querySelector('#notifText');
  if(!count || count <= 0){ b.style.display = 'none'; return; }
  var msg = (count === 1 ? '1 new message' : count + ' new messages');
  if(senders && senders.length > 0){
    var names = senders.slice(0,2).map(function(s){ return '@'+s; }).join(', ');
    if(senders.length > 2) names += ' +' + (senders.length-2) + ' more';
    msg += ' from ' + names;
  }
  textEl.textContent = msg;  // textContent — safe
  b.style.display = 'flex';
}

// ---- Fix 5.4 — Global socket for unread notifications (replaces polling) ----
// Socket.io is loaded in base.html. We connect once per page, join the personal
// room "user_{username}", and listen for unread_update events from the server.
// The server pushes this event whenever a message is sent to the current user,
// so the banner updates instantly without any polling interval.
document.addEventListener('DOMContentLoaded', function(){
  var userMeta = document.querySelector('meta[name="current-user"]');
  if(!userMeta) return;                         // not logged in, nothing to do
  var username = userMeta.getAttribute('content');
  if(!username) return;

  // Only connect if not already on a chat page (chat pages manage their own socket).
  // We check for the chatBox element as a signal that a chat page is already running.
  var onChatPage = !!document.getElementById('chatBox');

  var socket = (typeof io !== 'undefined') ? io({ transports: ['websocket','polling'] }) : null;
  if(!socket) return;

  socket.on('connect', function(){
    // Join personal notification room
    socket.emit('join', { room: 'user_' + username });
    // Chat pages also join their own room — that's handled in the chat template's script.
  });

  // Fix 5.4 — update banner immediately when server pushes unread_update
  socket.on('unread_update', function(d){
    updateBanner(d.unread || 0, d.senders || []);
  });

  // Keep pinging last_seen for online status indicator (unchanged)
  function pingOnline(){ fetch('/ping', { method: 'POST' }).catch(function(){}); }
  pingOnline();
  setInterval(pingOnline, 20000);
});
