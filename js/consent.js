/* Согласие на cookie (152-ФЗ): Яндекс Метрика включается только после «Принять».
   Подключается на всех страницах сайта одной строкой <script src="/js/consent.js"></script>.
   Выбор посетителя хранится в localStorage этого браузера; без выбора и после «Отказаться» Метрика не загружается. */
(function () {
  var ID = 113881059, KEY = 'cookie-consent';
  // очередь вызовов: цели, вызванные до согласия, не уходят никуда, пока Метрика не загружена
  window.ym = window.ym || function () { (window.ym.a = window.ym.a || []).push(arguments); };
  window.ym.l = +new Date();

  function get() { try { return localStorage.getItem(KEY); } catch (_) { return null; } }
  function set(v) { try { localStorage.setItem(KEY, v); } catch (_) {} }

  var loaded = false;
  function load() {
    if (loaded) return; loaded = true;
    // Вебвизор не записывает, что набрано в полях (имя, телефон)
    [].forEach.call(document.querySelectorAll('input,textarea'), function (el) { el.classList.add('ym-disable-keys'); });
    var s = document.createElement('script'); s.async = true; s.src = 'https://mc.yandex.ru/metrika/tag.js';
    document.head.appendChild(s);
    ym(ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true });
    var goal = function (g) { try { ym(ID, 'reachGoal', g); } catch (_) {} };
    document.addEventListener('click', function (ev) {
      var a = ev.target.closest && ev.target.closest('a[href]'); if (!a) return; var h = a.href;
      if (h.indexOf('wa.me') > -1) goal('wa'); else if (h.indexOf('t.me') > -1) goal('tg');
      else if (h.indexOf('max.ru') > -1) goal('max'); else if (h.indexOf('tel:') === 0) goal('call');
    }, true);
    document.addEventListener('submit', function () { goal('lead'); }, true);
    document.addEventListener('play', function (ev) { if (ev.target.tagName === 'VIDEO') goal('video'); }, true);
  }

  function banner() {
    var css = document.createElement('style');
    css.textContent =
      '.ck{position:fixed;left:12px;right:12px;bottom:12px;z-index:2147483000;max-width:560px;margin:0 auto;' +
      'background:#1C2026;color:#E3E6EA;border:1px solid #2A3039;border-radius:18px;padding:16px 18px;' +
      'box-shadow:0 10px 40px rgba(0,0,0,.45);font:14px/1.5 Manrope,"Segoe UI",system-ui,sans-serif}' +
      '.ck a{color:#FF7A1A}.ck .b{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}' +
      '.ck button{flex:1 1 140px;border:0;border-radius:999px;padding:11px 16px;font:800 14px Manrope,"Segoe UI",sans-serif;cursor:pointer}' +
      '.ck .y{background:#FF7A1A;color:#121417}.ck .n{background:transparent;color:#E3E6EA;border:1px solid #3A414C}';
    document.head.appendChild(css);
    var d = document.createElement('div');
    d.className = 'ck'; d.setAttribute('role', 'dialog'); d.setAttribute('aria-label', 'Согласие на cookie');
    d.innerHTML = 'Сайт использует cookie и сервис Яндекс Метрика, чтобы понимать, удобен ли сайт. ' +
      'Нажимая «Принять», вы соглашаетесь на обработку этих данных ООО «Яндекс» по нашему поручению. ' +
      '<a href="/privacy.html#cookie">Подробнее</a>' +
      '<div class="b"><button type="button" class="y">Принять</button><button type="button" class="n">Отказаться</button></div>';
    document.body.appendChild(d);
    d.querySelector('.y').onclick = function () { set('yes'); d.remove(); load(); };
    d.querySelector('.n').onclick = function () { set('no'); d.remove(); };
  }

  function start() {
    var v = get();
    if (v === 'yes') load();
    else if (v !== 'no') banner();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
