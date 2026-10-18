(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const ic = (n, cls = '') => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
/* Percent change that never divides by zero (null when there is no base) */
const change = (cur, prev) => (prev ? (cur / prev - 1) * 100 : null);
/* One listener set per host: re-running a mount replaces its handlers
   instead of stacking a second copy (pass the result as the options). */
const hostSignal = (el) => { el._ac?.abort(); el._ac = new AbortController(); return { signal: el._ac.signal }; };
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const isMobile = () => matchMedia('(max-width: 767px)').matches;

const prefs = (() => {
  const KEY = 'aiqyn-vision.prefs';
  let data = {};
  try { data = JSON.parse(localStorage.getItem(KEY) || localStorage.getItem('forte-vision.prefs') || '{}') || {}; } catch (e) { data = {}; }
  return {
    get: (k, d) => (k in data ? data[k] : d),
    set(k, v) { data[k] = v; try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* sandboxed: keep in memory */ } },
  };
})();

/* =====================================================================
   TOASTS
   ===================================================================== */
const toastBox = $('#toasts');
function toast({ title, desc = '', tone = 'ok', action = null, duration = 4200 }) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  const iconName = tone === 'ok' ? 'circle-check' : tone === 'warn' ? 'circle-alert' : 'info';
  el.innerHTML = `${ic(iconName, tone)}<div class="body"><div class="t">${esc(title)}</div>${desc ? `<div class="d">${esc(desc)}</div>` : ''}</div>${action ? `<button class="btn btn-outline btn-sm" type="button">${esc(action.label)}</button>` : ''}<button class="btn btn-ghost btn-icon btn-sm" type="button" aria-label="Закрыть" style="margin:-4px -4px 0 0">${ic('x', 'i-sm')}</button>`;
  toastBox.append(el);
  while (toastBox.children.length > 3) toastBox.firstElementChild.remove();
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('show')));
  let timer; let remaining = duration; let started = Date.now();
  const close = () => { clearTimeout(timer); el.classList.add('hide'); el.classList.remove('show'); setTimeout(() => el.remove(), 200); };
  const arm = () => { started = Date.now(); timer = setTimeout(close, remaining); };
  el.addEventListener('mouseenter', () => { clearTimeout(timer); remaining -= Date.now() - started; });
  el.addEventListener('mouseleave', arm);
  const btns = el.querySelectorAll('button');
  if (action) btns[0].addEventListener('click', () => { action.fn(); close(); });
  btns[btns.length - 1].addEventListener('click', close);
  arm();
  return close;
}

/* =====================================================================
   THEME: mode (light / dark / system), preset, density
   ===================================================================== */
const root = document.documentElement;
const PRESETS = [{ id: 'slate', name: 'Aikyn' }, { id: 'tangerine', name: 'Мандарин' }];
const theme = {
  mode: prefs.get('mode', 'light'), preset: prefs.get('preset', 'slate'), density: prefs.get('density', 'comfortable'),
};
const sysDark = matchMedia('(prefers-color-scheme: dark)');
function applyTheme() {
  root.classList.add('no-tr');
  const dark = theme.mode === 'dark' || (theme.mode === 'system' && sysDark.matches);
  root.classList.toggle('dark', dark);
  root.setAttribute('data-theme-preset', theme.preset);
  root.setAttribute('data-density', theme.density);
  $('#modeIcon').setAttribute('href', dark ? '#i-sun' : '#i-moon');
  $('#modeBtn').setAttribute('aria-label', dark ? 'Светлая тема' : 'Тёмная тема');
  if (!PRESETS.some(p => p.id === theme.preset)) theme.preset = 'slate';
  $('#presetLbl').textContent = PRESETS.find((p) => p.id === theme.preset).name;
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('no-tr')));
  document.dispatchEvent(new CustomEvent('themechange'));
}
function setTheme(patch) { Object.assign(theme, patch); for (const k in patch) prefs.set(k, patch[k]); applyTheme(); }
sysDark.addEventListener?.('change', () => theme.mode === 'system' && applyTheme());
window.__setTheme = (mode) => setTheme({ mode });
const noTr = document.createElement('style');
noTr.textContent = 'html.no-tr *, html.no-tr *::before, html.no-tr *::after { transition: none !important; }';
document.head.append(noTr);

/* =====================================================================
   LAYERS: popovers, menus, dialogs, drawers, palette
   One stack; Esc closes the top layer; focus is trapped in modal layers
   and returned to the trigger on close.
   ===================================================================== */
const layers = [];
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
function openLayer({ el, scrim = false, trigger = document.activeElement, onClose, modal = false, focus = true, anim = true }) {
  const layer = { el, trigger, onClose, modal, scrimEl: null };
  if (scrim) {
    const s = document.createElement('div'); s.className = 'layer-scrim';
    s.addEventListener('click', () => closeLayer(layer));
    document.body.append(s); layer.scrimEl = s;
    requestAnimationFrame(() => s.classList.add('open'));
  }
  document.body.append(el);
  layers.push(layer);
  if (trigger && trigger.setAttribute && trigger.hasAttribute('aria-expanded')) trigger.setAttribute('aria-expanded', 'true');
  if (anim) requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('open'))); else el.classList.add('open');
  if (focus) {
    if (modal && !el.hasAttribute('tabindex')) el.tabIndex = -1;
    const target = el.querySelector('[data-autofocus]') || (modal ? el : el.querySelector(FOCUSABLE));
    setTimeout(() => (target || el).focus({ preventScroll: true }), anim ? 30 : 0);
  }
  return layer;
}
function closeLayer(layer = layers[layers.length - 1], { restore = true } = {}) {
  if (!layer) return;
  const i = layers.indexOf(layer); if (i < 0) return;
  if (layer.custom) { layer.custom(); return; }
  layers.splice(i, 1);
  const { el, scrimEl, trigger, onClose } = layer;
  el.classList.remove('open');
  if (scrimEl) scrimEl.classList.remove('open');
  const done = () => { el.remove(); scrimEl?.remove(); };
  if (reduced()) done(); else setTimeout(done, el.classList.contains('drawer') ? 380 : 200);
  if (trigger?.setAttribute && trigger.hasAttribute('aria-expanded')) trigger.setAttribute('aria-expanded', 'false');
  onClose?.();
  if (restore && trigger && document.contains(trigger)) trigger.focus({ preventScroll: true });
}
const closeAllPopovers = () => { for (let i = layers.length - 1; i >= 0; i--) if (!layers[i].modal) closeLayer(layers[i], { restore: false }); };
document.addEventListener('keydown', (e) => {
  const top = layers[layers.length - 1];
  if (!top) return;
  if (e.key === 'Escape') { e.preventDefault(); closeLayer(top); return; }
  if (e.key === 'Tab' && top.modal) {
    const f = $$(FOCUSABLE, top.el).filter((n) => n.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (!f.includes(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});
document.addEventListener('pointerdown', (e) => {
  const top = layers[layers.length - 1];
  if (!top || top.modal || top.scrimEl) return;
  if (top.el.contains(e.target) || top.trigger?.contains?.(e.target)) return;
  closeLayer(top, { restore: false });
});

/* Anchor a floating element to a trigger; flips when it would overflow */
function place(el, anchor, placement = 'bottom-start', gap = 6) {
  const r = anchor.getBoundingClientRect();
  el.style.left = '0px'; el.style.top = '0px';
  const w = el.offsetWidth, h = el.offsetHeight, vw = innerWidth, vh = innerHeight;
  let [side, align] = placement.split('-');
  if (side === 'bottom' && r.bottom + gap + h > vh - 8 && r.top - gap - h > 8) side = 'top';
  if (side === 'right' && r.right + gap + w > vw - 8) side = 'left';
  let x, y;
  if (side === 'bottom' || side === 'top') {
    y = side === 'bottom' ? r.bottom + gap : r.top - gap - h;
    x = align === 'end' ? r.right - w : r.left;
  } else {
    x = side === 'right' ? r.right + gap : r.left - gap - w;
    y = align === 'end' ? r.bottom - h : r.top;
  }
  x = clamp(x, 8, vw - w - 8); y = clamp(y, 8, vh - h - 8);
  el.style.left = x + 'px'; el.style.top = y + 'px';
  const ox = side === 'left' ? 'right' : side === 'right' ? 'left' : (align === 'end' ? 'right' : 'left');
  const oy = side === 'top' ? 'bottom' : side === 'bottom' ? 'top' : (align === 'end' ? 'bottom' : 'top');
  el.style.transformOrigin = `${oy} ${ox}`;
}

/* Dropdown menu with roving focus */
function openMenu(anchor, items, { placement = 'bottom-start', label = 'Menu', width } = {}) {
  if (anchor.getAttribute('aria-expanded') === 'true') { closeAllPopovers(); return; }
  closeAllPopovers();
  const el = document.createElement('div');
  el.className = 'pop'; el.setAttribute('role', 'menu'); el.setAttribute('aria-label', label);
  if (width) el.style.minWidth = width + 'px';
  el.innerHTML = items.map((it, i) => {
    if (it.sep) return '<div class="menu-sep" role="separator"></div>';
    if (it.heading) return `<div class="menu-label">${esc(it.heading)}</div>`;
    if (it.html) return it.html;
    const role = it.checked !== undefined ? 'menuitemradio' : 'menuitem';
    return `<button class="menu-item ${it.danger ? 'danger' : ''}" type="button" role="${role}" ${it.checked !== undefined ? `aria-checked="${!!it.checked}"` : ''} data-i="${i}" tabindex="-1">${it.lead || (it.icon ? ic(it.icon) : '')}<span>${esc(it.label)}</span>${it.sc ? `<span class="sc">${esc(it.sc)}</span>` : ''}${it.checked ? `<span class="check">${ic('check', 'i-sm')}</span>` : ''}</button>`;
  }).join('');
  el.addEventListener('click', (e) => {
    const b = e.target.closest('.menu-item'); if (!b) return;
    const it = items[+b.dataset.i];
    closeLayer(layer, { restore: !it.keepFocusAway });
    it.action?.();
  });
  el.addEventListener('keydown', (e) => {
    const list = $$('.menu-item', el); const i = list.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
    if (e.key === 'Home') { e.preventDefault(); list[0].focus(); }
    if (e.key === 'End') { e.preventDefault(); list[list.length - 1].focus(); }
    if (e.key === 'Tab') { closeLayer(layer, { restore: false }); }
  });
  const layer = openLayer({ el, trigger: anchor, anim: true, focus: false });
  place(el, anchor, placement);
  const first = el.querySelector('.menu-item'); if (first) setTimeout(() => first.focus({ preventScroll: true }), 10);
  return layer;
}

/* Generic popover with arbitrary content */
function openPopover(anchor, html, { placement = 'bottom-start', width = 320, label = 'Details', onMount } = {}) {
  closeAllPopovers();
  const el = document.createElement('div');
  el.className = 'pop'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', label);
  el.style.width = width + 'px'; el.tabIndex = -1; el.innerHTML = html;
  const layer = openLayer({ el, trigger: anchor, focus: false });
  place(el, anchor, placement);
  onMount?.(el, layer);
  setTimeout(() => el.focus({ preventScroll: true }), 10);
  return layer;
}

/* Modal dialog */
function openDialog({ title, desc = '', body, foot, onSubmit, width = 520, onMount, trigger }) {
  const el = document.createElement('form');
  el.className = 'dialog'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-labelledby', 'dlg-title'); el.noValidate = true;
  el.style.width = `min(${width}px, calc(100vw - 24px))`;
  el.innerHTML = `<div class="dialog-head"><h2 id="dlg-title">${esc(title)}</h2>${desc ? `<p>${esc(desc)}</p>` : ''}</div>
    <button class="btn btn-ghost btn-icon btn-sm x" type="button" data-close aria-label="Закрыть">${ic('x')}</button>
    <div class="dialog-body">${body}</div>${foot !== false ? `<div class="dialog-foot">${foot || ''}</div>` : ''}`;
  const layer = openLayer({ el, scrim: true, modal: true, trigger });
  el.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeLayer(layer); });
  bindForm(el, () => onSubmit?.(el, layer));
  onMount?.(el, layer);
  return layer;
}

/* Right-side drawer (bottom sheet on phones) */
function openDrawer({ label, html, onMount, trigger }) {
  const el = document.createElement('aside');
  el.className = 'drawer'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', label);
  el.innerHTML = html;
  const layer = openLayer({ el, scrim: true, modal: true, trigger });
  el.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) closeLayer(layer); });
  onMount?.(el, layer);
  return layer;
}

/* Forms: a sandboxed iframe blocks native submission before the submit
   event fires, so every form submits from its [data-submit] button click or
   Enter in a field. Keep <form novalidate> for semantics only. */
function bindForm(form, handler) {
  form.addEventListener('submit', (e) => e.preventDefault());
  form.addEventListener('click', (e) => { const b = e.target.closest('[data-submit]'); if (b && !b.disabled && form.contains(b)) { e.preventDefault(); handler(b); } });
  form.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    if (!e.target.matches?.('input:not([type="checkbox"]):not([type="radio"]):not([type="button"])')) return;
    e.preventDefault();
    const b = form.querySelector('[data-submit]'); if (b && !b.disabled) handler(b);
  });
}


const ROUTES = {
  overview: { title: 'Новая проверка', group: 'Анализ видео' },
  results: { title: 'Результаты', group: 'Анализ видео' },
  rules: { title: 'Нормативная база', group: 'Рабочее пространство' },
  guide: { title: 'Как это работает', group: 'Рабочее пространство' },
  settings: { title: 'Настройки', group: 'Рабочее пространство' },
};
const VIEWS = {}; // name -> { init(), enter(sub), inited }
const HOME = Object.keys(ROUTES)[0]; // first route is the landing view
const groupHome = (g) => Object.keys(ROUTES).find((k) => ROUTES[k].group === g) || HOME;
let current = null;
let memHash = '';
const embedded = (() => { try { return window.self !== window.top; } catch (e) { return true; } })();
const readHash = () => { let h = ''; try { h = location.hash; } catch (e) { /* opaque origin */ } return (memHash || h || '').replace(/^#\/?/, ''); };
/* History API instead of location.hash: assigning the hash counts as a
   navigation inside a sandboxed (opaque-origin) iframe and gets blocked.
   Embedded demos use replaceState so the host page's Back button still
   leaves the page instead of stepping through console views. */
function navigate(path) {
  memHash = '#/' + path;
  try { history[embedded ? 'replaceState' : 'pushState'](null, '', memHash); } catch (e) { /* keep in memory */ }
  route();
}
function route() {
  const [name, sub] = readHash().split('/');
  const view = ROUTES[name] ? name : HOME;
  const section = $(`.view[data-page="${view}"]`);
  const changed = current !== view;
  if (changed) {
    $$('.view').forEach((v) => { v.hidden = v !== section; });
    $$('.sb-item').forEach((a) => { if (a.dataset.view === view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    $('#crumbGroup').textContent = ROUTES[view].group;
    $('#crumbGroup').setAttribute('href', `#/${groupHome(ROUTES[view].group)}`);
    $('#crumbPage').textContent = ROUTES[view].title;
    document.title = `${ROUTES[view].title} · ${SITE.product}`;
    const v = VIEWS[view];
    if (v && !v.inited) { v.inited = true; v.init?.(); }
    section.classList.remove('enter'); void section.offsetWidth; section.classList.add('enter');
    const main = $('#main');
    if (isMobile()) window.scrollTo({ top: 0 }); else main.scrollTop = 0;
    if (current !== null) $('.page-title', section)?.focus({ preventScroll: true });
    current = view;
    closeAllPopovers();
  }
  if (isMobile() && sbLayer) { setSidebar(false); $('.page-title', section)?.focus({preventScroll:true}); }
  VIEWS[view]?.enter?.(sub, changed);
}
const syncFromUrl = () => { try { memHash = location.hash; } catch (e) { /* noop */ } route(); };
window.addEventListener('popstate', syncFromUrl);
window.addEventListener('hashchange', syncFromUrl);
/* Intercept in-page links so they never resolve against a parent URL */
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href^="#"]');
  if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const href = a.getAttribute('href');
  e.preventDefault();
  if (a.hasAttribute('data-skip')) { $('.view:not([hidden]) .page-title')?.focus(); return; }
  if (href.startsWith('#/')) navigate(href.slice(2));
});

/* =====================================================================
   SIDEBAR: expanded / rail on desktop, drawer on phones
   ===================================================================== */
function setSidebar(open) {
  const trig = $('#sbTrigger');
  if (isMobile()) {
    if (open && !sbLayer) {
      root.setAttribute('data-sidebar', 'open');
      const s = document.createElement('div'); s.className = 'layer-scrim'; s.id = 'sbScrim'; s.style.zIndex = 74;
      s.addEventListener('click', () => setSidebar(false));
      document.body.append(s); requestAnimationFrame(() => s.classList.add('open'));
      sbLayer = { el: $('#sidebar'), trigger: trig, modal: true, custom: () => { setSidebar(false); trig.focus(); } };
      layers.push(sbLayer);
      trig.setAttribute('aria-expanded', 'true');
      setTimeout(() => { if(sbLayer) $('.sb-item[aria-current]')?.focus({ preventScroll: true }); }, 80);
    } else if (!open && sbLayer) {
      const i = layers.indexOf(sbLayer); if (i >= 0) layers.splice(i, 1); sbLayer = null;
      root.removeAttribute('data-sidebar');
      const s = $('#sbScrim'); if (s) { s.classList.remove('open'); setTimeout(() => s.remove(), 240); }
      trig.setAttribute('aria-expanded', 'false');
    }
    return;
  }
  const tablet = matchMedia('(max-width: 1023px)').matches;
  if (tablet) { if (open) root.setAttribute('data-sidebar', 'open'); else root.removeAttribute('data-sidebar'); }
  else { if (open) root.removeAttribute('data-sidebar'); else root.setAttribute('data-sidebar', 'rail'); prefs.set('rail', !open); }
  trig.setAttribute('aria-expanded', String(open));
}
let sbLayer = null;
const sidebarOpen = () => {
  if (isMobile()) return root.getAttribute('data-sidebar') === 'open';
  if (matchMedia('(max-width: 1023px)').matches) return root.getAttribute('data-sidebar') === 'open';
  return root.getAttribute('data-sidebar') !== 'rail';
};
$('#sbTrigger').addEventListener('click', () => setSidebar(!sidebarOpen()));
if (!isMobile() && !matchMedia('(max-width: 1023px)').matches && prefs.get('rail', false)) root.setAttribute('data-sidebar', 'rail');
matchMedia('(max-width: 767px)').addEventListener?.('change', () => { if (sbLayer) setSidebar(false); root.removeAttribute('data-sidebar'); $('#sbTrigger').setAttribute('aria-expanded', String(sidebarOpen())); observeTop(); });

/* Header gains a hairline + backdrop once content scrolls under it */
let topIO;
function observeTop() {
  topIO?.disconnect();
  if (!('IntersectionObserver' in window)) return;
  topIO = new IntersectionObserver(([e]) => $('#topbar').classList.toggle('scrolled', !e.isIntersecting), { root: isMobile() ? null : $('#main'), threshold: 0 });
  topIO.observe($('#topSentinel'));
}


function openPalette() {
  if (layers.some((l) => l.el.classList.contains('palette'))) return;
  closeAllPopovers();
  const el = document.createElement('div');
  el.className = 'palette'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', 'Быстрый переход');
  el.innerHTML = `<div class="palette-in">${ic('search')}<input type="text" placeholder="Найти раздел или действие" aria-label="Поиск" role="combobox" aria-expanded="true" aria-controls="pal-list" aria-autocomplete="list" data-autofocus autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div>
    <div class="palette-list" id="pal-list" role="listbox" aria-label="Результаты поиска"></div>
    <div class="palette-foot"><span><kbd>${ic('arrow-up')}</kbd><kbd>${ic('arrow-down')}</kbd>Выбрать</span><span><kbd>${ic('corner-down-left')}</kbd>Открыть</span><span class="hide-sm" style="margin-left:auto">${ic('command', 'i-sm')} ${esc(SITE.product)}</span></div>`;
  const input = el.querySelector('input'); const list = el.querySelector('.palette-list');
  const all = paletteCommands();
  let shown = []; let sel = 0;
  const render = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) shown = all.filter((c) => !c.account && !c.task).concat(all.filter((c) => c.account).slice(0, 4));
    else {
      shown = all.map((c) => {
        const l = c.label.toLowerCase(); const k = (c.kw || '').toLowerCase();
        const s = l.startsWith(q) ? 3 : l.split(/\s+/).some((w) => w.startsWith(q)) ? 2 : (l.includes(q) || k.includes(q)) ? 1 : 0;
        return { c, s };
      }).filter((x) => x.s).sort((a, b) => b.s - a.s).map((x) => x.c).slice(0, 14);
      const order = ['Разделы', 'Действия'];
      shown.sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
    }
    sel = clamp(sel, 0, Math.max(0, shown.length - 1));
    if (!shown.length) { list.innerHTML = `<div class="palette-empty">Ничего не найдено. Попробуйте «проверка» или «демо».</div>`; input.removeAttribute('aria-activedescendant'); return; }
    let g = ''; let html = '';
    shown.forEach((c, i) => {
      if (c.group !== g) { g = c.group; html += `<div class="palette-group" role="presentation">${g}</div>`; }
      html += `<button type="button" class="palette-item" role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === sel}" tabindex="-1">${c.lead || ic(c.icon)}<span>${esc(c.label)}</span>${c.sub ? `<span class="sub">${esc(c.sub)}</span>` : ''}</button>`;
    });
    list.innerHTML = html;
    input.setAttribute('aria-activedescendant', 'pal-' + sel);
  };
  const move = (d) => { if (!shown.length) return; sel = (sel + d + shown.length) % shown.length; $$('.palette-item', list).forEach((b) => b.setAttribute('aria-selected', String(+b.dataset.i === sel))); input.setAttribute('aria-activedescendant', 'pal-' + sel); $('#pal-' + sel)?.scrollIntoView({ block: 'nearest' }); };
  const run = (i) => { const c = shown[i]; if (!c) return; closeLayer(layer, { restore: false }); c.run(); };
  input.addEventListener('input', () => { sel = 0; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); run(sel); }
  });
  list.addEventListener('click', (e) => { const b = e.target.closest('.palette-item'); if (b) run(+b.dataset.i); });
  list.addEventListener('pointermove', (e) => { const b = e.target.closest('.palette-item'); if (b && +b.dataset.i !== sel) { sel = +b.dataset.i; $$('.palette-item', list).forEach((x) => x.setAttribute('aria-selected', String(x === b))); } });
  render();
  const layer = openLayer({ el, scrim: true, modal: true, anim: false });
  layer.scrimEl.style.transition = 'none';
}
$('#searchBtn').addEventListener('click', openPalette);


/* Aikyn Vision application. API integration follows 04_frontend_demo.md.
   API key, files, evidence and job state stay in memory; only theme is persisted. */
const SITE = { product: 'Aikyn Vision' };
const MAX_WAIT_MS = 300000;
const POLL_MS = 1600;
const state = {
  phase: 'idle', file: null, videoUrl: null, duration: null,
  jobId: null, jobBase: null, result: null, error: '', mode: null,
  selected: 0, generation: 0, controller: null, timer: null, clockTimer: null, startedAt: 0, deadline: 0, localDemo: false,
  ready: false, readyMode: null, readyController: null, readyGeneration: 0,
  pollErrors: 0, pollMessage: '', localSessionPromise: null,
};
const active = () => ['uploading', 'processing'].includes(state.phase);
const hasJob = () => Boolean(state.jobId && !state.localDemo);
const announce = (text) => { $('#liveStatus').textContent = text; };
const seconds = (n) => {
  if (!Number.isFinite(n) || n < 0) return 'Время не указано';
  const millis = Math.round(n * 1000);
  const whole = Math.floor(millis / 1000);
  const base = `${String(Math.floor(whole / 60)).padStart(2,'0')}:${String(whole % 60).padStart(2,'0')}`;
  const fraction = String(millis % 1000).padStart(3,'0').replace(/0+$/, '');
  return fraction ? `${base}.${fraction}` : base;
};
const fileSize = (n) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(n / 1048576) + ' МБ';
function safeSource(raw) {
  if (typeof raw !== 'string' || raw.length > 4096) return null;
  try { const u = new URL(raw); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; }
}
async function bootstrapLocalSession() {
  if (!['localhost', '127.0.0.1', '[::1]'].includes(location.hostname) || $('#apiBase').value.trim() || $('#apiKey').value.trim()) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('/local-session', { headers: { 'X-Local-Bootstrap': '1' }, signal: controller.signal, cache: 'no-store', credentials: 'same-origin', redirect: 'error' });
    if (!response.ok) return;
    const data = await response.json();
    if (typeof data.api_key !== 'string' || data.api_key.length < 24 || data.api_key.length > 512 || $('#apiBase').value.trim() || $('#apiKey').value.trim()) return;
    $('#apiKey').value = data.api_key;
    $('#connectionNoteText').textContent = 'Локальное подключение настроено. Выберите видео и нажмите «Начать анализ».';
    $('#sidebarStatus').textContent = 'Готов к загрузке';
    readyMessage('Локальное подключение настроено автоматически. Ключ хранится только в памяти этой страницы.');
  } catch { /* Remote/custom installations can still enter their API key in Settings. */ }
  finally { clearTimeout(timer); }
}
function getConnection() {
  const raw = $('#apiBase').value.trim();
  const key = $('#apiKey').value.trim();
  let url;
  try { url = new URL(raw || location.origin); } catch { throw new Error('Укажите полный адрес сервера, например http://localhost:8080.'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Нужен адрес HTTP или HTTPS без логина, пароля, параметров и фрагмента.');
  if (location.protocol === 'https:' && url.protocol === 'http:' && !['localhost','127.0.0.1','[::1]'].includes(url.hostname)) throw new Error('Для подключения с HTTPS-страницы нужен HTTPS-адрес API.');
  return { base: url.href.replace(/\/+$/, ''), key };
}
function invalidateReadiness() {
  state.readyGeneration++;
  state.readyController?.abort();
  state.readyController = null;
  $('#checkReady').disabled = false;
  $('#checkReady').classList.remove('is-loading');
  state.ready = false;
  state.readyMode = null;
  $('#readyStatus').className = 'ready-status';
  $('#readyStatus').textContent = 'Настройки изменены. Проверьте готовность сервиса.';
  updateConnection();
}
function updateConnection() {
  const testing = ['demo', 'test'].includes(state.readyMode);
  $('#sidebarStatus').textContent = state.ready ? (testing ? 'API: тестовый режим' : state.readyMode === 'real' ? 'Сервис готов' : 'API доступен') : 'API не проверен';
  $('#sidebarDot').classList.toggle('ready', state.ready);
  $('#connectionNote').classList.toggle('ok', state.ready);
  $('#connectionNoteText').textContent = state.ready ? (testing ? 'Подключён тестовый обработчик. Его ответы не подтверждают наличие или отсутствие нарушений.' : state.readyMode === 'real' ? 'Локальный анализатор готов. Выберите MOV и запустите проверку.' : 'API доступен, но режим модели не подтверждён сервером.') : 'Откройте настройки, введите локальный ключ и проверьте готовность анализатора.';
}
const HTTP_MESSAGES = {
  400: 'Сервер не смог принять запрос. Проверьте файл и настройки подключения.',
  401: 'Ключ отсутствует или неверен. Проверьте ключ в настройках.',
  403: 'У этого ключа нет доступа к операции.',
  404: 'Задание или маршрут не найден. Проверьте адрес сервера и идентификатор задания.',
  413: 'Файл превышает допустимый сервером размер. Выберите файл меньшего размера.',
  415: 'Сервер принимает MOV. Выберите видео с расширением .mov.',
  422: 'Видео пустое, повреждено или не поддерживается сервером.',
  429: 'Очередь занята. Подождите и повторите действие позже.',
  503: 'Модель, каталог или обработчик ещё не готовы. Проверьте готовность сервиса.',
};
class ApiError extends Error { constructor(message, status = 0, retryable = false) { super(message); this.status = status; this.retryable = retryable; } }
function serverErrorMessage(data) {
  const message = typeof data?.error === 'string' ? data.error :
    typeof data?.error?.message === 'string' ? data.error.message :
    typeof data?.detail === 'string' ? data.detail : '';
  return message.slice(0, 2000);
}
async function request(path, config, { method = 'GET', body, signal, timeout = 18000, expectedStatus } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort(); else signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const clock = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  try {
    const headers = { Accept: 'application/json' };
    if (config.key) headers['X-API-Key'] = config.key;
    const response = await fetch(config.base + path, { method, headers, body, signal: controller.signal, cache: 'no-store', credentials: 'omit', redirect: 'error' });
    const text = await response.text();
    if (text.length > 32 * 1048576) throw new ApiError('Ответ сервера слишком большой для безопасного отображения.');
    let data;
    try { data = text ? JSON.parse(text) : null; } catch { if (response.ok) throw new ApiError('Сервер вернул повреждённый ответ: ожидался JSON.'); }
    if (!response.ok) {
      const extra = serverErrorMessage(data);
      throw new ApiError((HTTP_MESSAGES[response.status] || `Ошибка сервера (HTTP ${response.status}).`) + (extra ? ` Сообщение сервера: ${extra}` : ''), response.status, [408,429,502,503,504].includes(response.status));
    }
    if (expectedStatus && response.status !== expectedStatus) throw new ApiError(`Неожиданный HTTP-статус ${response.status}. Ожидался ${expectedStatus}. Запрос повторно не отправлен.`);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ApiError('Сервер вернул повреждённый ответ: ожидался объект JSON.');
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal?.aborted) throw e;
    if (timedOut) throw new ApiError('Сервер не ответил вовремя. Проверьте соединение и состояние задания.', 0, true);
    throw new ApiError('Не удалось связаться с сервером. Проверьте адрес, доступность API и разрешение CORS.', 0, true);
  } finally { clearTimeout(clock); signal?.removeEventListener('abort', abort); }
}
async function checkReady() {
  if (active()) { toast({ title:'Дождитесь завершения текущего запроса', tone:'warn' }); return; }
  let config;
  try { config = getConnection(); } catch(e) { readyMessage(e.message, false); return; }
  state.readyController?.abort();
  const controller = new AbortController(); state.readyController = controller;
  const generation = ++state.readyGeneration;
  const button = $('#checkReady'); button.disabled = true;
  readyMessage('Проверяем связь сайта с локальным анализатором…');
  try {
    const data = await request('/readyz', config, { signal: controller.signal });
    if (generation !== state.readyGeneration) return;
    const status = String(data.status || '').toLowerCase();
    if (data.ready === false || !((data.ready === true) || ['ready','ok','healthy'].includes(status))) throw new ApiError('Сервис отвечает, но не подтвердил готовность к анализу. Нужны ready: true или status: ready/ok/healthy от /readyz.');
    state.ready = true;
    state.readyMode = normalizeMode(data.mode);
    const testing = ['demo', 'test'].includes(state.readyMode);
    readyMessage(testing ? 'API готов в тестовом режиме. Ответы не являются реальной проверкой видео.' : state.readyMode === 'real' ? 'Сервис сообщил о готовности через /readyz. Можно запускать анализ.' : 'API отвечает, но режим модели не указан. Реальное происхождение результатов не подтверждено.', true);
    updateConnection();
    toast({ title: testing ? 'Подключён тестовый API' : state.readyMode === 'real' ? 'Сервис сообщил о готовности' : 'Режим модели не подтверждён', tone: testing || !state.readyMode ? 'warn' : 'ok' });
  } catch(e) {
    if (generation !== state.readyGeneration) return;
    state.ready = false; state.readyMode = null; readyMessage(e.message, false); updateConnection();
  } finally { if (generation === state.readyGeneration) { button.disabled = false; state.readyController = null; } }
}
function readyMessage(text, ok = null) {
  const el = $('#readyStatus'); el.textContent = text;
  el.className = 'ready-status' + (ok === true ? ' good' : ok === false ? ' bad' : '');
}
function stopWork() {
  state.generation++;
  state.controller?.abort(); state.controller = null;
  clearTimeout(state.timer); state.timer = null;
  clearTimeout(state.clockTimer); state.clockTimer = null;
}
function startElapsedClock() {
  clearTimeout(state.clockTimer);
  const tick = () => {
    if (!active() || !state.startedAt) return;
    const el = $('#processingElapsed');
    if (el) el.textContent = seconds(Math.floor(Math.max(0, Date.now() - state.startedAt) / 1000));
    state.clockTimer = setTimeout(tick, 1000);
  };
  tick();
}
function releaseVideo() {
  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = null; state.duration = null;
}
function clearJob() {
  stopWork(); state.jobId = null; state.jobBase = null; state.result = null;
  state.error = ''; state.mode = null; state.selected = 0; state.phase = 'idle'; state.localDemo = false; state.startedAt = 0;
  state.pollErrors = 0; state.pollMessage = '';
  $('#eventCount').hidden = true; $('#resultsDescription').textContent = 'События и доказательные кадры текущего задания.';
  renderResults(); renderRules();
}
function newCheck() {
  clearJob(); releaseVideo(); state.file = null; $('#fileInput').value = '';
  showFileError(''); renderUpload(); navigate('overview');
}
function showFileError(message) {
  $('#fileError').textContent = message; $('#fileError').hidden = !message;
}
function chooseFiles(files) {
  if (active()) { toast({title:'Проверка уже выполняется',desc:'Завершите ожидание перед выбором другого файла.',tone:'warn'}); return; }
  // Rejecting a newly chosen file also clears the old result, preventing accidental attribution.
  clearJob(); releaseVideo(); state.file = null;
  if (files.length !== 1) { showFileError('Выберите ровно один MOV-файл.'); renderUpload(); return; }
  const file = files[0];
  if (!/\.mov$/i.test(file.name)) { showFileError('Нужен файл с расширением .mov.'); renderUpload(); return; }
  if (!file.size) { showFileError('Файл пустой. Выберите другое видео.'); renderUpload(); return; }
  // No invented browser size ceiling: the API remains the authority and returns HTTP 413.
  state.file = file; state.videoUrl = URL.createObjectURL(file);
  showFileError(''); renderUpload(); announce('Видео выбрано. ' + file.name);
}
function renderUpload() {
  for (const id of ['apiBase','apiKey','clearKey']) $('#'+id).disabled = active();
  const file = state.file; $('#dropzone').hidden = Boolean(file);
  $('#selectedFile').hidden = !file;
  $('#chooseFile').disabled = active();
  if (!file) { $('#selectedFile').replaceChildren(); return; }
  $('#selectedFile').innerHTML = `<div class="selected-wrap"><div class="file-row"><span class="file-symbol">${ic('video')}</span><div><div class="file-name">${esc(file.name)}</div><div class="file-meta">${esc(fileSize(file.size))} · MOV · На устройстве</div></div><button class="btn btn-ghost btn-icon" type="button" data-action="remove-file" aria-label="Удалить выбранный файл" ${active()?'disabled':''}>${ic('x')}</button></div><div class="video-wrap"><video id="localVideo" controls preload="metadata" playsinline aria-label="Предпросмотр выбранного видео"></video></div><p id="playerHint" class="player-hint">Предпросмотр зависит от поддержки MOV вашим браузером. Даже без воспроизведения файл можно отправить на анализ.</p><div class="selected-actions"><button class="btn btn-outline" data-action="replace-file" type="button" ${active()?'disabled':''}>Другой файл</button><button class="btn btn-primary" data-action="analyze" type="button" ${active()?'disabled':''}>${ic('play')}Начать анализ</button></div></div>`;
  const video = $('#localVideo'); video.src = state.videoUrl;
  const capturedUrl = state.videoUrl;
  video.addEventListener('loadedmetadata', () => { if (state.videoUrl !== capturedUrl) return; state.duration = Number.isFinite(video.duration) ? video.duration : null; });
  video.addEventListener('error', () => { if(state.videoUrl === capturedUrl) $('#playerHint').textContent = 'Браузер не воспроизводит этот MOV. Это не мешает загрузке на сервер и просмотру доказательных кадров.'; });
}
async function analyze() {
  if (active()) return;
  if (!state.file) { showFileError('Сначала выберите MOV-файл.'); navigate('overview'); return; }
  if (!$('#apiKey').value.trim() && state.localSessionPromise) await state.localSessionPromise;
  if (active() || !state.file) return;
  let config;
  try { config = getConnection(); if (!config.key) throw new Error('Введите ключ доступа в настройках.'); }
  catch(e) { readyMessage(e.message, false); navigate('settings'); $('#apiKey').focus(); return; }
  clearJob();
  const generation = state.generation;
  state.phase = 'uploading'; state.mode = null; state.jobBase = config.base; state.startedAt = Date.now(); state.deadline = state.startedAt + MAX_WAIT_MS;
  state.controller = new AbortController(); const signal = state.controller.signal;
  renderUpload(); renderResults(); startElapsedClock(); navigate('results'); announce('Видео передаётся серверу.');
  const form = new FormData(); form.append('file', state.file);
  try {
    const data = await request('/api/v1/analyze', config, { method:'POST', body:form, signal, timeout:90000, expectedStatus:202 });
    if (generation !== state.generation) return;
    if (typeof data.job_id !== 'string' || !data.job_id.trim() || data.job_id.length > 256 || data.status !== 'processing') throw new ApiError('Сервер не вернул корректные job_id и status: processing. Запрос повторно не отправлен.');
    state.jobId = data.job_id; state.mode = normalizeMode(data.mode); state.phase = 'processing';
    state.deadline = Date.now() + MAX_WAIT_MS;
    renderResults(); announce('Задание создано. Выполняется анализ видео.');
    poll(config, generation, signal);
  } catch(e) {
    if (generation !== state.generation || signal.aborted) return;
    const uncertain = !e.status;
    state.phase = 'error'; state.error = e.message + (uncertain ? ' Идентификатор задания не получен. Сервер мог принять файл; перед повторной загрузкой уточните состояние у команды.' : '');
    renderUpload(); renderResults(); announce('Не удалось начать проверку. Вердикта нет.');
  }
}
function normalizeMode(mode) { return ['real','demo','test'].includes(mode) ? mode : null; }
async function poll(config, generation, signal) {
  if (generation !== state.generation || signal.aborted) return;
  if (Date.now() >= state.deadline) {
    pauseJob('За 5 минут готовый ответ не получен. Нажмите «Запросить статус», чтобы продолжить без повторной загрузки видео.'); return;
  }
  try {
    const data = await request('/api/v1/jobs/' + encodeURIComponent(state.jobId), config, { signal, timeout:Math.min(18000, state.deadline - Date.now()) });
    if (generation !== state.generation) return;
    if (data.job_id !== state.jobId) throw new ApiError('Ответ содержит идентификатор другого задания. Результат не показан.');
    const previousMode = state.mode;
    const wasRetrying = Boolean(state.pollMessage);
    state.pollErrors = 0; state.pollMessage = '';
    if (Object.hasOwn(data,'mode')) state.mode = normalizeMode(data.mode);
    if (data.status === 'processing') {
      state.phase = 'processing'; if(previousMode !== state.mode || wasRetrying) renderResults();
      state.timer = setTimeout(() => poll(config, generation, signal), Math.min(POLL_MS, Math.max(0, state.deadline - Date.now())));
    } else if (data.status === 'done') {
      const result = validateResult(data);
      state.result = result; state.mode = normalizeMode(data.mode); state.phase = 'done'; state.controller = null;
      clearTimeout(state.clockTimer); state.clockTimer = null;
      renderUpload(); renderResults(); renderRules(); announce('Анализ завершён. ' + (data.verdict==='violation' ? 'Найден подозрительный эпизод.' : 'Сигналов не найдено.'));
    } else if (data.status === 'failed') {
      state.phase = 'error'; state.error = serverErrorMessage(data) || 'Сервер сообщил об ошибке анализа без подробностей.';
      state.controller = null; clearTimeout(state.clockTimer); state.clockTimer = null;
      renderUpload(); renderResults(); announce('Анализ завершился ошибкой. Результат не получен.');
    } else throw new ApiError('Неизвестный статус задания. Ожидались processing, done или failed.');
  } catch(e) {
    if (generation !== state.generation || signal.aborted) return;
    if (e.retryable && ++state.pollErrors <= 3 && Date.now() < state.deadline) {
      state.pollMessage = `Связь с сервером прервалась. Восстанавливаем автоматически (${state.pollErrors}/3)…`;
      renderResults();
      state.timer = setTimeout(() => poll(config, generation, signal), Math.min(POLL_MS * state.pollErrors, Math.max(0, state.deadline - Date.now())));
      return;
    }
    pauseJob(e.message);
  }
}
function pauseJob(message) {
  stopWork(); state.phase = 'paused'; state.error = message;
  renderUpload(); renderResults(); announce('Ожидание приостановлено. Идентификатор задания сохранён.');
}
function resumeJob() {
  if (active() || !hasJob()) return;
  let config;
  try { config = getConnection(); if (!config.key) throw new Error('Введите ключ доступа в настройках.'); if (config.base !== state.jobBase) throw new Error('Задание принадлежит другому серверу. Верните прежний адрес API, чтобы запросить его статус.'); }
  catch(e) { readyMessage(e.message, false); navigate('settings'); return; }
  stopWork(); const generation = state.generation;
  state.controller = new AbortController(); state.deadline = Date.now()+MAX_WAIT_MS; state.phase = 'processing'; state.error = '';
  state.pollErrors = 0; state.pollMessage = '';
  renderUpload(); renderResults(); startElapsedClock(); announce('Запрашиваем состояние существующего задания.');
  poll(config, generation, state.controller.signal);
}
function validateResult(data) {
  const invalid = () => { throw new ApiError('Повреждённый результат: поля ответа не соответствуют контракту. Вердикт не показан.'); };
  if (data.status !== 'done' || typeof data.job_id !== 'string' || !['violation','no_violation'].includes(data.verdict) || !Array.isArray(data.violations)) invalid();
  if ((data.verdict === 'no_violation' && data.violations.length) || (data.verdict === 'violation' && !data.violations.length) || data.violations.length > 500) invalid();
  const nonnegative = n => typeof n === 'number' && Number.isFinite(n) && n >= 0;
  for (const v of data.violations) {
    if (!v || typeof v.type !== 'string' || !v.type.trim() || v.type.length > 1000 || typeof v.description !== 'string' || v.description.length > 50000 || !nonnegative(v.timecode_sec) || !Array.isArray(v.evidence_frames) || v.evidence_frames.length < 1 || v.evidence_frames.length > 3) invalid();
    for (const frame of v.evidence_frames) {
      if (!frame || !nonnegative(frame.timestamp_sec) || typeof frame.image_base64 !== 'string' || frame.image_base64.length > 12*1048576 || !frame.image_base64.startsWith('/9j/') || frame.image_base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(frame.image_base64)) invalid();
    }
    if (v.rule != null && (typeof v.rule !== 'object' || Array.isArray(v.rule))) invalid();
  }
  if (data.analysis != null) {
    const a = data.analysis;
    if (typeof a !== 'object' || Array.isArray(a) || a.complete === false || a.timeline_covered === false) invalid();
    if (a.experimental === true && (a.complete !== true || a.timeline_covered !== true || !Number.isInteger(a.windows_total) || a.windows_total <= 0 || !Number.isInteger(a.windows_done) || a.windows_done !== a.windows_total)) invalid();
    for (const key of ['experimental', 'new_training', 'complete', 'timeline_covered']) if (a[key] != null && typeof a[key] !== 'boolean') invalid();
    for (const key of ['sample_fps', 'window_seconds', 'stride_seconds', 'elapsed_sec']) if (a[key] != null && !nonnegative(a[key])) invalid();
    for (const key of ['windows_total', 'windows_done']) if (a[key] != null && (!nonnegative(a[key]) || !Number.isInteger(a[key]))) invalid();
    if (a.localization != null && (typeof a.localization !== 'string' || a.localization.length > 100)) invalid();
    if (a.windows_total != null && a.windows_done != null && a.windows_done !== a.windows_total) invalid();
    if (a.limitations != null && (!Array.isArray(a.limitations) || a.limitations.length > 100 || a.limitations.some(s => typeof s !== 'string' || s.length > 10000))) invalid();
    if (a.review_questions != null) {
      if (!Array.isArray(a.review_questions) || a.review_questions.length > 500) invalid();
      for (const q of a.review_questions) if (!q || typeof q.type !== 'string' || !q.type.trim() || q.type.length > 1000 || !nonnegative(q.timecode_sec) || typeof q.message !== 'string' || !q.message.trim() || q.message.length > 10000) invalid();
    }
  }
  return data;
}
function modeBanner() {
  if (['demo','test'].includes(state.mode)) return `<div class="mode-notice">${ic('circle-alert')}<p><strong>${state.mode.toUpperCase()}: тестовый режим.</strong> ${state.mode === 'demo' ? 'Синтетические события и кадры. Это не анализ выбранного видео.' : 'Тестовый ответ сервера. Не является результатом реальной проверки.'}</p></div>`;
  if (state.phase !== 'idle' && !state.mode) return `<div class="mode-notice">${ic('info')}<p><strong>Режим не указан сервером.</strong> Реальное происхождение результата не подтверждено.</p></div>`;
  return '';
}
function jobMarkup() { return state.jobId ? `<div class="job-id" aria-label="Идентификатор задания">${esc(state.jobId)}</div>` : ''; }
function isApproximateTiming() { return state.result?.analysis?.localization === 'approximate_window'; }
function eventTime(n) { return (isApproximateTiming() ? '≈ ' : '') + seconds(n); }
function renderAnalysisSummary(analysis) {
  if (!analysis) return '';
  const facts = [];
  if (analysis.new_training === false) facts.push('Предобученная модель, без дообучения');
  if (Number.isInteger(analysis.windows_done) && Number.isInteger(analysis.windows_total)) facts.push(`Обработано фрагментов: ${analysis.windows_done} / ${analysis.windows_total}`);
  if (Number.isFinite(analysis.sample_fps)) facts.push(`Выборка: ${analysis.sample_fps} кадра/с`);
  if (Number.isFinite(analysis.window_seconds)) facts.push(`Фрагменты по ${analysis.window_seconds} с${Number.isFinite(analysis.stride_seconds) ? `, начало каждые ${analysis.stride_seconds} с` : ''}`);
  if (Number.isFinite(analysis.elapsed_sec)) facts.push(`Обработка на сервере: ${seconds(analysis.elapsed_sec)}`);
  const limitations = analysis.limitations || [];
  const approximate = analysis.localization === 'approximate_window';
  if (!facts.length && !limitations.length && !analysis.experimental && !approximate) return '';
  return `<details class="card analysis-summary"><summary>Сведения об анализе</summary><h2>${analysis.experimental ? 'Экспериментальный анализ' : 'Обработка видео'}</h2>${facts.length ? `<div class="analysis-facts">${facts.map(f => `<span>${esc(f)}</span>`).join('')}</div>` : ''}${approximate ? '<p><strong>Примерное время событий.</strong> Метка указывает на проверяемый фрагмент, а не на точное начало действия. Просмотрите контекст до и после неё. Время отдельного кадра указано по исходному видео.</p>' : ''}${analysis.complete && analysis.timeline_covered ? '<p>Обработаны все запланированные фрагменты по всей длительности видео. Использовалась выборка кадров: быстрые и плохо видимые действия могли быть пропущены.</p>' : ''}${limitations.length ? `<details><summary>Ограничения этой проверки (${limitations.length})</summary><ul>${limitations.map(s => `<li>${esc(s)}</li>`).join('')}</ul></details>` : ''}</details>`;
}
function renderReviewQuestions(analysis) {
  const questions = analysis?.review_questions || [];
  if (!questions.length) return '';
  const canSeek = Boolean(state.videoUrl && state.mode !== 'demo');
  return `<details class="card review-questions"><summary>Дополнительные наблюдения (${questions.length})</summary><p class="questions-intro">Наблюдения модели с таймкодами. Они не включены в найденные подозрительные эпизоды.</p><ul>${questions.map((q, i) => `<li><div class="question-heading"><h3>${esc(q.type)}</h3>${canSeek ? `<button class="btn btn-outline btn-sm mono" type="button" data-question-seek="${i}" aria-label="Открыть вопрос ${i + 1} на ${esc(eventTime(q.timecode_sec))}">${ic('play')}${esc(eventTime(q.timecode_sec))}</button>` : `<span class="badge mono">${esc(eventTime(q.timecode_sec))}</span>`}</div><p>${esc(q.message)}</p></li>`).join('')}</ul></details>`;
}
function renderResults() {
  const content = $('#resultContent');
  $('#resultsDescription').textContent = state.file && state.mode !== 'demo' ? state.file.name : 'События и доказательные кадры текущего задания.';
  if (state.phase === 'idle') {
    content.innerHTML = `<div class="empty-state">${ic('list-checks')}<h2>Здесь будет результат проверки</h2><p>Выберите MOV, запустите анализ и дождитесь ответа сервера. Или изучите интерфейс на отдельном синтетическом примере.</p><div class="empty-actions"><a class="btn btn-primary" href="#/overview">${ic('plus')}Выбрать видео</a><button class="btn btn-outline" type="button" data-demo="violation">Открыть демо</button></div></div>`; return;
  }
  if (active()) {
    const upload = state.phase === 'uploading';
    content.innerHTML = modeBanner() + `<div class="card processing-card"><div class="processing-orbit">${ic(upload ? 'upload' : 'activity')}</div><span class="step-label">${state.mode==='demo'?'ДЕМОНСТРАЦИЯ ИНТЕРФЕЙСА':'ПРОВЕРКА В ПРОЦЕССЕ'}</span><h2 style="margin-top:12px">${upload?'Передаём видео серверу':'Анализируем видео'}</h2><p>${upload?'Оставьте страницу открытой. После приёма файла сервер вернёт идентификатор задания.':'Автоматически ищем события, таймкоды и кадры. Результат появится здесь.'}</p><div class="wait-indicator" aria-hidden="true"><i></i></div><div class="stage-list"><span class="${upload?'active':''}">${ic(upload?'upload':'check')}Передача видео</span><span class="${!upload?'active':''}">${ic('activity')}Обработка</span><span>${ic('list-checks')}Результат</span></div>${state.startedAt ? '<p class="processing-time">Прошло с отправки: <strong id="processingElapsed" class="mono">' + seconds(Math.floor(Math.max(0, Date.now() - state.startedAt) / 1000)) + '</strong> · до 5 минут после загрузки</p>' : ''}${state.pollMessage ? '<p role="status" class="player-hint">' + esc(state.pollMessage) + '</p>' : ''}${jobMarkup()}<button class="btn btn-outline" type="button" data-action="pause">${upload?'Прекратить ожидание загрузки':'Прекратить ожидание'}</button><p class="player-hint">Это остановит ожидание в браузере. Серверная задача может продолжить работу.</p></div>`;
    return;
  }
  if (['error','paused'].includes(state.phase)) {
    const paused = state.phase === 'paused';
    content.innerHTML = modeBanner() + `<div class="empty-state error-state">${ic(paused?'link':'circle-alert')}<h2>${paused?'Ожидание приостановлено':'Не удалось завершить проверку'}</h2><p>${esc(state.error)}</p><span class="badge">Результат не получен</span>${jobMarkup()}<div class="empty-actions">${hasJob()?'<button class="btn btn-primary" type="button" data-action="resume">Запросить статус</button>':''}<a class="btn btn-outline" href="#/settings">Настройки подключения</a><button class="btn btn-outline" type="button" data-action="new">Новая проверка</button></div></div>`;
    return;
  }
  const result = state.result; if (!result) return;
  const events = result.violations; const violation = result.verdict === 'violation';
  $('#eventCount').textContent = events.length; $('#eventCount').hidden = !events.length;
  const analysis = result.analysis && typeof result.analysis === 'object' ? result.analysis : null;
  content.innerHTML = modeBanner() + `<div class="result-summary"><div class="verdict-icon ${violation?'':'clear'}">${ic(violation?'flag':'circle-check')}</div><div><h2>${violation?'Найден подозрительный эпизод':'Сигналов не найдено'}</h2><p>${violation?'Выберите таймкод, чтобы открыть эпизод в исходном видео.':'Анализ завершён. Подозрительные эпизоды не отмечены.'}</p></div><div class="summary-count"><b>${events.length}</b><span>событий в ответе</span></div></div><div class="job-strip"><span>Задание: <strong class="mono">${esc(result.job_id)}</strong></span><span>Режим: <strong>${state.mode === 'real'?'REAL':state.mode ? esc(state.mode.toUpperCase()):'не указан'}</strong></span>${analysis?'<button class="text-link" data-action="analysis-info" type="button" style="margin:0">Сведения об анализе</button>':''}</div>${renderAnalysisSummary(analysis)}${events.length?`<div class="timeline"><div class="timeline-labels"><span>СОБЫТИЯ НА ВРЕМЕННОЙ ШКАЛЕ</span><span>${state.mode==='demo'?'Тестовая запись':'От начала видео'}</span></div><div class="timeline-track" role="group" aria-label="Перейти к событию">${events.map((v,i)=>{const end = Math.max(state.duration || 0, ...events.map(x=>x.timecode_sec),1)*1.08;return `<button class="timeline-tick" type="button" data-select="${i}" data-time="${esc(eventTime(v.timecode_sec))}" style="left:${clamp(v.timecode_sec/end*100,2,98)}%" aria-label="Событие ${i+1}, ${esc(eventTime(v.timecode_sec))}" aria-pressed="${state.selected===i}"></button>`;}).join('')}</div></div><div class="result-layout"><div class="card event-list"><div class="list-heading"><h2>События</h2><span class="badge">${events.length}</span></div>${events.map((v,i)=>`<button class="event-item" type="button" data-select="${i}" aria-pressed="${state.selected===i}"><span class="event-num">${String(i+1).padStart(2,'0')}</span><span><b>${esc(v.type)}</b><span class="event-time">${esc(eventTime(v.timecode_sec))}</span></span>${ic('chevron-right')}</button>`).join('')}</div><div id="eventDetail" class="card"></div></div>`:`<div class="empty-state">${ic('shield-check')}<h2>Событий для просмотра нет</h2><p>Можно загрузить следующую запись.</p><button class="btn btn-outline" type="button" data-action="new">Проверить другое видео</button></div>`}${renderReviewQuestions(analysis)}<div class="review-note">${ic('info')}<p>Вывод системы требует проверки человеком и не является установлением виновности.</p></div>`;
  if (events.length) renderEvent();
}
function renderRule(rule) {
  if (!rule || typeof rule !== 'object') return `<div class="rule-card"><div class="rule-label">${ic('book')}Нормативное основание</div><p>Нормативное основание требует проверки. Сервер не передал подтверждённый источник для этого события.</p></div>`;
  const source = safeSource(rule.source_url);
  return `<div class="rule-card"><div class="rule-label">${ic('book')}${state.mode==='demo'?'Тестовое основание':'Источник для проверки основания'}${rule.id ? ' / '+esc(String(rule.id).slice(0,300)):''}</div><h3>${esc(typeof rule.document==='string'?rule.document:'Документ не указан сервером')}</h3><p>${esc(typeof rule.section==='string'?rule.section:'Раздел не указан сервером')}</p>${source?`<a class="text-link" href="${esc(source)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">Открыть первоисточник${ic('arrow-up-right')}</a>`:`<p>${state.mode==='demo'?'Ссылка отсутствует: учебный сценарий не ссылается на реальную норму.':'Безопасная ссылка на источник не передана сервером.'}</p>`}</div>`;
}
function renderEvent() {
  const event = state.result?.violations[state.selected]; if(!event || !$('#eventDetail')) return;
  const seekAvailable = Boolean(state.videoUrl && state.mode !== 'demo');
  $('#eventDetail').innerHTML = `<div class="detail-header"><div class="detail-eyebrow"><span>СОБЫТИЕ ${String(state.selected+1).padStart(2,'0')}${isApproximateTiming() ? ' · Примерное время' : ''}</span>${seekAvailable ? '<button class="btn btn-outline btn-sm mono" type="button" data-action="seek-video" aria-label="Перейти к времени события">' + esc(eventTime(event.timecode_sec)) + '</button>' : '<span class="badge mono">' + esc(eventTime(event.timecode_sec)) + '</span>'}</div><h2>${esc(event.type)}</h2><p>${esc(event.description)}</p>${seekAvailable?'<button class="btn btn-outline btn-sm" type="button" data-action="seek-video">'+ic('play')+'Открыть момент в видео</button>':''}</div><div class="evidence-section"><h3>${state.mode==='demo'?'Синтетические кадры':'Кадры для проверки'} <span class="muted">/ ${event.evidence_frames.length}</span></h3><div class="evidence-grid">${event.evidence_frames.map((frame,i)=>`<figure><button class="frame-button" type="button" data-frame="${i}" aria-label="Открыть кадр ${i+1} на ${esc(seconds(frame.timestamp_sec))}"><img src="data:image/jpeg;base64,${frame.image_base64}" alt="${state.mode==='demo'?'Синтетическая схема':'Кадр из ответа сервера'}, отметка ${esc(seconds(frame.timestamp_sec))}" width="480" height="300" loading="lazy"><span class="expand-hint">${ic('arrow-up-right')}</span></button><figcaption><span>${state.mode==='demo'?'СХЕМА / ДЕМО':'КАДР '+String(i+1).padStart(2,'0')}</span>${seekAvailable ? `<button class="text-link mono" type="button" data-frame-seek="${i}" aria-label="Открыть видео на ${esc(seconds(frame.timestamp_sec))}">${esc(seconds(frame.timestamp_sec))}</button>` : `<span class="mono">${esc(seconds(frame.timestamp_sec))}</span>`}</figcaption></figure>`).join('')}</div></div>${renderRule(event.rule)}`;
  $$('#eventDetail img').forEach(img=>img.addEventListener('error',()=>{const box=document.createElement('div');box.className='frame-missing';box.textContent='Кадр не удалось открыть. Проверьте JPEG в ответе сервера.';img.closest('.frame-button').replaceWith(box);},{once:true}));
}
function selectEvent(index) {
  if (!Number.isInteger(index) || !state.result?.violations[index]) return;
  state.selected = index;
  $$('[data-select]').forEach(button=>button.setAttribute('aria-pressed',String(+button.dataset.select===index)));
  renderEvent(); announce('Выбрано событие '+(index+1));
}
function renderRules() {
  const events = state.result?.violations || [];
  const withRules = events.filter(v=>v.rule && typeof v.rule === 'object');
  $('#rulesContent').innerHTML = withRules.length ? modeBanner() + `<div class="rule-list">${withRules.map(v=>`<article class="card"><span class="step-label">СОБЫТИЕ / ${esc(eventTime(v.timecode_sec))}</span><h2 style="margin-top:12px">${esc(v.type)}</h2>${renderRule(v.rule)}</article>`).join('')}</div>` : `<div class="empty-state">${ic('book')}<h2>Основания появятся вместе с результатом</h2><p>Документ, раздел и ссылка приходят из общего API. Здесь отображаются только основания событий текущего задания; отдельный каталог интерфейс не выдумывает.</p><a class="btn btn-outline" href="#/results">К результатам проверки</a></div>`;
}
function showFrame(index) {
  const frame = state.result?.violations[state.selected]?.evidence_frames[index]; if(!frame) return;
  openDialog({title:`Кадр ${index+1} / ${seconds(frame.timestamp_sec)}`,desc:state.mode==='demo'?'Синтетическая схема для демонстрации интерфейса.':'Изображение получено от сервера для текущего задания.',width:960,body:`<img class="expanded-frame" src="data:image/jpeg;base64,${frame.image_base64}" alt="${esc('Кадр, '+seconds(frame.timestamp_sec))}" width="960" height="600">`,foot:'<button class="btn btn-outline" data-close type="button">Закрыть</button>'});
}
function showVideo(timecode = state.result?.violations[state.selected]?.timecode_sec, approximate = isApproximateTiming()) {
  if (!Number.isFinite(timecode) || timecode < 0 || !state.videoUrl || state.mode === 'demo') return;
  openDialog({title:'Момент в исходной записи',desc:`${approximate ? 'Примерное время' : 'Отметка'} ${seconds(timecode)}.${approximate ? ' Посмотрите контекст до и после отметки.' : ''} Воспроизведение MOV зависит от браузера.`,width:900,body:'<div class="video-wrap"><video id="seekPlayer" controls preload="metadata" playsinline aria-label="Момент в исходном видео"></video></div><p class="player-hint" id="seekHint">Если видео не открывается, проверьте этот таймкод в локальном видеоплеере.</p>',foot:'<button class="btn btn-outline" data-close type="button">Закрыть</button>',onMount(el,layer){const video=el.querySelector('video');video.src=state.videoUrl;video.addEventListener('loadedmetadata',()=>{try{video.currentTime=Math.min(timecode,Number.isFinite(video.duration)?video.duration:timecode);}catch{}});video.addEventListener('error',()=>el.querySelector('#seekHint').textContent='Этот MOV не воспроизводится в браузере. Откройте исходный файл в локальном видеоплеере и перейдите к указанному времени.');layer.onClose=()=>{video.pause();video.removeAttribute('src');video.load();};}});
}
function syntheticFrame(variant=0) {
  const canvas=document.createElement('canvas');canvas.width=720;canvas.height=450;
  const c=canvas.getContext('2d');
  c.fillStyle='#252b37';c.fillRect(0,0,720,450);
  c.strokeStyle='#465060';c.lineWidth=2;
  for(let x=-400;x<1100;x+=80){c.beginPath();c.moveTo(x,140);c.lineTo(x+260,450);c.stroke();}
  for(let y=160;y<450;y+=50){c.beginPath();c.moveTo(0,y);c.lineTo(720,y);c.stroke();}
  c.fillStyle='#353e4d';c.fillRect(390,80,245,90);c.strokeRect(390,80,245,90);
  c.fillStyle='#8895a8';c.fillRect(415,100,70,38);c.fillRect(530,100,70,38);
  const x=variant?330:245;c.fillStyle='#aab5c4';c.beginPath();c.arc(x+28,202,16,0,Math.PI*2);c.fill();c.fillRect(x+12,222,32,60);c.fillRect(x+13,277,12,45);c.fillRect(x+32,277,12,45);
  c.strokeStyle='#dd76a0';c.lineWidth=3;c.setLineDash([9,6]);c.beginPath();c.moveTo(440,195);c.lineTo(660,420);c.stroke();c.setLineDash([]);c.strokeRect(x-6,175,70,158);
  c.fillStyle='#e6e9ef';c.font='17px sans-serif';c.fillText('SYNTHETIC SAMPLE / NOT REAL FOOTAGE',24,34);c.font='13px monospace';c.fillText(variant?'DEMO FRAME B':'DEMO FRAME A',24,421);
  return canvas.toDataURL('image/jpeg',.85).split(',')[1];
}
function demoResult(verdict) {
  return {job_id:'demo-interface-only',status:'done',mode:'demo',verdict,violations:verdict==='no_violation'?[]:[
    {type:'Пересечение условной границы',timecode_sec:24,description:'Синтетический пример: условный объект пересекает линию в учебной схеме. Это не результат модели и не квалификация реального действия.',evidence_frames:[{timestamp_sec:23.8,image_base64:syntheticFrame(0)},{timestamp_sec:24.3,image_base64:syntheticFrame(1)}],rule:{id:'DEMO-01',document:'Учебное правило демонстрации',section:'Вымышленное основание. Не нормативный акт.',source_url:null}},
    {type:'Событие для ручной проверки',timecode_sec:63,description:'Второе синтетическое событие показывает переключение карточек, отметок времени и кадров. Реальные категории и описания поступают от API.',evidence_frames:[{timestamp_sec:63.2,image_base64:syntheticFrame(1)}],rule:null}
  ]};
}
function runDemo(verdict='violation') {
  if(active() || hasJob() && state.phase==='paused'){
    openDialog({title:'Открыть отдельный демопример?',desc:'Текущее ожидание будет прекращено. Демонстрация использует синтетический сценарий, а не выбранное видео.',body:'<p class="muted">Если на сервере уже создано задание, сохраните его идентификатор перед переключением. Серверная обработка не отменяется.</p>'+jobMarkup(),foot:'<button class="btn btn-outline" data-close type="button">Остаться</button><button class="btn btn-primary" type="button" data-submit>Открыть демо</button>',onSubmit(el,layer){closeLayer(layer);clearJob();startDemo(verdict);}});return;
  }
  clearJob();startDemo(verdict);
}
function startDemo(verdict) {
  const generation=state.generation;state.phase='processing';state.mode='demo';state.localDemo=true;state.jobId='demo-interface-only';
  renderResults();renderUpload();navigate('results');announce('Демонстрация интерфейса. Используются синтетические данные.');
  state.timer=setTimeout(()=>{
    if(generation!==state.generation)return;
    if(verdict==='failed'){state.phase='error';state.error='Учебный сценарий: обработчик не смог завершить анализ. При такой ошибке интерфейс не показывает вердикт.';}
    else{state.result=demoResult(verdict);state.phase='done';state.selected=0;}
    renderUpload();renderResults();renderRules();announce(verdict==='failed'?'Демонстрация ошибки. Вердикта нет.':'Демонстрационный результат готов.');
  },reduced()?100:1200);
}
function paletteCommands() {
  const icons={overview:'plus',results:'list-checks',rules:'book',guide:'info',settings:'settings'};
  return [...Object.entries(ROUTES).map(([id,r])=>({group:'Разделы',label:r.title,icon:icons[id],sub:r.group,kw:id,run:()=>navigate(id)})),
    {group:'Действия',label:'Открыть синтетический демопример',icon:'play',kw:'demo тест',run:()=>runDemo()},
    {group:'Действия',label:root.classList.contains('dark')?'Включить светлую тему':'Включить тёмную тему',icon:'contrast',kw:'theme тема',run:()=>setTheme({mode:root.classList.contains('dark')?'light':'dark'})},
    {group:'Действия',label:'Проверить готовность сервиса',icon:'activity',kw:'ready api',run:()=>{navigate('settings');checkReady();}}];
}
VIEWS.overview={init(){}};
VIEWS.results={init(){},enter(){renderResults();}};
VIEWS.rules={init(){},enter(){renderRules();}};
VIEWS.guide={init(){}};
VIEWS.settings={init(){},enter(){syncThemeControls();}};
function syncThemeControls(){ $('#modeSelect').value=theme.mode;$('#presetSelect').value=theme.preset; }
function boot() {
  // Memory-only credentials: no URL, storage, analytics or export receives the key.
  $('#apiBase').addEventListener('input',invalidateReadiness);$('#apiKey').addEventListener('input',invalidateReadiness);
  bindForm($('#connectionForm'),checkReady);
  $('#clearKey').addEventListener('click',()=>{$('#apiKey').value='';invalidateReadiness();toast({title:'Ключ удалён из памяти страницы'});});
  $('#toggleKey').addEventListener('click',()=>{const input=$('#apiKey');const show=input.type==='password';input.type=show?'text':'password';$('#toggleKey').setAttribute('aria-label',show?'Скрыть ключ':'Показать ключ');$('#toggleKey').setAttribute('aria-pressed',String(show));});
  $('#modeBtn').addEventListener('click',()=>setTheme({mode:root.classList.contains('dark')?'light':'dark'}));
  $('#presetBtn').addEventListener('click',()=>openMenu($('#presetBtn'),PRESETS.map(p=>({label:p.name,checked:p.id===theme.preset,action:()=>setTheme({preset:p.id})})),{label:'Цветовая тема'}));
  $('#modeSelect').addEventListener('change',e=>setTheme({mode:e.target.value}));$('#presetSelect').addEventListener('change',e=>setTheme({preset:e.target.value}));
  document.addEventListener('themechange',syncThemeControls);
  $('#chooseFile').addEventListener('click',()=>$('#fileInput').click());
  $('#fileInput').addEventListener('change',e=>{if(e.target.files.length)chooseFiles([...e.target.files]);e.target.value='';});
  const zone=$('#dropzone');
  zone.addEventListener('dragover',e=>{e.preventDefault();if(!active())zone.classList.add('dragover');});
  zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('dragover');});
  zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('dragover');chooseFiles([...e.dataTransfer.files]);});
  // Prevent the browser from navigating to a dropped file outside the dropzone.
  document.addEventListener('dragover',e=>{if(e.dataTransfer?.types.includes('Files'))e.preventDefault();});
  document.addEventListener('drop',e=>{if(e.dataTransfer?.files.length)e.preventDefault();});
  $('#openDemo').addEventListener('click',()=>runDemo());$('#guideDemo').addEventListener('click',()=>runDemo());
  document.addEventListener('click',e=>{
    const demo=e.target.closest('[data-demo]');if(demo){runDemo(demo.dataset.demo);return;}
    const select=e.target.closest('[data-select]');if(select){selectEvent(+select.dataset.select);return;}
    const frame=e.target.closest('[data-frame]');if(frame){showFrame(+frame.dataset.frame);return;}
    const frameSeek=e.target.closest('[data-frame-seek]');if(frameSeek){const f=state.result?.violations[state.selected]?.evidence_frames?.[Number(frameSeek.dataset.frameSeek)];if(f)showVideo(f.timestamp_sec,false);return;}
    const question=e.target.closest('[data-question-seek]');if(question){const q=state.result?.analysis?.review_questions?.[Number(question.dataset.questionSeek)];if(q)showVideo(q.timecode_sec);return;}
    const action=e.target.closest('[data-action]')?.dataset.action;
    if(action==='analyze')analyze();
    if(action==='resume')resumeJob();
    if(action==='new'){
      if(active()) openDialog({title:'Начать новую проверку?',desc:'Ожидание в браузере прекратится. Серверная обработка может продолжиться.',body:'<p class="muted">Сохраните идентификатор текущего задания, если он уже получен.</p>'+jobMarkup(),foot:'<button class="btn btn-outline" data-close type="button">Остаться</button><button class="btn btn-primary" data-submit type="button">Новая проверка</button>',onSubmit(el,layer){closeLayer(layer);newCheck();}});
      else newCheck();
    }
    if(action==='remove-file'){clearJob();releaseVideo();state.file=null;renderUpload();}
    if(action==='replace-file')$('#fileInput').click();
    if(action==='pause'){
      if(state.phase==='uploading'){stopWork();state.phase='error';state.error='Ожидание ответа на загрузку прекращено. Сервер мог принять файл, но идентификатор не получен. Перед повторной отправкой уточните состояние у команды.';renderUpload();renderResults();}
      else pauseJob(state.mode==='demo'?'Демонстрация остановлена.':'Опрос остановлен в браузере. Серверная задача может продолжить работу.');
    }
    if(action==='seek-video')showVideo();
    if(action==='analysis-info')openDialog({title:'Сведения об анализе',desc:'Данные получены от сервера без изменения значений.',body:`<pre class="analysis-json">${esc(JSON.stringify(state.result.analysis,null,2))}</pre>`,foot:'<button class="btn btn-outline" data-close type="button">Закрыть</button>',width:650});
  });
  document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openPalette();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='b'){e.preventDefault();setSidebar(!sidebarOpen());}});
  window.addEventListener('beforeunload',()=>{stopWork();releaseVideo();});
  applyTheme();renderUpload();renderResults();renderRules();route();observeTop();
  state.localSessionPromise = bootstrapLocalSession();
}
boot();

})();
