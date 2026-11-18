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
  nofile: 'Dosya klasörde yok',
};
const STATE_TEXT = { WAITING: 'Sınav başlamadı', RUNNING: 'Sınav sürüyor', ENDED: 'Sınav bitti' };
const ROSTER_TEXT = {
  no_roster: 'Liste yüklü değil',
  ok: 'Listede',
  name_mismatch: 'Listede, ad uyuşmuyor',
  not_in_list: 'Listede yok',
};
const ROW_EVENT_LIMIT = 6;
const ALERT_LIST_LIMIT = 200;
const SIZE_MIN = 140;
const SIZE_MAX = 900;
const SIZE_STEP = 40;

let S = null;                    // sunucudan gelen son durum
let lastAlertId = null;          // sesli uyarı için
let filter = 'all';              // 'all' (öğrenciler) | 'alerts' (uyarı listesi)
let fitTiles = true;             // ekranları kaydırmadan sığdır
let sideCollapsed = false;       // sağdaki öğrenci listesi daraltıldı
let folderBusy = false;          // klasör seçme penceresi açık
let byNumara = new Map();        // numara -> öğrenci (son durum)
let receivedAt = 0;              // son durumun geldiği an (Date.now())
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

/* Kalan süre: 1:05:09 ya da 34:12. */
function fmtRemaining(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = String(total % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
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
  if (!response.ok) {
    const error = new Error(data.error || `Hata (${response.status})`);
    error.status = response.status;
    throw error;
  }
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
      const url = `${S.webrtc_base}/${encodeURIComponent(this.numara)}/whep`;
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
  if (st.status === 'nofile') return 'Teslim dosyası klasörde yok';
  return STATUS_TEXT[st.status] || st.status;
}

function noVideoText(st) {
  if (st.status === 'done') return 'Teslim etti';
  if (st.status === 'nosubmit') return 'Teslim yok';
  if (st.status === 'nofile') return 'Dosya klasörde yok';
  if (st.status === 'lost') return 'Bağlantı yok';
  return st.stream_ready ? 'Görüntü bağlanıyor…' : 'Ekran bekleniyor…';
}

/* Uyarı listesinde gösterilecek olaylar (en yeni üstte). */
function warningAlerts() {
  return S.alerts.filter((alert) => alert.severity !== 'info');
}

/* Öğretmen "görüldü" dedikten sonra gelen uyarılar görülmemiş sayılır. */
function isUnseen(alert) {
  if (!alert.numara) return alert.id > (S.general_ack_id || 0);
  const st = byNumara.get(alert.numara);
  return alert.id > (st ? st.ack_id || 0 : 0);
}

/* Her öğrencinin en son görülmemiş uyarısı (S.alerts en yeni üstte gelir). */
function latestAlerts() {
  const latest = new Map();
  for (const alert of warningAlerts()) {
    if (alert.numara && !latest.has(alert.numara) && isUnseen(alert)) latest.set(alert.numara, alert);
  }
  return latest;
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
  // Teslim edenlerin ekranı sona gider; kalanlar numara sırasıyla üstte durur.
  const ordered = S.students.slice().sort((a, b) => Number(a.status === 'done') - Number(b.status === 'done'));
  for (const st of ordered) {
    seen.add(st.numara);
    let tile = tiles.get(st.numara);
    if (!tile) {
      tile = createTile(st.numara);
      tiles.set(st.numara, tile);
    }
    // DOM sırasını yukarıdaki sıraya uydur.
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

/* Ekran boyutu: "Sığdır" açıkken kaydırma gerekmeyecek en büyük genişlik bulunur;
 * kapalıyken her ekran, kaydırıcıda seçilen genişlikte çizilir. */
function layoutGrid() {
  const grid = $('grid');
  const wrap = $('gridWrap');
  const count = tiles.size;
  const gap = 12;
  const width = wrap.clientWidth - 32;
  if (!fitTiles || count === 0) {
    const size = Math.max(SIZE_MIN, Math.min(Number($('tileSize').value), width));
    grid.style.gridTemplateColumns = `repeat(auto-fill, ${Math.floor(size)}px)`;
    return;
  }
  const caption = 36;
  const height = wrap.clientHeight - 32;
  let best = 1;
  for (let cols = 1; cols <= count; cols += 1) {
    const tileWidth = (width - (cols - 1) * gap) / cols;
    if (tileWidth < SIZE_MIN) break;
    const rowsNeeded = Math.ceil(count / cols);
    const total = rowsNeeded * (tileWidth * 9 / 16 + caption) + (rowsNeeded - 1) * gap;
    best = cols;
    if (total <= height) break;       // ilk sığan sütun sayısı = en büyük kutu
  }
  const tileWidth = Math.min(640, (width - (best - 1) * gap) / best);
  grid.style.gridTemplateColumns = `repeat(${best}, minmax(0, ${Math.floor(tileWidth)}px))`;
  // Kaydırıcı, "Sığdır"ın bulduğu boyutu göstersin: − / + oradan devam eder.
  if (document.activeElement !== $('tileSize')) $('tileSize').value = String(Math.round(tileWidth));
}
window.addEventListener('resize', layoutGrid);

function setFit(on) {
  fitTiles = on;
  $('fit').setAttribute('aria-pressed', on ? 'true' : 'false');
  setPref('fit', on ? '1' : '0');
  layoutGrid();
}

/* Sağdaki listeyi ince bir şeride daralt / yeniden aç; ekranlar boşalan yeri kullanır. */
function setSideCollapsed(collapsed) {
  sideCollapsed = collapsed;
  $('side').classList.toggle('collapsed', collapsed);
  setPref('sideCollapsed', collapsed ? '1' : '0');
  layoutGrid();
  setTimeout(layoutGrid, 220);      // genişlik geçişi bittikten sonra bir kez daha
}

function setTileSize(value) {
  const size = Math.max(SIZE_MIN, Math.min(SIZE_MAX, Math.round(value)));
  $('tileSize').value = String(size);
  setPref('tileSize', size);
  setFit(false);
}

/* ----------------------------------------------------------------- üst bölüm */

function renderHeader() {
  setText($('className'), S.class.sinif_adi);
  setText($('teacherName'), S.class.ogretmen_adi);
  document.title = `Sınav İzleme — ${S.class.sinif_adi}`;

  const state = S.exam.state;
  const plan = state === 'WAITING' ? S.exam.scheduled : null;
  setText($('examState'), plan ? 'Sınav planlandı' : (STATE_TEXT[state] || state));
  const exam = document.querySelector('.exam');
  exam.classList.toggle('running', state === 'RUNNING');
  exam.classList.toggle('ended', state === 'ENDED');

  $('setup').hidden = state !== 'WAITING';
  $('btnEnd').hidden = state !== 'RUNNING';
  $('btnResetTop').hidden = state !== 'ENDED';
  $('btnReset').disabled = state === 'RUNNING';
  // Sınav sürerken ad değiştirilemez: öğrenciler bu adla bağlandı.
  $('btnIdentity').hidden = state === 'RUNNING';

  const folder = S.exam.folder;
  $('btnOpenFolderTop').hidden = state !== 'ENDED' || !folder;
  $('btnOpenFolder').disabled = !folder;
  const folderInfo = $('folderInfo').firstElementChild;
  setText(folderInfo, folder || 'Kayıtlar ve teslimler buraya gelir');
  $('folderInfo').title = folder
    ? `${folder}\nİçinde “Kayıtlar” (ekran kayıtları) ve “Teslimler” (teslim edilen dosyalar) klasörleri açıldı.`
    : 'Seçtiğiniz klasörün içinde “Kayıtlar” ve “Teslimler” klasörleri açılır.';
  $('btnFolder').parentElement.classList.toggle('done', Boolean(folder));
  $('btnFolder').disabled = folderBusy;
  setText($('btnFolder'), folderBusy ? 'Pencere açık…' : (folder ? 'Değiştir' : 'Klasör seç'));

  const file = S.exam.file;
  setText($('examFileInfo'), file ? file.name : 'Henüz seçilmedi');
  $('examFileInfo').title = file ? file.name : '';
  $('btnExamFile').parentElement.classList.toggle('done', Boolean(file));
  setText($('btnExamFile'), file ? 'Değiştir' : 'Dosya seç');
  setText($('rosterInfo'), S.roster.count ? `${S.roster.count} öğrenci — ${S.roster.name}` : 'Yüklenmedi');
  $('btnRoster').parentElement.classList.toggle('done', S.roster.count > 0);
  setText($('btnRoster'), S.roster.count ? 'Değiştir' : 'Dosya seç');
  $('btnStart').disabled = !file || !folder;
  let startHint = 'Başlangıç saatini, süreyi ve ekran kaydını seçersiniz';
  if (!folder) startHint = 'Önce sınav klasörünü seçin';
  else if (!file) startHint = 'Önce sınav dosyasını seçin: sınav başlayınca öğrencilerle paylaşılır';
  $('btnStart').title = startHint;
  // Planlanmış başlangıç: düğmenin yerinde saat ve "İptal et" görünür.
  $('btnStart').hidden = Boolean(plan);
  $('scheduledBox').hidden = !plan;
  if (plan) {
    const details = [plan.duration_min ? `${plan.duration_min} dakika` : 'süre yok',
      plan.record ? 'ekranlar kaydedilecek' : 'ekranlar kaydedilmeyecek'];
    setText($('scheduledText'), `Sınav saat ${fmtClock(plan.at)} için planlandı`);
    $('scheduledBox').title = details.join(', ');
  }
  $('btnExtend').hidden = !(state === 'RUNNING' && S.exam.ends_at);

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
  if (S.exam.folder) {
    lines.push(`Sınav klasörü: ${S.exam.folder}`);
  } else {
    lines.push('Sınav klasörü seçilmedi: ekranlar henüz kaydedilmiyor.');
  }
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
  if (health.folder_error) {
    messages.push(`${health.folder_error}. Teslimler alınamıyor ve kayıt yapılamıyor; klasörün bulunduğu `
      + 'disk takılı mı?');
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
  const parts = [];
  let ending = false;
  if (exam.state === 'WAITING' && exam.scheduled) {
    parts.push(`başlangıç ${fmtClock(exam.scheduled.at)}`);
  } else if (exam.state === 'RUNNING' && exam.started_at) {
    parts.push(`başlangıç ${fmtClock(exam.started_at)}`);
    if (exam.ends_at) {
      // Sunucunun saatine göre hesaplanır; tarayıcı saati yanlış olsa da doğru kalır.
      const serverNow = S.server_time + (Date.now() - receivedAt) / 1000;
      const remaining = exam.ends_at - serverNow;
      parts.push(`kalan ${fmtRemaining(remaining)}`);
      ending = remaining <= 300;
    }
    parts.push(exam.record ? 'kayıt açık' : 'kayıt kapalı');
  } else if (exam.state === 'ENDED' && exam.started_at) {
    parts.push(`${fmtClock(exam.started_at)} – ${fmtClock(exam.ended_at)}`);
  }
  setText($('timer'), parts.join(' · '));
  $('timer').classList.toggle('ending', ending);
}
setInterval(renderTimer, 500);

/* ----------------------------------------------------------------- öğrenci listesi (sağ) */

function summaryItem(dotColor, count, label) {
  const item = el('span');
  const dot = el('span', 'dot');
  dot.style.background = dotColor;
  item.append(dot, el('b', '', String(count)), document.createTextNode(` ${label}`));
  return item;
}

function railItem(dotColor, count, label) {
  const item = el('span');
  item.title = `${count} ${label}`;
  const dot = el('span', 'dot');
  dot.style.background = dotColor;
  item.append(dot, document.createTextNode(String(count)));
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
  // Daraltılmış şerit: aynı sayılar alt alta.
  const rail = $('railSummary');
  if (rail.dataset.signature !== signature) {
    rail.dataset.signature = signature;
    rail.replaceChildren(
      railItem('var(--ok)', sum.connected, 'bağlı'),
      railItem('var(--warn)', sum.warned, 'uyarılı'),
      railItem('var(--lost)', sum.lost, 'kopuk'),
      railItem('var(--done)', sum.submitted, 'teslim etti'),
    );
  }
  const unseen = warningAlerts().filter(isUnseen).length;
  $('railAlerts').hidden = unseen === 0;
  setText($('railAlerts'), unseen > 99 ? '99+' : String(unseen));
  $('railAlerts').title = `${unseen} görülmemiş uyarı`;
  setText($('countAll'), String(S.students.length));
  setText($('countAlerts'), unseen > 99 ? '99+' : String(unseen));
  $('filterAlerts').classList.toggle('attention', unseen > 0);
  $('ackAll').hidden = filter !== 'alerts' || unseen === 0;
}

function createRow(numara) {
  const root = el('li', 'row');
  root.dataset.numara = numara;

  // Tek satır: durum noktası, numara + ad, sağda (varsa) son uyarı ya da durum.
  const head = el('button', 'row-head');
  head.type = 'button';
  const who = el('span', 'who');
  const name = el('span', 'name');
  who.append(el('span', 'num', numara), name);
  const note = el('span', 'note');
  const count = el('span', 'count');
  count.hidden = true;
  head.append(el('span', 'dot'), who, note, count, el('span', 'chev'));

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
  root.append(head, body);

  head.addEventListener('click', () => toggleRow(numara));
  zoom.addEventListener('click', () => openModal(numara));
  ack.addEventListener('click', async () => {
    try { await api('/panel/api/ack', { json: { numara } }); } catch (error) { toast(error.message, true); }
  });

  return { root, head, name, note, count, body, events, meta, ack, statusClass: '', metaSignature: '', eventSignature: '' };
}

function toggleRow(numara) {
  if (expanded.has(numara)) expanded.delete(numara);
  else expanded.add(numara);
  renderList();
}

/* Satırın sağındaki tek satırlık not: görülmemiş son uyarı, yoksa durum. */
function rowNote(st, alert) {
  if (st.status === 'lost' || st.status === 'nofile' || st.status === 'nosubmit') return statusText(st);
  if (alert) return alert.message;
  if (st.status === 'done') return STATUS_TEXT.done;
  return '';
}

function renderList() {
  renderSummary();
  const showAlerts = filter === 'alerts';
  $('studentList').hidden = showAlerts;
  $('alertList').hidden = !showAlerts;
  if (showAlerts) renderAlertList();
  else renderStudentList();

  const missing = S.roster.missing;
  $('missing').hidden = missing.length === 0 || showAlerts;
  setText($('missingCount'), String(missing.length));
  const missingSignature = missing.map((m) => m.numara).join(',');
  const missingList = $('missingList');
  if (missingList.dataset.signature !== missingSignature) {
    missingList.dataset.signature = missingSignature;
    missingList.replaceChildren(...missing.map((m) => el('div', '', `${m.numara} ${m.ad} ${m.soyad}`.trim())));
  }
}

function renderStudentList() {
  const latest = latestAlerts();
  const list = $('studentList');
  const seen = new Set();
  let previous = null;
  for (const st of S.students) {
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
  emptyBox.hidden = S.students.length > 0;
  setText(emptyBox, 'Henüz giriş yapan öğrenci yok.');
}

/* "Uyarılar": bütün uyarılar tek satırlık, en yenisi üstte olan düz bir liste. */
function renderAlertList() {
  const alerts = warningAlerts().slice(0, ALERT_LIST_LIMIT);
  const list = $('alertList');
  const signature = alerts.map((a) => `${a.id}${isUnseen(a) ? '!' : ''}${tiles.has(a.numara) ? '' : '-'}`).join(',');
  if (list.dataset.signature !== signature) {
    list.dataset.signature = signature;
    list.replaceChildren(...alerts.map(alertItem));
  }
  const emptyBox = $('listEmpty');
  emptyBox.hidden = alerts.length > 0;
  setText(emptyBox, 'Henüz uyarı yok.');
}

function alertItem(alert) {
  const item = el('li', `alert sev-${alert.severity}${isUnseen(alert) ? '' : ' seen'}`);
  const line = el('button', 'alert-line');
  line.type = 'button';
  const who = alert.numara ? `${alert.numara} ${alert.name}`.trim() : 'Genel';
  line.append(el('span', 'dot'), el('span', 'when', fmtClock(alert.ts)), el('span', 'who', who),
    el('span', 'msg', alert.message));
  line.title = `${fmtClockSeconds(alert.ts)} — ${who}: ${alert.message}`;
  if (alert.numara && tiles.has(alert.numara)) line.addEventListener('click', () => openModal(alert.numara));
  else line.disabled = true;
  item.append(line);
  return item;
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
  const note = rowNote(st, alert);
  setText(row.note, note);
  row.head.title = note ? `${st.numara} ${fullName(st)} — ${note}` : '';
  row.count.hidden = st.warn_count < 2;
  setText(row.count, String(st.warn_count));

  row.body.hidden = !open;
  if (!open) return;

  row.ack.hidden = st.warn_count === 0;
  const metaLines = [[st.ip, st.hostname, st.mac].filter(Boolean).join(' · ')];
  let fileMissing = false;
  if (st.submission) {
    fileMissing = st.status === 'nofile';
    metaLines.push(`Teslim: ${st.submission.filename}, ${fmtClock(st.submission.ts)}`
      + (fileMissing ? ' — klasörde yok' : ''));
  }
  const metaSignature = metaLines.join('|');
  if (row.metaSignature !== metaSignature) {
    row.metaSignature = metaSignature;
    row.meta.replaceChildren(...metaLines.map((text, index) => {
      const line = el('div', index === 1 && fileMissing ? 'bad' : '', text);
      line.title = index === 0 ? `IP adresi · bilgisayar adı · ağ (MAC) adresi\n${text}` : text;
      return line;
    }));
  }

  const cached = eventCache.get(st.numara);
  if (!cached || cached.count !== st.ev_count) loadEvents(st.numara, st.ev_count);
  const events = cached
    ? cached.events.filter((e) => e.alert && e.severity !== 'info').slice(-ROW_EVENT_LIMIT).reverse()
    : null;
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
        li.title = `${fmtClockSeconds(event.ts)} — ${event.message}`;
        li.append(el('span', 'when', fmtClock(event.ts)), el('span', 'msg', event.message));
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
  if (st.status === 'nofile') infoRow(info, 'Uyarı', 'Teslim dosyası Teslimler klasöründe bulunamıyor');
  if (S.paths.recordings) {
    const sep = S.paths.recordings.includes('\\') ? '\\' : '/';
    infoRow(info, 'Kayıt klasörü', `${S.paths.recordings}${sep}${st.numara}`);
  }
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
  byNumara = new Map(S.students.map((st) => [st.numara, st]));
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
    receivedAt = Date.now();
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
    + 'Bu sınavın ekran kayıtları ve teslim dosyaları sınav klasöründe kalır; hiçbir şey silinmez. '
    + 'Yeni sınav için yeniden klasör seçersiniz. Öğrenci listesi korunur.';
  if (!confirm(question)) return;
  try {
    await api('/panel/api/reset');
    toast('Yeni sınav hazır.');
  } catch (error) {
    toast(error.message, true);
  }
}

/* Sınav klasörü: sunucu, bu bilgisayarda Windows'un klasör seçme penceresini açar. */
async function chooseFolder() {
  if (folderBusy) return;
  folderBusy = true;
  if (S) renderHeader();
  try {
    const data = await api('/panel/api/pick-folder');
    if (data.folder) toast(`Sınav klasörü seçildi: ${data.folder}`);
  } catch (error) {
    if (error.status === 501) openDialog('folderDialog', 'folderPath', S && S.exam.folder ? S.exam.folder : '');
    else toast(error.message, true);
  } finally {
    folderBusy = false;
    if (S) renderHeader();
  }
}

async function openExamFolder() {
  closeMenu();
  try {
    await api('/panel/api/open-folder');
  } catch (error) {
    toast(error.message, true);
  }
}

function openDialog(id, focusId, value) {
  closeMenu();
  $(id).hidden = false;
  const input = $(focusId);
  if (value !== undefined) input.value = value;
  input.focus();
  input.select();
}

function closeDialogs() {
  $('identityDialog').hidden = true;
  $('folderDialog').hidden = true;
  $('startDialog').hidden = true;
}

/* "Sınavı başlat" penceresi: başlangıç (hemen / saat), isteğe bağlı süre, ekran kaydı. */
function openStartDialog() {
  if (!S || !S.exam.file) return;
  closeMenu();
  setText($('startFileNote'),
    `Sınav dosyası (${S.exam.file.name}) sınav başladığı anda öğrencilerle paylaşılır; `
    + 'izin verilmeyen programlar kısa bir geri sayımdan sonra kapatılır.');
  // Öneri: beş dakikanın katı olan, en az beş dakika sonraki ilk saat.
  const suggestion = new Date(Math.ceil((Date.now() + 5 * 60000) / 300000) * 300000);
  $('startTime').value = `${String(suggestion.getHours()).padStart(2, '0')}:${String(suggestion.getMinutes()).padStart(2, '0')}`;
  $('startNow').checked = true;
  $('startDuration').value = '';
  $('startRecord').checked = pref('record', '1') === '1';
  syncStartDialog();
  $('startDialog').hidden = false;
  $('startDuration').focus();
}

function syncStartDialog() {
  const later = $('startLater').checked;
  $('startTime').disabled = !later;
  setText($('startSubmit'), later ? 'Planla' : 'Sınavı başlat');
}

async function submitStart(event) {
  event.preventDefault();
  const body = { record: $('startRecord').checked };
  const duration = $('startDuration').value.trim();
  if (duration !== '') body.duration_min = Number(duration);
  if ($('startLater').checked) {
    const [hours, minutes] = $('startTime').value.split(':').map(Number);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
      toast('Başlangıç saatini seçin ya da “Hemen”i işaretleyin.', true);
      return;
    }
    const at = new Date();
    at.setHours(hours, minutes, 0, 0);
    if (at.getTime() <= Date.now()) {
      toast('Seçtiğiniz saat geçmiş. İleri bir saat seçin ya da “Hemen”i işaretleyin.', true);
      return;
    }
    body.start_at = at.getTime() / 1000;
  }
  try {
    const data = await api('/panel/api/start', { json: body });
    setPref('record', body.record ? '1' : '0');
    closeDialogs();
    toast(data.scheduled ? `Sınav saat ${fmtClock(data.scheduled.at)} için planlandı.` : 'Sınav başladı.');
  } catch (error) {
    toast(error.message, true);
  }
}

function bindDialogs() {
  $('btnIdentity').addEventListener('click', () => {
    $('identityTeacher').value = S ? S.class.ogretmen_adi : '';
    openDialog('identityDialog', 'identityClass', S ? S.class.sinif_adi : '');
  });
  $('identityCancel').addEventListener('click', closeDialogs);
  $('identityForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/panel/api/identity', {
        json: { sinif_adi: $('identityClass').value, ogretmen_adi: $('identityTeacher').value },
      });
      closeDialogs();
      toast('Sınıf ve öğretmen adı güncellendi.');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('folderCancel').addEventListener('click', closeDialogs);
  $('folderForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/panel/api/exam-folder', { json: { path: $('folderPath').value } });
      closeDialogs();
      toast(`Sınav klasörü seçildi: ${data.folder}`);
    } catch (error) {
      toast(error.message, true);
    }
  });
  $('btnStart').addEventListener('click', openStartDialog);
  $('startCancel').addEventListener('click', closeDialogs);
  $('startNow').addEventListener('change', syncStartDialog);
  $('startLater').addEventListener('change', () => { syncStartDialog(); $('startTime').focus(); });
  $('startForm').addEventListener('submit', submitStart);
  $('btnCancelStart').addEventListener('click', async () => {
    try {
      await api('/panel/api/cancel-start');
      toast('Planlanan başlangıç iptal edildi.');
    } catch (error) {
      toast(error.message, true);
    }
  });
  $('btnExtend').addEventListener('click', async () => {
    closeMenu();
    try {
      const data = await api('/panel/api/extend', { json: { minutes: 5 } });
      toast(`5 dakika eklendi. Yeni bitiş: ${fmtClock(data.ends_at)}`);
    } catch (error) {
      toast(error.message, true);
    }
  });

  for (const id of ['identityDialog', 'folderDialog', 'startDialog']) {
    $(id).addEventListener('mousedown', (event) => { if (event.target === $(id)) closeDialogs(); });
  }
}

function bindControls() {
  bindDialogs();
  $('btnFolder').addEventListener('click', chooseFolder);
  $('btnOpenFolder').addEventListener('click', openExamFolder);
  $('btnOpenFolderTop').addEventListener('click', openExamFolder);
  $('ackAll').addEventListener('click', async () => {
    try { await api('/panel/api/ack', { json: {} }); } catch (error) { toast(error.message, true); }
  });
  $('btnExamFile').addEventListener('click', () => $('fileExam').click());
  $('fileExam').addEventListener('change', () => uploadFile(
    $('fileExam'), '/panel/api/exam-file', (file) => `Sınav dosyası yüklendi: ${file.name}`));

  const chooseRoster = () => { closeMenu(); $('fileRoster').click(); };
  $('btnRoster').addEventListener('click', chooseRoster);
  $('btnRosterMenu').addEventListener('click', chooseRoster);
  $('fileRoster').addEventListener('change', () => uploadFile(
    $('fileRoster'), '/panel/api/roster', (file, data) => `Öğrenci listesi yüklendi: ${data.count} öğrenci`));

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
    if (!$('identityDialog').hidden || !$('folderDialog').hidden || !$('startDialog').hidden) closeDialogs();
    else if (modalNumara) closeModal();
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

  $('sideCollapse').addEventListener('click', () => setSideCollapsed(true));
  $('sideRail').addEventListener('click', () => setSideCollapsed(false));
  sideCollapsed = pref('sideCollapsed', '0') === '1';
  $('side').classList.toggle('collapsed', sideCollapsed);
  $('side').addEventListener('transitionend', (event) => { if (event.propertyName === 'width') layoutGrid(); });

  // Ekran boyutu: − / kaydırıcı / + elle boyut verir, "Sığdır" otomatik boyuta döner.
  const size = $('tileSize');
  size.value = pref('tileSize', '260');
  fitTiles = pref('fit', '1') === '1';
  $('fit').setAttribute('aria-pressed', fitTiles ? 'true' : 'false');
  $('fit').addEventListener('click', () => setFit(!fitTiles));
  size.addEventListener('input', () => setTileSize(Number(size.value)));
  $('sizeDown').addEventListener('click', () => setTileSize(Number(size.value) - SIZE_STEP));
  $('sizeUp').addEventListener('click', () => setTileSize(Number(size.value) + SIZE_STEP));
  // Ctrl + fare tekerleği de ekranları büyütür / küçültür.
  $('gridWrap').addEventListener('wheel', (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setTileSize(Number(size.value) + (event.deltaY < 0 ? SIZE_STEP : -SIZE_STEP));
  }, { passive: false });
}

bindControls();
connectStream();
