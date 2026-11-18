/* Sınav İzleme paneli. Harici kaynak kullanılmaz; her şey bu sunucudan ve yerel MediaMTX'ten gelir.
 * Öğrenciden gelen tüm metinler (ad, bilgisayar adı, pencere başlığı…) yalnızca textContent ile
 * yazılır; hiçbir zaman HTML olarak yorumlanmaz. */
'use strict';

const $ = (id) => document.getElementById(id);

const STATUS_TEXT = {
  ok: 'Bağlı',
  warn: 'Uyarı var',
  lost: 'Bağlantı yok',
  done: 'Teslim etti',
  nosubmit: 'Teslim yok',
};
const STATE_TEXT = { WAITING: 'Sınav başlamadı', RUNNING: 'Sınav sürüyor', ENDED: 'Sınav bitti' };
const ROSTER_TEXT = {
  no_roster: 'Liste yüklü değil',
  ok: 'Listede',
  name_mismatch: 'Listede, ad uyuşmuyor',
  not_in_list: 'Listede yok',
};
const ROW_EVENT_LIMIT = 6;

let S = null;                    // sunucudan gelen son durum
let lastAlertId = null;          // sesli uyarı için
let filter = 'all';              // 'all' | 'alerts'
let modalNumara = null;
let modalEvCount = -1;
const tiles = new Map();         // numara -> kutu
const rows = new Map();          // numara -> liste satırı
const expanded = new Set();      // açık satırlar
const eventCache = new Map();    // numara -> { count, events }

/* ----------------------------------------------------------------- yardımcılar */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function fmtClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

function fmtClockSeconds(ts) {
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour12: false });
}

function toast(message, isError) {
  const node = el('div', isError ? 'toast error' : 'toast', message);
  $('toasts').appendChild(node);
  setTimeout(() => node.remove(), isError ? 9000 : 4500);
}

function pref(key, fallback) {
  try {
    const value = localStorage.getItem(`sinav.${key}`);
    return value === null ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

function setPref(key, value) {
  try { localStorage.setItem(`sinav.${key}`, String(value)); } catch (_) { /* önemli değil */ }
}

async function api(path, options) {
  const init = Object.assign({ method: 'POST' }, options || {});
  init.headers = Object.assign({ 'X-Panel': '1' }, init.headers || {});
  if (init.json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(init.json);
    delete init.json;
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (_) {
    throw new Error('Sunucuya ulaşılamadı. Başlatma penceresi açık mı?');
  }
  let data = {};
  try { data = await response.json(); } catch (_) { /* gövde yok */ }
  if (!response.ok) throw new Error(data.error || `Hata (${response.status})`);
  return data;
}

/* ----------------------------------------------------------------- ses */

let audioCtx = null;
function beep(critical) {
  if (!$('sound').checked) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const now = audioCtx.currentTime;
    const tones = critical ? [880, 660, 880] : [740];
    tones.forEach((freq, i) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const start = now + i * 0.16;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.14);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(start);
      osc.stop(start + 0.15);
    });
  } catch (_) { /* ses açılamadıysa sessiz devam */ }
}

/* ----------------------------------------------------------------- WebRTC (WHEP) */

const startQueue = [];
let startWorkers = 0;
const MAX_PARALLEL_STARTS = 4;

function pumpStartQueue() {
  while (startWorkers < MAX_PARALLEL_STARTS && startQueue.length) {
    const player = startQueue.shift();
    player.queued = false;
    startWorkers += 1;
    player.connect().finally(() => {
      startWorkers -= 1;
      pumpStartQueue();
    });
  }
}

function waitIceGathering(pc, timeoutMs) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => { if (pc.iceGatheringState === 'complete') done(); };
    const timer = setTimeout(done, timeoutMs);
    pc.addEventListener('icegatheringstatechange', check);
  });
}

class Player {
  constructor(numara, video, holder) {
    this.numara = numara;
    this.video = video;
    this.holder = holder;       // "playing" sınıfı buraya eklenir
    this.pc = null;
    this.wanted = false;
    this.queued = false;
    this.timer = null;
    this.lastBytes = -1;
    this.stalls = 0;
    video.addEventListener('playing', () => this.holder.classList.add('playing'));
  }

  setWanted(wanted) {
    if (wanted === this.wanted) return;
    this.wanted = wanted;
    if (wanted) this.schedule(0);
    else this.close();
  }

  schedule(delayMs) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      if (!this.wanted || this.pc || this.queued) return;
      this.queued = true;
      startQueue.push(this);
      pumpStartQueue();
    }, delayMs);
  }

  close() {
    clearTimeout(this.timer);
    if (this.pc) {
      const pc = this.pc;
      this.pc = null;
      try { pc.close(); } catch (_) { /* zaten kapalı */ }
    }
    this.video.srcObject = null;
    this.holder.classList.remove('playing');
    this.lastBytes = -1;
    this.stalls = 0;
  }

  retry(delayMs) {
    this.close();
    if (this.wanted) this.schedule(delayMs);
  }

  async connect() {
    if (!this.wanted || this.pc || !S) return;
    const pc = new RTCPeerConnection({ iceServers: [] });   // internet yok: STUN/TURN yok
    this.pc = pc;
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addEventListener('track', (ev) => {
      if (pc !== this.pc) return;
      this.video.srcObject = ev.streams[0] || new MediaStream([ev.track]);
      const playing = this.video.play();
      if (playing && playing.catch) playing.catch(() => {});
    });
    pc.addEventListener('connectionstatechange', () => {
      if (pc !== this.pc) return;
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        this.retry(2000);
      } else if (pc.connectionState === 'disconnected') {
        setTimeout(() => {
          if (pc === this.pc && pc.connectionState !== 'connected') this.retry(1000);
        }, 4000);
      }
    });
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await waitIceGathering(pc, 1500);
      const url = `${S.webrtc_base}/s/${encodeURIComponent(this.numara)}/whep`;
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: pc.localDescription.sdp,
      });
      if (!response.ok) throw new Error(`WHEP ${response.status}`);
      const answer = await response.text();
      if (pc !== this.pc) return;
      await pc.setRemoteDescription({ type: 'answer', sdp: answer });
    } catch (_) {
      if (pc === this.pc) this.retry(3000);
    }
  }

  /* Yayın "var" görünüp veri akmıyorsa bağlantıyı yenile. */
  async checkStall() {
    const pc = this.pc;
    if (!pc || pc.connectionState !== 'connected') return;
    let bytes = 0;
    try {
      const stats = await pc.getStats();
      stats.forEach((report) => {
        if (report.type === 'inbound-rtp' && report.kind === 'video') bytes += report.bytesReceived || 0;
      });
    } catch (_) {
      return;
    }
    if (pc !== this.pc) return;
    if (bytes === this.lastBytes) {
      this.stalls += 1;
      if (this.stalls >= 2) this.retry(0);
    } else {
      this.stalls = 0;
      this.lastBytes = bytes;
    }
  }
}

const visibility = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const tile = tiles.get(entry.target.dataset.numara);
    if (tile) {
      tile.visible = entry.isIntersecting;
      updatePlayback(tile);
    }
  }
}, { root: $('gridWrap'), rootMargin: '200px' });

function updatePlayback(tile) {
  const st = tile.data;
  if (!st) return;
  const isOpen = modalNumara === st.numara;
  const visibleEnough = isOpen || tile.visible || !$('pauseHidden').checked;
  tile.player.setWanted(Boolean(st.stream_ready) && visibleEnough);
}

setInterval(() => { tiles.forEach((tile) => tile.player.checkStall()); }, 5000);

/* ----------------------------------------------------------------- ortak metinler */

function fullName(st) {
  return `${st.ad} ${st.soyad}`.trim();
}

function statusText(st) {
  if (st.status === 'lost') return st.lost_reason ? `Bağlantı yok — ${st.lost_reason}` : 'Bağlantı yok';
  return STATUS_TEXT[st.status] || st.status;
}

function noVideoText(st) {
  if (st.status === 'done') return 'Teslim etti';
  if (st.status === 'nosubmit') return 'Teslim yok';
  if (st.status === 'lost') return 'Bağlantı yok';
  return st.stream_ready ? 'Görüntü bağlanıyor…' : 'Ekran bekleniyor…';
}

/* Her öğrencinin en son uyarısı (S.alerts en yeni üstte gelir). */
function latestAlerts() {
  const latest = new Map();
  for (const alert of S.alerts) {
    if (alert.numara && alert.severity !== 'info' && !latest.has(alert.numara)) latest.set(alert.numara, alert);
  }
  return latest;
}

function needsAttention(st) {
  return st.warn_count > 0 || st.status === 'lost' || st.status === 'nosubmit';
}

/* ----------------------------------------------------------------- ekran kutuları */

function createTile(numara) {
  const root = el('div', 'tile');
  root.dataset.numara = numara;
  const videoBox = el('div', 'video');
  const video = document.createElement('video');
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  const noVideo = el('div', 'novideo');
  const flag = el('span', 'flag');
  flag.hidden = true;
  videoBox.append(video, noVideo, flag);

  const cap = el('div', 'cap');
  const who = el('span', 'who');
  const num = el('span', 'num', numara);
  const name = el('span', 'name');
  who.append(num, name);
  cap.append(el('span', 'dot'), who);
  root.append(videoBox, cap);

  root.addEventListener('click', () => openModal(numara));
  const tile = {
    root, video, noVideo, flag, name,
    player: new Player(numara, video, videoBox),
    visible: true,
    data: null,
    statusClass: '',
  };
  visibility.observe(root);
  return tile;
}

function renderTiles() {
  const grid = $('grid');
  const seen = new Set();
  let previous = null;
  for (const st of S.students) {
    seen.add(st.numara);
    let tile = tiles.get(st.numara);
    if (!tile) {
      tile = createTile(st.numara);
      tiles.set(st.numara, tile);
    }
    // Sıra sunucudan numaraya göre gelir; DOM sırasını ona uydur.
    const expectedNext = previous ? previous.root.nextSibling : grid.firstChild;
    if (expectedNext !== tile.root) grid.insertBefore(tile.root, expectedNext);
    previous = tile;

    tile.data = st;
    const statusClass = `st-${st.status}`;
    if (tile.statusClass !== statusClass) {
      if (tile.statusClass) tile.root.classList.remove(tile.statusClass);
      tile.root.classList.add(statusClass);
      tile.statusClass = statusClass;
    }
    setText(tile.name, fullName(st));
    tile.root.title = `${st.numara} ${fullName(st)} — ${statusText(st)}`;
    tile.flag.hidden = st.warn_count === 0;
    setText(tile.flag, String(st.warn_count));
    setText(tile.noVideo, noVideoText(st));
    updatePlayback(tile);
  }
  for (const [numara, tile] of tiles) {
    if (!seen.has(numara)) {
      tile.player.setWanted(false);
      visibility.unobserve(tile.root);
      tile.root.remove();
      tiles.delete(numara);
    }
  }
  $('empty').hidden = S.students.length > 0;
  layoutGrid();
}

/* Kutuları ekrana sığdır: kaydırma gerekmeyecek en büyük kutu genişliğini bulur. */
function layoutGrid() {
  const grid = $('grid');
  const count = tiles.size;
  if (!$('fit').checked || count === 0) {
    grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${$('tileSize').value}px, 1fr))`;
    return;
  }
  const wrap = $('gridWrap');
  const gap = 12;
  const caption = 36;
  const width = wrap.clientWidth - 32;
  const height = wrap.clientHeight - 32;
  let best = 1;
  for (let cols = 1; cols <= count; cols += 1) {
    const tileWidth = (width - (cols - 1) * gap) / cols;
    if (tileWidth < 150) break;
    const rowsNeeded = Math.ceil(count / cols);
    const total = rowsNeeded * (tileWidth * 9 / 16 + caption) + (rowsNeeded - 1) * gap;
    best = cols;
    if (total <= height) break;       // ilk sığan sütun sayısı = en büyük kutu
  }
  const tileWidth = Math.min(560, (width - (best - 1) * gap) / best);
  grid.style.gridTemplateColumns = `repeat(${best}, minmax(0, ${Math.floor(tileWidth)}px))`;
}
window.addEventListener('resize', layoutGrid);

/* ----------------------------------------------------------------- üst bölüm */

function renderHeader() {
  setText($('className'), S.class.sinif_adi);
  setText($('teacherName'), S.class.ogretmen_adi);
  document.title = `Sınav İzleme — ${S.class.sinif_adi}`;

  const state = S.exam.state;
  setText($('examState'), STATE_TEXT[state] || state);
  const exam = document.querySelector('.exam');
  exam.classList.toggle('running', state === 'RUNNING');
  exam.classList.toggle('ended', state === 'ENDED');

  $('setup').hidden = state !== 'WAITING';
  $('btnEnd').hidden = state !== 'RUNNING';
  $('btnExportTop').hidden = state !== 'ENDED';
  $('btnResetTop').hidden = state !== 'ENDED';
  $('btnReset').disabled = state === 'RUNNING';

  const file = S.exam.file;
  setText($('examFileInfo'), file ? file.name : 'Henüz seçilmedi');
  $('examFileInfo').title = file ? file.name : '';
  $('btnExamFile').parentElement.classList.toggle('done', Boolean(file));
  setText($('btnExamFile'), file ? 'Değiştir' : 'Dosya seç');
  setText($('rosterInfo'), S.roster.count ? `${S.roster.count} öğrenci — ${S.roster.name}` : 'Yüklenmedi');
  $('btnRoster').parentElement.classList.toggle('done', S.roster.count > 0);
  setText($('btnRoster'), S.roster.count ? 'Değiştir' : 'Dosya seç');
  $('btnStart').disabled = !file;
  $('btnStart').title = file ? 'Dosyayı paylaşmak sınavı başlatır' : 'Önce sınav dosyasını seçin';

  renderMenuInfo();
  renderBanners();
  renderTimer();
}

function renderMenuInfo() {
  const lines = [];
  const ips = S.health.lan_ips;
  if (ips.length) {
    lines.push(`Ajan sunucuyu kendisi bulamazsa öğrenci şu adresi yazabilir: ${ips.join(' veya ')}`);
  }
  lines.push(`Teslim dosyaları: ${S.paths.submissions}`);
  lines.push(`Ekran kayıtları: ${S.paths.recordings}`);
  const box = $('menuInfo');
  const signature = lines.join('\n');
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  box.replaceChildren(...lines.map((line) => el('div', '', line)));
}

function renderBanners() {
  const messages = [];
  const health = S.health;
  if (!health.mediamtx_ok) {
    messages.push('Ekran görüntüleri alınamıyor ve kayıt yapılmıyor. Başlatma penceresini kapatıp '
      + 'start-teacher.bat dosyasını yeniden çalıştırın.');
  }
  if (health.discovery_error) messages.push(health.discovery_error);
  if (health.config_error) messages.push(health.config_error);
  if (!health.lan_ips.length) {
    messages.push('Bu bilgisayar bir ağa bağlı görünmüyor. Sınıf modemine bağlı olduğunuzdan emin olun.');
  }
  const box = $('banners');
  const signature = JSON.stringify(messages);
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  box.replaceChildren(...messages.map((text) => el('div', 'banner', text)));
}

function renderTimer() {
  if (!S) return;
  const exam = S.exam;
  // Süre tutulmaz; yalnızca başlangıç (ve bitiş) saati gösterilir.
  let text = '';
  if (exam.state === 'RUNNING' && exam.started_at) {
    text = `başlangıç ${fmtClock(exam.started_at)}`;
  } else if (exam.state === 'ENDED' && exam.started_at) {
    text = `${fmtClock(exam.started_at)} – ${fmtClock(exam.ended_at)}`;
  }
  setText($('timer'), text);
}

/* ----------------------------------------------------------------- öğrenci listesi (sağ) */

function summaryItem(dotColor, count, label) {
  const item = el('span');
  const dot = el('span', 'dot');
  dot.style.background = dotColor;
  item.append(dot, el('b', '', String(count)), document.createTextNode(` ${label}`));
  return item;
}

function renderSummary() {
  const sum = S.summary;
  const signature = `${sum.connected}|${sum.warned}|${sum.lost}|${sum.submitted}`;
  const box = $('summary');
  if (box.dataset.signature !== signature) {
    box.dataset.signature = signature;
    box.replaceChildren(
      summaryItem('var(--ok)', sum.connected, 'bağlı'),
      summaryItem('var(--warn)', sum.warned, 'uyarılı'),
      summaryItem('var(--lost)', sum.lost, 'kopuk'),
      summaryItem('var(--done)', sum.submitted, 'teslim etti'),
    );
  }
  const attention = S.students.filter(needsAttention).length;
  setText($('countAll'), String(S.students.length));
  setText($('countAlerts'), String(attention));
  $('filterAlerts').classList.toggle('attention', attention > 0);
}

function createRow(numara) {
  const root = el('li', 'row');
  root.dataset.numara = numara;

  const head = el('button', 'row-head');
  head.type = 'button';
  const who = el('span', 'who');
  const name = el('span', 'name');
  who.append(el('span', 'num', numara), name);
  const status = el('span', 'status');
  head.append(el('span', 'dot'), who, status, el('span', 'chev'));

  const alert = el('div', 'row-alert');
  alert.hidden = true;

  const body = el('div', 'row-body');
  body.hidden = true;
  const events = el('ul', 'row-events');
  const meta = el('div', 'row-meta');
  const actions = el('div', 'row-actions');
  const zoom = el('button', '', 'Ekranı büyüt');
  zoom.type = 'button';
  const ack = el('button', '', 'Görüldü');
  ack.type = 'button';
  actions.append(zoom, ack);
  body.append(events, meta, actions);
  root.append(head, alert, body);

  head.addEventListener('click', () => toggleRow(numara));
  zoom.addEventListener('click', () => openModal(numara));
  ack.addEventListener('click', async () => {
    try { await api('/panel/api/ack', { json: { numara } }); } catch (error) { toast(error.message, true); }
  });

  return { root, head, name, status, alert, body, events, meta, ack, statusClass: '', signature: '', eventSignature: '' };
}

function toggleRow(numara) {
  if (expanded.has(numara)) expanded.delete(numara);
  else expanded.add(numara);
  renderList();
}

function rowStatusText(st) {
  const warnings = st.warn_count > 0 ? `${st.warn_count} uyarı` : '';
  if (st.status === 'ok') return '';
  if (st.status === 'warn') return warnings;
  const base = STATUS_TEXT[st.status] || st.status;
  return warnings ? `${base} · ${warnings}` : base;
}

function renderList() {
  renderSummary();
  const latest = latestAlerts();
  let students = S.students;
  if (filter === 'alerts') {
    students = students.filter(needsAttention).sort((a, b) => {
      const ta = latest.has(a.numara) ? latest.get(a.numara).ts : 0;
      const tb = latest.has(b.numara) ? latest.get(b.numara).ts : 0;
      return tb - ta;                       // en yeni uyarı üstte
    });
  }

  const list = $('studentList');
  const seen = new Set();
  let previous = null;
  for (const st of students) {
    seen.add(st.numara);
    let row = rows.get(st.numara);
    if (!row) {
      row = createRow(st.numara);
      rows.set(st.numara, row);
    }
    const expectedNext = previous ? previous.root.nextSibling : list.firstChild;
    if (expectedNext !== row.root) list.insertBefore(row.root, expectedNext);
    previous = row;
    updateRow(row, st, latest.get(st.numara));
  }
  for (const [numara, row] of rows) {
    if (!seen.has(numara)) {
      row.root.remove();
      rows.delete(numara);
    }
  }

  const emptyBox = $('listEmpty');
  emptyBox.hidden = students.length > 0;
  if (students.length === 0) {
    setText(emptyBox, filter === 'alerts' ? 'Dikkat gerektiren öğrenci yok.' : 'Henüz giriş yapan öğrenci yok.');
  }

  const general = S.alerts.filter((a) => !a.numara && a.severity !== 'info').slice(0, 3);
  const generalBox = $('general');
  generalBox.hidden = general.length === 0;
  const generalSignature = general.map((a) => a.id).join(',');
  if (generalBox.dataset.signature !== generalSignature) {
    generalBox.dataset.signature = generalSignature;
    generalBox.replaceChildren(...general.map((a) => el('div', '', `${a.message} (${fmtClock(a.ts)})`)));
  }

  const missing = S.roster.missing;
  $('missing').hidden = missing.length === 0;
  setText($('missingCount'), String(missing.length));
  const missingSignature = missing.map((m) => m.numara).join(',');
  const missingList = $('missingList');
  if (missingList.dataset.signature !== missingSignature) {
    missingList.dataset.signature = missingSignature;
    missingList.replaceChildren(...missing.map((m) => el('div', '', `${m.numara} ${m.ad} ${m.soyad}`.trim())));
  }
}

function updateRow(row, st, alert) {
  const open = expanded.has(st.numara);
  const statusClass = `st-${st.status}`;
  if (row.statusClass !== statusClass) {
    if (row.statusClass) row.root.classList.remove(row.statusClass);
    row.root.classList.add(statusClass);
    row.statusClass = statusClass;
  }
  row.root.classList.toggle('open', open);
  row.head.setAttribute('aria-expanded', open ? 'true' : 'false');
  setText(row.name, fullName(st));
  setText(row.status, rowStatusText(st));

  // Satırdaki uyarı: en son görülmemiş uyarı ya da bağlantı durumu.
  let alertText = '';
  let alertTime = '';
  if (st.status === 'lost') {
    alertText = statusText(st);
  } else if (st.warn_count > 0 && alert) {
    alertText = alert.message;
    alertTime = fmtClock(alert.ts);
  }
  const signature = `${alertText}|${alertTime}`;
  if (row.signature !== signature) {
    row.signature = signature;
    row.alert.replaceChildren(document.createTextNode(alertText));
    if (alertTime) row.alert.append(el('span', 'when', alertTime));
  }
  row.alert.hidden = alertText === '' || open;

  row.body.hidden = !open;
  if (!open) return;

  row.ack.hidden = st.warn_count === 0;
  setText(row.meta, [st.ip, st.hostname, st.mac].filter(Boolean).join(' · '));
  row.meta.title = 'IP adresi · bilgisayar adı · ağ (MAC) adresi';

  const cached = eventCache.get(st.numara);
  if (!cached || cached.count !== st.ev_count) loadEvents(st.numara, st.ev_count);
  const events = cached ? cached.events.filter((e) => e.alert).slice(-ROW_EVENT_LIMIT).reverse() : null;
  const eventSignature = events ? events.map((e) => e.id).join(',') : 'loading';
  if (row.eventSignature !== eventSignature) {
    row.eventSignature = eventSignature;
    if (!events) {
      row.events.replaceChildren(el('li', 'none', 'Yükleniyor…'));
    } else if (events.length === 0) {
      row.events.replaceChildren(el('li', 'none', 'Bu öğrenci için uyarı yok.'));
    } else {
      row.events.replaceChildren(...events.map((event) => {
        const li = el('li');
        li.append(el('span', 'when', fmtClock(event.ts)), document.createTextNode(event.message));
        return li;
      }));
    }
  }
}

const loadingEvents = new Set();
async function loadEvents(numara, count) {
  if (loadingEvents.has(numara)) return;
  loadingEvents.add(numara);
  try {
    const data = await api(`/panel/api/events?numara=${encodeURIComponent(numara)}`, { method: 'GET' });
    eventCache.set(numara, { count, events: data.events });
    if (S) {
      renderList();
      renderModal();
    }
  } catch (_) {
    /* bir sonraki güncellemede yeniden denenir */
  } finally {
    loadingEvents.delete(numara);
  }
}

function setFilter(next) {
  filter = next;
  $('filterAll').classList.toggle('active', next === 'all');
  $('filterAlerts').classList.toggle('active', next === 'alerts');
  if (S) renderList();
}

/* ----------------------------------------------------------------- sesli uyarı */

function checkNewAlerts() {
  const newest = S.alerts.length ? S.alerts[0].id : 0;
  if (lastAlertId !== null && newest > lastAlertId) {
    const fresh = S.alerts.filter((a) => a.id > lastAlertId && a.severity !== 'info');
    if (fresh.length) beep(fresh.some((a) => a.severity === 'critical'));
  }
  lastAlertId = newest;
}

/* ----------------------------------------------------------------- tek öğrenci görünümü */

function openModal(numara) {
  if (!tiles.has(numara)) return;
  modalNumara = numara;
  modalEvCount = -1;
  $('modalEvents').replaceChildren();
  $('modalDetails').open = false;
  $('modal').hidden = false;
  renderModal();
}

function closeModal() {
  const previous = modalNumara;
  modalNumara = null;
  $('modal').hidden = true;
  $('bigVideo').srcObject = null;
  const tile = previous && tiles.get(previous);
  if (tile) updatePlayback(tile);
}

function infoRow(list, label, value) {
  if (value === '' || value === null || value === undefined) return;
  list.append(el('dt', '', label), el('dd', '', String(value)));
}

function renderModal() {
  if (!modalNumara) return;
  const tile = tiles.get(modalNumara);
  if (!tile || !tile.data) {
    closeModal();
    return;
  }
  const st = tile.data;
  updatePlayback(tile);

  setText($('modalTitle'), `${st.numara} — ${fullName(st)}`);
  const status = $('modalStatus');
  status.className = `modal-status st-${st.status}`;
  const statusSignature = statusText(st);
  if (status.dataset.signature !== statusSignature) {
    status.dataset.signature = statusSignature;
    status.replaceChildren(el('span', 'dot'), document.createTextNode(statusSignature));
  }
  $('modalAck').disabled = st.warn_count === 0;

  // Büyük görüntü, kutudaki akışın aynısını paylaşır (ikinci bağlantı açılmaz).
  const big = $('bigVideo');
  const stream = tile.video.srcObject;
  if (big.srcObject !== stream) {
    big.srcObject = stream;
    if (stream) {
      const playing = big.play();
      if (playing && playing.catch) playing.catch(() => {});
    }
  }
  const noVideo = $('bigNoVideo');
  noVideo.hidden = Boolean(stream);
  setText(noVideo, noVideoText(st));

  const info = document.createDocumentFragment();
  infoRow(info, 'IP adresi', st.ip);
  infoRow(info, 'Bilgisayar adı', st.hostname);
  infoRow(info, 'Ağ (MAC) adresi', st.mac);
  infoRow(info, 'Öğrenci listesi', ROSTER_TEXT[st.roster] || st.roster);
  infoRow(info, 'Giriş saati', fmtClockSeconds(st.login_ts) + (st.login_count > 1 ? ` (${st.login_count}. giriş)` : ''));
  infoRow(info, 'Açık pencere', st.fg_process ? `${st.fg_process}${st.fg_title ? ` — ${st.fg_title}` : ''}` : '');
  if (st.monitors > 1) infoRow(info, 'Monitör sayısı', st.monitors);
  if (st.submission) {
    const sub = st.submission;
    infoRow(info, 'Teslim', `${sub.filename}${sub.auto ? ' (otomatik)' : ''}, ${fmtClockSeconds(sub.ts)}`);
    infoRow(info, 'Dosya özeti', sub.sha256);
  }
  const sep = S.paths.recordings.includes('\\') ? '\\' : '/';
  infoRow(info, 'Kayıt klasörü', `${S.paths.recordings}${sep}s${sep}${st.numara}`);
  $('modalInfo').replaceChildren(info);

  const cached = eventCache.get(st.numara);
  if (!cached || cached.count !== st.ev_count) loadEvents(st.numara, st.ev_count);
  if (cached && modalEvCount !== cached.events.length) {
    modalEvCount = cached.events.length;
    const items = cached.events.slice().reverse().map((event) => {
      const li = el('li', `sev-${event.severity}${event.alert ? '' : ' minor'}`);
      li.append(el('span', 'when', fmtClockSeconds(event.ts)), document.createTextNode(event.message));
      return li;
    });
    $('modalEvents').replaceChildren(...items);
  }
}

/* ----------------------------------------------------------------- ana çizim + canlı bağlantı */

function render() {
  renderHeader();
  renderTiles();
  renderList();
  renderModal();
  checkNewAlerts();
}

function connectStream() {
  const source = new EventSource('/panel/api/stream');
  source.onmessage = (message) => {
    S = JSON.parse(message.data);
    const down = $('banners').querySelector('.server-down');
    if (down) { down.remove(); $('banners').dataset.signature = ''; }
    render();
  };
  source.onerror = () => {
    // EventSource kendiliğinden yeniden bağlanır; bu arada durumu göster.
    const box = $('banners');
    if (!box.querySelector('.server-down')) {
      box.prepend(el('div', 'banner server-down',
        'Sunucuyla bağlantı kesildi. Başlatma penceresi (start-teacher.bat) açık mı? Yeniden bağlanılıyor…'));
    }
  };
}

/* ----------------------------------------------------------------- denetimler */

async function uploadFile(input, path, successText) {
  const file = input.files[0];
  input.value = '';
  if (!file) return;
  const form = new FormData();
  form.append('file', file, file.name);
  try {
    const data = await api(path, { body: form });
    toast(successText(file, data));
  } catch (error) {
    toast(error.message, true);
  }
}

function closeMenu() {
  $('menu').hidden = true;
  $('btnMenu').setAttribute('aria-expanded', 'false');
}

async function resetExam() {
  closeMenu();
  const question = 'Yeni sınav hazırlansın mı?\n\n'
    + 'Bu sınavın teslim dosyaları ve olay kaydı silinmez; tarihli bir arşiv klasörüne taşınır. '
    + 'Öğrenci listesi korunur.';
  if (!confirm(question)) return;
  try {
    await api('/panel/api/reset');
    toast('Yeni sınav hazır.');
  } catch (error) {
    toast(error.message, true);
  }
}

function bindControls() {
  $('btnExamFile').addEventListener('click', () => $('fileExam').click());
  $('fileExam').addEventListener('change', () => uploadFile(
    $('fileExam'), '/panel/api/exam-file', (file) => `Sınav dosyası yüklendi: ${file.name}`));

  const chooseRoster = () => { closeMenu(); $('fileRoster').click(); };
  $('btnRoster').addEventListener('click', chooseRoster);
  $('btnRosterMenu').addEventListener('click', chooseRoster);
  $('fileRoster').addEventListener('change', () => uploadFile(
    $('fileRoster'), '/panel/api/roster', (file, data) => `Öğrenci listesi yüklendi: ${data.count} öğrenci`));

  $('btnStart').addEventListener('click', async () => {
    const question = 'Sınav dosyası paylaşılsın mı?\n\n'
      + 'Paylaştığınız anda sınav başlar: öğrencilerde izin verilmeyen programlar kısa bir geri sayımdan '
      + 'sonra kapatılır ve öğrenciler dosyayı indirebilir.';
    if (!confirm(question)) return;
    try {
      await api('/panel/api/start');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnEnd').addEventListener('click', async () => {
    const question = 'Sınavı bitirmek istediğinize emin misiniz?\n\n'
      + 'Teslim etmemiş öğrencilerin son kaydettiği dosya otomatik toplanır ve öğrenci programları kapanır. '
      + 'Bu işlem geri alınamaz.';
    if (!confirm(question)) return;
    try {
      await api('/panel/api/end');
      toast('Sınav bitirildi. Teslimler toplanıyor…');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnReset').addEventListener('click', resetExam);
  $('btnResetTop').addEventListener('click', resetExam);
  $('btnExport').addEventListener('click', closeMenu);

  $('btnMenu').addEventListener('click', (event) => {
    event.stopPropagation();
    const open = $('menu').hidden;
    $('menu').hidden = !open;
    $('btnMenu').setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  $('menu').addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', closeMenu);

  $('filterAll').addEventListener('click', () => setFilter('all'));
  $('filterAlerts').addEventListener('click', () => setFilter('alerts'));

  $('modalAck').addEventListener('click', async () => {
    if (!modalNumara) return;
    try { await api('/panel/api/ack', { json: { numara: modalNumara } }); } catch (error) { toast(error.message, true); }
  });
  $('modalClose').addEventListener('click', closeModal);
  $('modal').addEventListener('click', (event) => { if (event.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (modalNumara) closeModal();
    else closeMenu();
  });

  const sound = $('sound');
  sound.checked = pref('sound', '0') === '1';
  sound.addEventListener('change', () => {
    setPref('sound', sound.checked ? '1' : '0');
    if (sound.checked) beep(false);   // kullanıcı etkileşimiyle sesi aç + örnek ses
  });

  const pause = $('pauseHidden');
  pause.checked = pref('pauseHidden', '0') === '1';
  pause.addEventListener('change', () => {
    setPref('pauseHidden', pause.checked ? '1' : '0');
    tiles.forEach(updatePlayback);
  });

  const fit = $('fit');
  const size = $('tileSize');
  fit.checked = pref('fit', '1') === '1';
  size.value = pref('tileSize', '230');
  size.disabled = fit.checked;
  fit.addEventListener('change', () => {
    setPref('fit', fit.checked ? '1' : '0');
    size.disabled = fit.checked;
    layoutGrid();
  });
  size.addEventListener('input', () => { setPref('tileSize', size.value); layoutGrid(); });
}

bindControls();
connectStream();
