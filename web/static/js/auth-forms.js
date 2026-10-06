// Show/hide password, strength meter and confirm-match check for
// auth.html and account.html (fields from partials/new_password.html).
(function () {
  document.querySelectorAll('.peek').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = btn.parentNode.querySelector('input');
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.firstElementChild.textContent = show ? 'visibility_off' : 'visibility';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });

  var pw = document.getElementById('password'), meter = document.querySelector('.meter');
  if (pw && meter) {
    var bars = meter.querySelectorAll('i'), label = document.querySelector('.meter-label');
    var names = ['', 'Weak', 'Fair', 'Good', 'Strong'], colors = ['', '#ba1a1a', '#C6742A', '#2f685f', '#0e7a52'];
    pw.addEventListener('input', function () {
      var v = pw.value, score = 0;
      if (v.length >= 8) score++;
      if (v.length >= 12) score++;
      if (/[a-z]/.test(v) && /[A-Z]/.test(v)) score++;
      if (/\d/.test(v) && /[^A-Za-z0-9]/.test(v)) score++;
      if (v && score === 0) score = 1;
      bars.forEach(function (b, i) { b.style.background = i < score ? colors[score] : ''; });
      label.textContent = v ? names[score] + (v.length < 8 ? ' - use at least 8 characters' : '') : '';
    });
  }

  var confirm = document.getElementById('confirm');
  if (pw && confirm) {
    var check = function () { confirm.setCustomValidity(confirm.value && confirm.value !== pw.value ? "Passwords don't match" : ''); };
    pw.addEventListener('input', check);
    confirm.addEventListener('input', check);
  }
})();
