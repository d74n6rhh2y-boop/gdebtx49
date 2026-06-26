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
        '<a href="/" class="nav-btn' + on('games') + '"><svg class="nav-ic" viewBox="0 0 24 24" aria-hidden="true"><line x1="6" x2="10" y1="11" y2="11"/><line x1="8" x2="8" y1="9" y2="13"/><line x1="15" x2="15.01" y1="12" y2="12"/><line x1="18" x2="18.01" y1="10" y2="10"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/></svg>games</a>' +
        '<a href="/about" class="nav-btn' + on('about') + '"><svg class="nav-ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>about</a>' +
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
