/* Shared site chrome — header, bottom tab switcher, footer.
   Loaded on every page; injected into .page. The active tab is read
   from <div class="page" data-page="games"> (or "about").
   Single source of truth: edit the markup here once, applies everywhere. */
(function () {
  var page = document.querySelector('.page');
  if (!page) return;
  var active = (page.getAttribute('data-page') || '').toLowerCase();
  var on = function (name) { return active === name ? ' on' : ''; };

  page.insertAdjacentHTML('afterbegin',
    '<header>' +
      '<a class="wordmark" href="https://t.me/hexplay" target="_blank" rel="noopener">' +
        '<span class="u">hexplay</span><span style="color:var(--cyan)">_</span>' +
      '</a>' +
      '<nav class="nav">' +
        '<a href="/" class="nav-btn' + on('games') + '">games</a>' +
        '<a href="/about" class="nav-btn' + on('about') + '">about</a>' +
      '</nav>' +
    '</header>'
  );

  page.insertAdjacentHTML('beforeend',
    '<footer>' +
      '<span class="footer-mark legal" style="flex-basis:100%;font-weight:400;color:var(--dim)!important">hexplay doesn&#39;t track you or collect your data · all rights belong to their owners</span>' +
      '<span class="footer-mark">// built by a gamer — for gamers</span>' +
      '<span class="footer-mark">hexplay © 2026</span>' +
    '</footer>'
  );
})();
