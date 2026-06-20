'use strict';

const $ = (s) => document.querySelector(s);
const elQ = $('#q');
const elResults = $('#results');
const elEmpty = $('#empty');
const elCount = $('#count');
const elBanner = $('#banner');
const elToast = $('#toast');

let api = null;
let items = [];
let sel = -1;
let reqId = 0;
let debounceTimer = null;
let currentScope = '';
let backendReady = true;   // Everything 索引是否就绪(status 会校正)
let fitRaf = null;

/* ---------- 就绪 ---------- */
window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  // 先通知 Python：此时本文件已完整执行，__glanceShow/__glanceScope 可用。
  // 热键若早于 bridge 初始化抵达，后端会在这里按顺序补发而不是静默丢失。
  try { await api.ui_ready(); } catch (e) { /* ignore */ }
  await bootTheme();
  try {
    const st = await api.status();
    backendReady = !!(st && st.ready);
    if (!backendReady) showBanner('正在准备文件索引…  首次启动需要几秒', 'info');
  } catch (e) { /* ignore */ }
  syncMaximized();
  scheduleFit();
  elQ.focus();
});

/* 后端就绪通知:Python 的后台线程备好 Everything 后 evaluate_js 调用 */
window.__glanceBackend = function (ready) {
  backendReady = !!ready;
  if (backendReady) { hideBanner(); if (elQ.value.trim()) doSearch(); }
  else showBanner('正在准备文件索引…  首次启动需要几秒', 'info');
};

/* ---------- 主题 ---------- */
async function bootTheme() {
  let theme = null;
  try { const b = await api.get_boot(); theme = b && b.theme; } catch (e) { /* ignore */ }
  if (theme !== 'light' && theme !== 'dark')
    theme = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  applyTheme(theme, false);
}
function applyTheme(theme, persist) {
  document.documentElement.setAttribute('data-theme', theme);
  try { if (api && api.set_native_dark) api.set_native_dark(theme === 'dark'); } catch (e) { /* ignore */ }
  if (persist && api && api.set_theme) api.set_theme(theme);
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  applyTheme(cur === 'dark' ? 'light' : 'dark', true);
}

/* ---------- 工具 ---------- */
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function highlight(name, query) {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return escapeHtml(name);
  const lower = name.toLowerCase();
  const hit = new Array(name.length).fill(false);
  for (const t of tokens) {
    let idx = 0;
    while (true) {
      const f = lower.indexOf(t, idx);
      if (f < 0) break;
      for (let k = f; k < f + t.length; k++) hit[k] = true;
      idx = f + t.length;
    }
  }
  let html = '', open = false;
  for (let i = 0; i < name.length; i++) {
    if (hit[i] && !open) { html += '<mark>'; open = true; }
    if (!hit[i] && open) { html += '</mark>'; open = false; }
    html += escapeHtml(name[i]);
  }
  if (open) html += '</mark>';
  return html;
}
function fmtSize(b) {
  if (b == null || b < 0) return '';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, n = b;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)) + ' ' + u[i];
}
function fmtDate(epoch) {
  if (!epoch) return '';
  const d = new Date(epoch * 1000), now = new Date();
  const opts = d.getFullYear() === now.getFullYear()
    ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' };
  return d.toLocaleDateString(undefined, opts);
}
function baseName(p) {
  const s = p.replace(/[\\/]+$/, '');
  const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'));
  return i >= 0 ? s.slice(i + 1) : s;
}

const CAT = {
  code: ['cpp','h','hpp','c','cc','cs','py','js','ts','jsx','tsx','java','go','rs','lua','rb','php','swift','kt'],
  shader: ['ush','usf','hlsl','glsl','shader','cginc','frag','vert','comp'],
  asset: ['uasset','umap','upk'],
  image: ['png','jpg','jpeg','tga','bmp','gif','webp','psd','tiff','exr','svg','ico'],
  media: ['mp4','mov','avi','mkv','wav','mp3','flac','ogg','fbx','obj','gltf','glb'],
};
const EXT2CAT = {};
for (const k in CAT) for (const e of CAT[k]) EXT2CAT[e] = k;

const FOLDER_SVG = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const REVEAL_SVG = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="2.2"/></svg>';
const COPY_SVG = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>';
const COPYNAME_SVG = '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><line x1="8.5" y1="13" x2="15" y2="13"/><line x1="8.5" y1="16.5" x2="13" y2="16.5"/></svg>';

function chip(it) {
  if (it.is_dir) return { cls: 'cat-folder', html: FOLDER_SVG, svg: true };
  const cat = EXT2CAT[it.ext];
  const label = it.ext ? (it.ext.length > 4 ? it.ext.slice(0, 4) : it.ext) : '·';
  return { cls: cat ? 'cat-' + cat : '', html: label, svg: false };
}

/* ---------- 渲染 ---------- */
function render(query) {
  elResults.innerHTML = '';
  if (!items.length) {
    const has = !!query.trim();
    if (!has) {                       // 初始空态:不显示任何居中文字(避免误以为在中央搜索)
      elEmpty.classList.add('hidden');
      elCount.textContent = '';
      scheduleFit();
      return;
    }
    elEmpty.classList.remove('hidden');
    if (!backendReady) {
      elEmpty.querySelector('.empty-title').textContent = '正在准备文件索引…';
      elEmpty.querySelector('.empty-sub').textContent = '首次启动需要几秒,稍后会自动显示结果';
    } else {
      elEmpty.querySelector('.empty-title').textContent = '没有匹配的文件';
      elEmpty.querySelector('.empty-sub').textContent = currentScope ? '当前范围内没有,试试清除范围' : '换个关键词试试';
    }
    elCount.textContent = '';
    scheduleFit();
    return;
  }
  elEmpty.classList.add('hidden');
  const frag = document.createDocumentFragment();
  items.forEach((it, i) => {
    const c = chip(it);
    const row = document.createElement('div');
    row.className = 'row' + (i === sel ? ' sel' : '');
    row.dataset.i = i;
    row.innerHTML =
      `<div class="chip ${c.cls}">${c.svg ? c.html : escapeHtml(c.html)}</div>` +
      `<div class="meta"><div class="name">${highlight(it.name, query)}</div>` +
      `<div class="path">${escapeHtml(it.dir)}</div></div>` +
      `<div class="side">` +
        `<div class="info"><span class="sz">${it.is_dir ? '文件夹' : fmtSize(it.size)}</span><br>${fmtDate(it.mtime)}</div>` +
        `<div class="actions">` +
          `<button class="act" data-act="copyname" title="复制文件名(含扩展名)">${COPYNAME_SVG}</button>` +
          `<button class="act" data-act="copy" title="复制完整路径">${COPY_SVG}</button>` +
          `<button class="act" data-act="reveal" title="打开所在文件夹并选中">${REVEAL_SVG}</button>` +
        `</div></div>`;
    frag.appendChild(row);
  });
  elResults.appendChild(frag);
  elCount.textContent = `${items.length} 个结果`;
  scheduleFit();
}

/* ---------- 搜索 ---------- */
function doSearch() {
  const query = elQ.value;
  const myId = ++reqId;
  if (!query.trim()) { items = []; sel = -1; render(''); return; }
  if (!api) return;
  api.search(query, currentScope).then((res) => {
    if (myId !== reqId) return;
    if (!res.ok) showBanner(res.error || '搜索出错'); else hideBanner();
    items = res.results || [];
    sel = items.length ? 0 : -1;
    render(query);
    scrollSelIntoView();
  });
}
elQ.addEventListener('input', () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(doSearch, 70); });

/* ---------- 范围 ---------- */
function setScope(path) {
  currentScope = path || '';
  const chipEl = $('#scopeChip');
  if (currentScope) {
    $('#scopeName').textContent = baseName(currentScope);
    chipEl.classList.remove('hidden');
    chipEl.title = '搜索范围:' + currentScope;
  } else {
    chipEl.classList.add('hidden');
  }
  if (elQ.value.trim()) doSearch();
}
$('#scopeClear').addEventListener('click', () => { setScope(''); elQ.focus(); });

/* 呼出钩子:Python 端 evaluate_js 调用 */
window.__glanceShow = function (scope) {
  setScope(scope || '');
  elQ.focus();
  elQ.select();
  syncMaximized();
  scheduleFit();
};

/* 范围钩子:前台目录由 Python 后台 COM 解析完成后推送(不抢焦点、不清输入) */
window.__glanceScope = function (scope) {
  setScope(scope || '');
};

/* ---------- 选择 / 动作 ---------- */
function setSel(i) {
  if (!items.length) return;
  sel = Math.max(0, Math.min(items.length - 1, i));
  [...elResults.children].forEach((r, idx) => r.classList.toggle('sel', idx === sel));
  scrollSelIntoView();
}
function scrollSelIntoView() { const r = elResults.children[sel]; if (r) r.scrollIntoView({ block: 'nearest' }); }
function act(kind, i) {
  const it = items[i];
  if (!it || !api) return;
  if (kind === 'open') api.open_file(it.path);
  else if (kind === 'reveal') api.reveal_in_folder(it.path);
  else if (kind === 'copy') api.copy_path(it.path).then((r) => { if (r && r.ok) toast('已复制路径'); });
  else if (kind === 'copyname') api.copy_name(it.path).then((r) => { if (r && r.ok) toast('已复制文件名'); });
}
elResults.addEventListener('click', (e) => {
  const row = e.target.closest('.row'); if (!row) return;
  const i = +row.dataset.i;
  const btn = e.target.closest('.act');
  if (btn) { act(btn.dataset.act, i); return; }
  setSel(i);
});
elResults.addEventListener('dblclick', (e) => {
  const row = e.target.closest('.row');
  if (row && !e.target.closest('.act')) act('open', +row.dataset.i);
});

/* ---------- 键盘 ---------- */
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { e.preventDefault(); setSel(sel + 1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(sel - 1); }
  else if (e.key === 'Enter') { e.preventDefault(); if (sel >= 0) act(e.ctrlKey ? 'reveal' : 'open', sel); }
  else if ((e.key === 'c' || e.key === 'C') && e.ctrlKey) {
    if (sel >= 0) { e.preventDefault(); act(e.shiftKey ? 'copyname' : 'copy', sel); }
  }
  else if (e.key === 'Escape') {
    e.preventDefault();
    if (elQ.value) { elQ.value = ''; items = []; sel = -1; render(''); }
    else if (api && api.win_close) api.win_close();   // 隐藏到托盘
  }
});

/* ---------- 窗口:拖动 / 缩放 / 控件 ---------- */
$('#titlebar').addEventListener('mousedown', (e) => {
  if (e.button !== 0) return;
  if (e.target.closest('button, .win-controls')) return;
  let sx = e.screenX, sy = e.screenY, started = false;
  function mm(ev) {
    if (started) return;
    if (Math.abs(ev.screenX - sx) > 4 || Math.abs(ev.screenY - sy) > 4) {
      started = true;
      if (api && api.win_drag) api.win_drag();
      cleanup();
    }
  }
  function cleanup() { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', cleanup); }
  window.addEventListener('mousemove', mm); window.addEventListener('mouseup', cleanup);
});
$('#titlebar').addEventListener('dblclick', (e) => {
  if (e.target.closest('button, .win-controls')) return;
  if (api && api.win_toggle_maximize) api.win_toggle_maximize().then(() => setTimeout(afterMaxToggle, 60));
});

const RH = { 'rh-n': 'top', 'rh-s': 'bottom', 'rh-w': 'left', 'rh-e': 'right',
  'rh-nw': 'topleft', 'rh-ne': 'topright', 'rh-sw': 'bottomleft', 'rh-se': 'bottomright' };
document.querySelectorAll('.resize-handle').forEach((h) => {
  h.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const edge = RH[[...h.classList].find((c) => c.startsWith('rh-'))];
    if (edge && api && api.win_resize) api.win_resize(edge);
  });
});

$('#winMin').addEventListener('click', () => api && api.win_minimize());
$('#winMax').addEventListener('click', () => api && api.win_toggle_maximize().then(() => setTimeout(afterMaxToggle, 60)));
$('#winClose').addEventListener('click', () => api && api.win_close());
$('#themeBtn').addEventListener('click', toggleTheme);

function syncMaximized() {
  if (!api || !api.win_is_maximized) return;
  api.win_is_maximized().then((m) => document.documentElement.classList.toggle('window-maximized', !!m));
}

/* ---------- 自适应高度(空时仅搜索栏,随结果增高到上限后滚动) ---------- */
function fitHeight() {
  if (!api || !api.win_set_height) return;
  if (document.documentElement.classList.contains('window-maximized')) return;
  const tb = $('#titlebar').offsetHeight;
  const sb = $('#searchbar').offsetHeight;
  const ft = $('#footer').offsetHeight;
  const bn = elBanner.classList.contains('hidden') ? 0 : elBanner.offsetHeight;
  let body;
  if (items.length) body = elResults.scrollHeight + 2;        // 全部结果内容高(+2 避免临界滚动条)
  else if (!elEmpty.classList.contains('hidden')) body = 120; // 无结果/准备中的提示
  else body = 0;                                              // 初始空态 → 紧凑
  const chrome = tb + sb + ft + bn;
  const maxCss = Math.min(640, (screen.availHeight || 900) - 80);
  const cssH = Math.max(chrome + 6, Math.min(chrome + body, maxCss));
  api.win_set_height(Math.round(cssH * (window.devicePixelRatio || 1)));
}
function scheduleFit() {
  if (fitRaf) cancelAnimationFrame(fitRaf);
  fitRaf = requestAnimationFrame(fitHeight);
}
function afterMaxToggle() {
  if (!api || !api.win_is_maximized) { scheduleFit(); return; }
  api.win_is_maximized().then((m) => {
    document.documentElement.classList.toggle('window-maximized', !!m);
    if (!m) scheduleFit();   // 还原后重新贴合内容;最大化时保持铺满
  });
}
let sizeTimer = null;
window.addEventListener('resize', () => {
  syncMaximized();
  clearTimeout(sizeTimer);
  sizeTimer = setTimeout(() => {
    if (api && api.save_size && !document.documentElement.classList.contains('window-maximized'))
      api.save_size(window.innerWidth, window.innerHeight);
  }, 500);
});

/* ---------- 提示 ---------- */
let toastTimer = null;
function toast(msg) {
  elToast.textContent = msg; elToast.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => elToast.classList.remove('show'), 1400);
}
function showBanner(msg, kind) {
  elBanner.textContent = msg;
  elBanner.classList.toggle('info', kind === 'info');
  elBanner.classList.remove('hidden');
}
function hideBanner() { elBanner.classList.add('hidden'); }
