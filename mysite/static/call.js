// ── Xeno Voice Calls — call.js ──────────────────────────────────
// Requires: window._xenoSocket (from app.js), CHAT_FRIEND (from chat.html)
// call.js loads after app.js so socket is already created.

'use strict';

// ── State ────────────────────────────────────────────────────────
var peerConn    = null;
var localStream = null;
var callTarget  = null;
var callTimer   = null;
var callSeconds = 0;
var isCaller    = false;
var _pendingOffer = null;
var micMuted    = false;

var ICE_SERVERS = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' }
  ]
};

// ── Get socket (created by app.js IIFE) ──────────────────────────
function getSocket() {
  return window._xenoSocket || null;
}

// ── Initiate a call ──────────────────────────────────────────────
async function startCall(friend) {
  if (peerConn) return; // already in a call
  var sock = getSocket();
  if (!sock) { showCallToast('Connection error. Try again.'); return; }

  callTarget = friend;
  isCaller   = true;

  try {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    showCallToast('Microphone access denied.');
    callTarget = null; isCaller = false;
    return;
  }

  showCallingOverlay(friend);
  peerConn = createPeerConn(friend);
  localStream.getTracks().forEach(function (t) { peerConn.addTrack(t, localStream); });

  var offer = await peerConn.createOffer();
  await peerConn.setLocalDescription(offer);
  sock.emit('call_offer', { to: friend, sdp: offer });
}

// ── Accept incoming call ──────────────────────────────────────────
async function acceptCall(from, remoteSdp) {
  var sock = getSocket();
  callTarget = from;
  isCaller   = false;

  try {
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    if (sock) sock.emit('call_busy', { to: from });
    dismissIncomingCall();
    showCallToast('Microphone access denied.');
    return;
  }

  dismissIncomingCall();
  showInCallOverlay(from);

  peerConn = createPeerConn(from);
  localStream.getTracks().forEach(function (t) { peerConn.addTrack(t, localStream); });

  await peerConn.setRemoteDescription(new RTCSessionDescription(remoteSdp));
  var answer = await peerConn.createAnswer();
  await peerConn.setLocalDescription(answer);
  if (sock) sock.emit('call_answer', { to: from, sdp: answer });
}

// ── Create RTCPeerConnection ──────────────────────────────────────
function createPeerConn(friend) {
  var pc = new RTCPeerConnection(ICE_SERVERS);
  var sock = getSocket();

  pc.onicecandidate = function (e) {
    if (e.candidate && sock) {
      sock.emit('ice_candidate', { to: friend, candidate: e.candidate });
    }
  };

  pc.ontrack = function (e) {
    var audio = document.getElementById('remoteAudio');
    if (!audio) {
      audio           = document.createElement('audio');
      audio.id        = 'remoteAudio';
      audio.autoplay  = true;
      document.body.appendChild(audio);
    }
    audio.srcObject = e.streams[0];
  };

  pc.onconnectionstatechange = function () {
    if (pc.connectionState === 'connected') {
      startCallTimer();
      // Transition caller from "Calling…" overlay to in-call overlay
      if (isCaller) {
        dismissCallingOverlay();
        showInCallOverlay(friend);
      }
    }
    if (['disconnected', 'failed', 'closed'].indexOf(pc.connectionState) !== -1) {
      endCall(false);
    }
  };

  return pc;
}

// ── End call ─────────────────────────────────────────────────────
function endCall(notify) {
  if (notify === undefined) notify = true;
  var sock = getSocket();
  if (notify && callTarget && sock) {
    sock.emit('call_end', { to: callTarget });
  }
  if (peerConn)    { peerConn.close(); peerConn = null; }
  if (localStream) { localStream.getTracks().forEach(function (t) { t.stop(); }); localStream = null; }
  stopCallTimer();
  dismissIncomingCall();
  dismissCallingOverlay();
  dismissInCallOverlay();
  var audio = document.getElementById('remoteAudio');
  if (audio) audio.remove();
  callTarget    = null;
  isCaller      = false;
  micMuted      = false;
  _pendingOffer = null;
}

// ── Mic toggle ────────────────────────────────────────────────────
function toggleMic() {
  if (!localStream) return;
  micMuted = !micMuted;
  localStream.getAudioTracks().forEach(function (t) { t.enabled = !micMuted; });
  var btn = document.getElementById('micToggleBtn');
  if (btn) btn.textContent = micMuted ? '🔇' : '🎤';
}

// ── Call timer ────────────────────────────────────────────────────
function startCallTimer() {
  callSeconds = 0;
  callTimer = setInterval(function () {
    callSeconds++;
    var m  = String(Math.floor(callSeconds / 60)).padStart(2, '0');
    var s  = String(callSeconds % 60).padStart(2, '0');
    var el = document.getElementById('callTimerDisplay');
    if (el) el.textContent = m + ':' + s;
  }, 1000);
}
function stopCallTimer() {
  clearInterval(callTimer);
  callTimer = null; callSeconds = 0;
}

// ── Overlay: "Calling…" (caller side) ────────────────────────────
function showCallingOverlay(friend) {
  var container = document.getElementById('callOverlayContainer');
  if (!container) return;
  container.innerHTML =
    '<div class="call-overlay" id="callingOverlay">' +
      '<div class="call-overlay-inner">' +
        '<div class="call-avatar-large">' +
          '<div class="call-avatar-ring"></div>' +
          '<div class="call-avatar-placeholder">' + escHtml(friend[0].toUpperCase()) + '</div>' +
        '</div>' +
        '<div class="call-name">' + escHtml(friend) + '</div>' +
        '<div class="call-status">Calling…</div>' +
        '<button class="call-end-btn" onclick="endCall(true)">📵</button>' +
      '</div>' +
    '</div>';
}
function dismissCallingOverlay() {
  var el = document.getElementById('callingOverlay');
  if (el) el.remove();
}

// ── Overlay: incoming call (callee side) ─────────────────────────
function showIncomingCall(from, avatar) {
  // incoming call can appear on ANY page — inject into body if no container
  var container = document.getElementById('callOverlayContainer');
  if (!container) {
    container    = document.createElement('div');
    container.id = 'callOverlayContainer';
    document.body.appendChild(container);
  }
  var avatarHtml = avatar
    ? '<img src="' + escHtml(avatar) + '" class="call-avatar-img">'
    : '<div class="call-avatar-placeholder">' + escHtml(from[0].toUpperCase()) + '</div>';

  container.innerHTML =
    '<div class="call-overlay incoming" id="incomingCallOverlay">' +
      '<div class="call-overlay-inner">' +
        '<div class="call-avatar-large">' +
          '<div class="call-avatar-ring pulsing"></div>' +
          avatarHtml +
        '</div>' +
        '<div class="call-name">' + escHtml(from) + '</div>' +
        '<div class="call-status">Incoming voice call…</div>' +
        '<div class="call-incoming-actions">' +
          '<button class="call-decline-btn" onclick="declineCall(\'' + escHtml(from) + '\')">📵</button>' +
          '<button class="call-accept-btn"  onclick="acceptCallFromOverlay(\'' + escHtml(from) + '\')">📞</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}
function dismissIncomingCall() {
  var el = document.getElementById('incomingCallOverlay');
  if (el) el.remove();
}

// ── Overlay: in-call (both sides) ────────────────────────────────
function showInCallOverlay(friend) {
  var container = document.getElementById('callOverlayContainer');
  if (!container) {
    container    = document.createElement('div');
    container.id = 'callOverlayContainer';
    document.body.appendChild(container);
  }
  container.innerHTML =
    '<div class="call-overlay in-call" id="inCallOverlay">' +
      '<div class="call-overlay-inner">' +
        '<div class="call-avatar-large">' +
          '<div class="call-avatar-placeholder">' + escHtml(friend[0].toUpperCase()) + '</div>' +
        '</div>' +
        '<div class="call-name">' + escHtml(friend) + '</div>' +
        '<div class="call-timer" id="callTimerDisplay">00:00</div>' +
        '<div class="call-in-actions">' +
          '<button class="call-mic-btn" id="micToggleBtn" onclick="toggleMic()">🎤</button>' +
          '<button class="call-end-btn" onclick="endCall(true)">📵</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}
function dismissInCallOverlay() {
  var el = document.getElementById('inCallOverlay');
  if (el) el.remove();
}

// ── Pending SDP helper ────────────────────────────────────────────
function acceptCallFromOverlay(from) {
  if (_pendingOffer) acceptCall(from, _pendingOffer);
}

function declineCall(from) {
  var sock = getSocket();
  if (sock) sock.emit('call_end', { to: from });
  _pendingOffer = null;
  dismissIncomingCall();
}

// ── Toast notification ────────────────────────────────────────────
function showCallToast(msg) {
  var t       = document.createElement('div');
  t.className = 'call-toast';
  t.textContent = msg;           // textContent — safe
  document.body.appendChild(t);
  setTimeout(function () { t.remove(); }, 3500);
}

// ── XSS-safe string escaper for innerHTML ─────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Socket event listeners ────────────────────────────────────────
// Wired up once the DOM is ready (socket already exists from app.js IIFE)
document.addEventListener('DOMContentLoaded', function () {
  var sock = getSocket();
  if (!sock) return;

  // ── Incoming call offer ───────────────────────────────────────
  sock.on('call_offer', function (data) {
    if (peerConn) {
      // Already in a call — send busy signal
      sock.emit('call_busy', { to: data.from });
      return;
    }
    _pendingOffer = data.sdp;
    showIncomingCall(data.from, data.from_avatar || '');
    showCallToast('📞 Incoming call from ' + data.from);
  });

  // ── Caller receives answer ────────────────────────────────────
  sock.on('call_answer', async function (data) {
    if (!peerConn) return;
    try {
      await peerConn.setRemoteDescription(new RTCSessionDescription(data.sdp));
      // onconnectionstatechange will handle overlay transition to in-call
    } catch (e) {
      console.error('call_answer error:', e);
    }
  });

  // ── ICE candidate exchange ────────────────────────────────────
  sock.on('ice_candidate', async function (data) {
    if (!peerConn || !data.candidate) return;
    try {
      await peerConn.addIceCandidate(new RTCIceCandidate(data.candidate));
    } catch (e) { /* ignore stale candidates */ }
  });

  // ── Remote ended the call ─────────────────────────────────────
  sock.on('call_end', function () {
    endCall(false);
    showCallToast('Call ended.');
  });

  // ── Remote is busy ────────────────────────────────────────────
  sock.on('call_busy', function () {
    showCallToast('📵 User is busy.');
    endCall(false);
  });
});
