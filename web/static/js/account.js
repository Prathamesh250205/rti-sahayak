/* Signed-in account menu. Pages are cached at the CDN and always rendered
   signed-out; when the rti_signed_in hint cookie is present (set beside the
   HttpOnly session at sign-in, see web/api/auth.py) the menu is fetched from
   /api/auth/me and swapped in. Signed-out visitors never call the server.
   English text here is translated by i18n.js like any other page text. */
(function () {
  if (!/(?:^|;\s*)rti_signed_in=1/.test(document.cookie)) {
    return;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  var SIGN_OUT = '<form method="post" action="/logout"><button %s type="submit">Sign out</button></form>';

  function render(user) {
    var name = escapeHtml(user.name);
    document.querySelectorAll('.acct-slot').forEach(function (slot) {
      if (slot.getAttribute('data-variant') === 'mobile') {
        slot.innerHTML = '<a class="acct-hello" href="/account">Signed in as <strong>' + name + '</strong></a>' +
          SIGN_OUT.replace('%s', 'class="acct-ghost"');
      } else {
        slot.innerHTML = '<details class="acct-menu"><summary aria-label="Account menu"><span class="acct-avatar">' +
          escapeHtml(user.name.charAt(0).toUpperCase()) + '</span></summary><div class="acct-pop">' +
          '<p class="acct-pop-name">' + name + '</p><p class="acct-pop-mail">' + escapeHtml(user.email) + '</p>' +
          '<a class="acct-pop-link" href="/account">Account settings</a>' + SIGN_OUT.replace('%s ', '') + '</div></details>';
      }
    });
    var welcome = document.getElementById('cta-welcome');
    if (welcome) {
      welcome.textContent = 'Welcome back, ' + user.name + '. Pick up where you left off.';
      document.getElementById('cta-signed-in').hidden = false;
      document.getElementById('cta-signed-out').hidden = true;
    }
  }

  fetch('/api/auth/me', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) {
        // Session expired or was revoked: drop the stale hint.
        document.cookie = 'rti_signed_in=; Max-Age=0; path=/';
        return null;
      }
      return r.ok ? r.json() : null;
    })
    .then(function (user) {
      if (user) {
        render(user);
      }
    })
    .catch(function () {
      // Offline or server error: the signed-out controls stay, which still work.
    });
})();
