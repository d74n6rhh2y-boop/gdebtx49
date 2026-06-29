/* Shared site chrome — header (top tab switcher), hero (logo + slogan),
   and footer. Loaded on every page; injected into .page.

   SINGLE SOURCE OF TRUTH: edit the markup here once and it applies to every
   page. The active tab and the page-specific subtitle are chosen from
   <div class="page" data-page="games"> (or "about").

   Loaded as the first child of .page so it runs before each page's own
   end-of-body script, which expects .logo / .wordmark / the hero to exist. */
(function () {
  var page = document.querySelector('.page');
  if (!page) return;
  var active = (page.getAttribute('data-page') || '').toLowerCase();
  var on = function (name) { return active === name ? ' on' : ''; };

  // Subtitle shown under the slogan. Page-specific: only the games page has one.
  // Add an entry here to give another page its own subtitle.
  var SUBTITLE = {
    games: 'Indie gems, top and hidden hits. Concise. Direct. Clear.<br>Use tags &gt; pick a game &gt; play better'
  };
  var sub = SUBTITLE[active] ? '<p>' + SUBTITLE[active] + '</p>' : '';

  page.insertAdjacentHTML('afterbegin',
    '<header>' +
      '<a class="wordmark" href="https://t.me/hexplay" target="_blank" rel="noopener">' +
        '<span class="u">hexplay</span><span style="color:var(--cyan)">_</span>' +
      '</a>' +
      '<nav class="nav">' +
        '<a href="/" class="nav-btn' + on('games') + '"><svg class="nav-ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="6" r="3"/><path d="M12 9v6"/><path d="M6 15h12a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2Z"/></svg>games</a>' +
        '<a href="/about" class="nav-btn' + on('about') + '"><svg class="nav-ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>about</a>' +
      '</nav>' +
    '</header>' +
    '<section class="hero">' +
      '<div class="logo-wrap"><img class="logo" src="/logo.jpg" alt="hexplay — curated mobile games" width="480" height="480" decoding="async" fetchpriority="high" draggable="false"></div>' +
      '<div class="hero-text">' +
        '<div class="hero-eyebrow">// catalog of the best mobile games</div>' +
        '<h1 class="glitch-text">I filter the noise<br><span class="grad">You play better</span></h1>' +
        sub +
      '</div>' +
    '</section>'
  );

  // Footer must land at the very end of .page. This script runs as the first
  // child, so at this point the rest of the page body isn't parsed yet — a
  // synchronous beforeend would drop the footer above the page content. Defer
  // it until the DOM is ready so it's appended after everything. (The header +
  // hero stay synchronous because each page's end-of-body script needs them.)
  var addFooter = function () {
    page.insertAdjacentHTML('beforeend',
      '<footer>' +
        '<span class="footer-mark legal" style="flex-basis:100%;font-weight:400;color:var(--dim)!important">hexplay doesn&#39;t track you or collect your data · all rights belong to their owners</span>' +
        '<span class="footer-mark">// built by a gamer — for gamers</span>' +
        '<span class="footer-mark">hexplay © 2026</span>' +
      '</footer>'
    );
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addFooter);
  } else {
    addFooter();
  }
})();
