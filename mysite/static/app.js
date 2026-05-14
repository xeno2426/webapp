// ---- Fix 1.3 — CSRF token auto-injection ----
// Reads the token from the <meta name="csrf-token"> tag set in base.html and
// injects a hidden csrf_token field into every static POST form on the page.
// Dynamic forms created by JS (swipe-to-reply in chat pages) add the token themselves.
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

// ---- Notification banner + online ping ----
document.addEventListener('DOMContentLoaded', function(){
  var banner = null;
  function ensureBanner(){
    if(banner) return banner;
    banner = document.createElement('div');
    banner.className = 'notif-banner';
    banner.style.display = 'none';
    banner.innerHTML = '<span id="notifText"></span><a href="/friends" class="notif-link">Open chats</a>';
    document.body.appendChild(banner);
    return banner;
  }
  function updateBanner(count, senders){
    var b = ensureBanner(), textEl = b.querySelector('#notifText');
    if(!textEl) return;
    if(!count || count <= 0){ b.style.display = 'none'; return; }
    var who = '';
    if(senders && senders.length > 0){
      var names = senders.slice(0,2).map(function(s){ return '@'+s; }).join(', ');
      if(senders.length > 2) names += ' +' + (senders.length-2) + ' more';
      who = ' from ' + names;
    }
    textEl.textContent = (count === 1 ? '1 new message' : count + ' new messages') + who;
    b.style.display = 'flex';
  }
  function pollUnread(){
    fetch('/unread.json').then(function(r){ return r.json(); })
      .then(function(d){ if(d && d.ok) updateBanner(d.unread||0, d.senders||[]); })
      .catch(function(){});
  }
  function pingOnline(){ fetch('/ping',{method:'POST'}).catch(function(){}); }
  pollUnread(); setInterval(pollUnread, 5000);
  pingOnline(); setInterval(pingOnline, 20000);
});
