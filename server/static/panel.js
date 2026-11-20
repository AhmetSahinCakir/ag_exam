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
  nosubmit: 'Teslim edilmedi',
  nofile: 'Dosya klasörde yok',
  absent: 'Giriş yapmadı',          // öğrenci listesinde var, henüz giriş yapmadı
};
const STATE_TEXT = { WAITING: 'Sınav başlamadı', RUNNING: 'Sınav sürüyor', ENDED: 'Sınav bitti' };
const ROSTER_TEXT = {
  no_roster: 'Liste yüklü değil',
  ok: 'Listede',
  name_mismatch: 'Listede, ad uyuşmuyor',
  not_in_list: 'Listede yok',
};
const ROW_EVENT_LIMIT = 6;
const SIZE_MIN = 140;
const SIZE_MAX = 900;
const SIZE_STEP = 40;

let S = null;                    // sunucudan gelen son durum
let lastAlertId = null;          // sesli uyarı için
let fitTiles = true;             // ekranları kaydırmadan sığdır
let sideCollapsed = false;       // sağdaki öğrenci listesi daraltıldı
let folderBusy = false;          // klasör seçme penceresi açık
let byNumara = new Map();        // numara -> öğrenci (son durum)
let receivedAt = 0;              // son durumun geldiği an (Date.now())
let systemClosed = false;        // "Sistemi kapat" istendi: sunucu duruyor
let modalNumara = null;
let modalEvSignature = '';       // büyük görünümdeki olay listelerinin son çizilen hâli
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
    throw new Error('Sunucuya ulaşılamadı. Sistem çalışıyor mu?');
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

/* Öğrencinin panelde nasıl yazılacağı Ayarlar'da seçilir: yalnızca ad soyad ('name'), yalnızca
   numara ('number') ya da ikisi ('both'). Dosya adlarında ve kayıtlarda numara her zaman vardır. */
function labelMode() {
  const mode = S && S.student_label;
  return mode === 'number' || mode === 'both' ? mode : 'name';
}

function studentLabel(st) {
  const mode = labelMode();
  if (mode === 'number') return st.numara;
  return mode === 'both' ? `${st.numara} ${fullName(st)}` : fullName(st);
}

/* Kutudaki ve satırdaki ad: numara kalın, ad soyad yanında (seçime göre biri gizlenir). */
function setWho(num, name, st) {
  const mode = labelMode();
  num.hidden = mode === 'name';
  name.hidden = mode === 'number';
  setText(num, st.numara);
  setText(name, fullName(st));
}

function byName(a, b) {
  return fullName(a).localeCompare(fullName(b), 'tr', { sensitivity: 'base' }) || a.numara.localeCompare(b.numara);
}

/* Yalnızca ad soyad gösterilirken sıra ada göredir; numara görünüyorsa numaraya göre (sunucudan
   gelen sıra). */
function inOrder(students) {
  return labelMode() === 'name' ? students.slice().sort(byName) : students.slice();
}

/* Sınav bittikten sonra teslim edenler "geç teslim" sayılır. */
function isLate(st) {
  return st.status === 'done' && Boolean(st.submission && st.submission.late);
}

function doneText(st) {
  return isLate(st) ? 'Geç teslim etti' : STATUS_TEXT.done;
}

function statusText(st) {
  if (st.status === 'lost') return st.lost_reason ? `Bağlantı yok — ${st.lost_reason}` : 'Bağlantı yok';
  if (st.status === 'nofile') return 'Teslim dosyası klasörde yok';
  if (st.status === 'done') return doneText(st);
  return STATUS_TEXT[st.status] || st.status;
}

function noVideoText(st) {
  if (st.status === 'absent') return STATUS_TEXT.absent;
  if (st.status === 'done') return doneText(st);
  if (st.status === 'nosubmit') return 'Teslim edilmedi';
  if (st.status === 'nofile') return 'Dosya klasörde yok';
  if (st.status === 'lost') return 'Bağlantı yok';
  return st.stream_ready ? 'Görüntü bağlanıyor…' : 'Ekran bekleniyor…';
}

/* Uyarı listesinde gösterilecek olaylar (en yeni üstte). */
function warningAlerts() {
  return S.alerts.filter((alert) => alert.severity !== 'info');
}

/* "Görüldü" denildikten sonra gelen uyarılar görülmemiş sayılır. */
function isUnseen(alert) {
  if (!alert.numara) return alert.id > (S.general_ack_id || 0);
  const st = byNumara.get(alert.numara);
  return alert.id > (st ? st.ack_id || 0 : 0);
}

/* Her öğrencinin en son görülmemiş uyarısı (S.alerts en yeni üstte gelir). Kopan bağlantı,
   sürdüğü sürece kırmızı durumla gösterilir; düzeldikten sonra satırda not olarak kalmaz. */
function latestAlerts() {
  const latest = new Map();
  for (const alert of warningAlerts()) {
    if (!alert.numara || latest.has(alert.numara) || alert.type === 'disconnected' || !isUnseen(alert)) continue;
    latest.set(alert.numara, alert);
  }
  return latest;
}

/* Belirli bir öğrenciye ait olmayan, görülmemiş uyarılar (ör. Teslimler klasöründe tanınmayan
   dosya). Sürenin dolduğu zaten üst satırda yazar. */
function generalAlerts() {
  return warningAlerts().filter((alert) => !alert.numara && alert.type !== 'time_up' && isUnseen(alert));
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
  const num = el('span', 'num');
  const name = el('span', 'name');
  who.append(num, name);
  cap.append(el('span', 'dot'), who);
  root.append(videoBox, cap);

  root.addEventListener('click', () => openModal(numara));
  const tile = {
    root, video, noVideo, flag, num, name,
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
  // Giriş yapanlar üstte durur; listede olup henüz giriş yapmayanlar onların ardından, teslim
  // edenler en sonda gelir (her grubun içinde ada ya da numaraya göre).
  const rank = (st) => (st.status === 'done' ? 2 : st.status === 'absent' ? 1 : 0);
  const ordered = inOrder(S.students).sort((a, b) => rank(a) - rank(b));
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
    setWho(tile.num, tile.name, st);
    tile.root.classList.toggle('late', isLate(st));
    tile.root.title = `${studentLabel(st)} — ${statusText(st)}`;
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
  $('side').parentElement.classList.toggle('side-collapsed', collapsed);
  setPref('sideCollapsed', collapsed ? '1' : '0');
  layoutGrid();
  setTimeout(layoutGrid, 220);      // genişlik geçişi bittikten sonra bir kez daha
}

/* Öğrenci listesinin genişliği: ekranlarla liste arasındaki tutamaç fareyle sürüklenir.
 * Seçilen genişlik hatırlanır; tutamaca çift tıklamak varsayılan genişliğe döner. */
const SIDE_MIN = 260;
function sideMax() {
  return Math.max(SIDE_MIN, Math.min(900, Math.round(window.innerWidth * 0.6)));
}
function setSideWidth(width, remember) {
  const side = $('side');
  if (!width) {
    side.style.removeProperty('--side-width');
    if (remember) setPref('sideWidth', '');
  } else {
    const clamped = Math.max(SIDE_MIN, Math.min(sideMax(), Math.round(width)));
    side.style.setProperty('--side-width', `${clamped}px`);
    if (remember) setPref('sideWidth', String(clamped));
  }
  layoutGrid();
}
function bindSideResize() {
  const handle = $('sideResize');
  let dragging = false;
  let frame = 0;
  let pending = 0;
  handle.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing');
    event.preventDefault();
  });
  handle.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    pending = window.innerWidth - event.clientX;      // liste sağ kenara yaslıdır
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; setSideWidth(pending, false); });
  });
  const finish = (event) => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('resizing');
    try { handle.releasePointerCapture(event.pointerId); } catch (_) { /* zaten bırakılmış */ }
    if (pending) setSideWidth(pending, true);
    pending = 0;
  };
  handle.addEventListener('pointerup', finish);
  handle.addEventListener('pointercancel', finish);
  handle.addEventListener('dblclick', () => setSideWidth(0, true));
  const saved = Number(pref('sideWidth', '0'));
  if (saved) setSideWidth(saved, false);
  // Pencere küçülürse liste ekranın yarısından fazlasını kaplamasın.
  window.addEventListener('resize', () => {
    const current = parseInt($('side').style.getPropertyValue('--side-width'), 10);
    if (current && current > sideMax()) setSideWidth(current, false);
  });
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

  const folder = S.exam.folder;
  $('setup').hidden = state !== 'WAITING';
  $('btnEnd').hidden = state !== 'RUNNING';
  // Sınav başladıktan sonra kayıt istenildiği an başlatılır ya da durdurulur: aynı yerde, o an
  // geçerli olan tek düğme görünür. Sınavı bitirmek kaydı durdurmaz: teslim etmeyen öğrenci,
  // teslim edene ya da "Kaydı durdur"a basılana kadar kaydedilir.
  const canRecord = state !== 'WAITING' && Boolean(folder);
  $('btnRecordStart').hidden = !(canRecord && !S.exam.record);
  $('btnRecordStop').hidden = !(canRecord && S.exam.record);
  $('btnResetTop').hidden = state !== 'ENDED';
  $('btnReset').disabled = state === 'RUNNING';
  // Sınav sürerken ad değiştirilemez: öğrenciler bu adla bağlandı.
  $('btnIdentity').hidden = state === 'RUNNING';

  $('btnOpenFolderTop').hidden = state !== 'ENDED' || !folder;
  $('btnOpenFolder').disabled = !folder;
  const folderInfo = $('folderInfo').firstElementChild;
  setText(folderInfo, folder || 'Kayıtlar, teslimler ve uyarılar buraya gelir');
  $('folderInfo').title = folder
    ? `${folder}\nİçinde “Kayıtlar” (ekran kayıtları), “Teslimler” (teslim edilen dosyalar) ve “Uyarılar” klasörleri açıldı.`
    : 'Seçtiğiniz klasörün içinde “Kayıtlar”, “Teslimler” ve “Uyarılar” klasörleri açılır.';
  $('btnFolder').parentElement.classList.toggle('done', Boolean(folder));
  $('btnFolder').disabled = folderBusy;
  setText($('btnFolder'), folderBusy ? 'Pencere açık…' : (folder ? 'Değiştir' : 'Klasör seç'));

  const file = S.exam.file;
  setText($('examFileInfo'), file ? file.name : 'Henüz seçilmedi');
  $('examFileInfo').title = file ? file.name : '';
  $('btnExamFile').parentElement.classList.toggle('done', Boolean(file));
  setText($('btnExamFile'), file ? 'Değiştir' : 'Dosya seç');
  // Liste dosyadan, elle eklenenlerden ya da ikisinden oluşabilir.
  const byHand = S.roster.manual || 0;
  let rosterInfo = 'Yüklenmedi';
  if (S.roster.name) rosterInfo = `${S.roster.count} öğrenci — ${S.roster.name}${byHand ? ` + ${byHand} elle` : ''}`;
  else if (S.roster.count) rosterInfo = `${S.roster.count} öğrenci — elle eklendi`;
  setText($('rosterInfo'), rosterInfo);
  $('btnRoster').parentElement.classList.toggle('done', S.roster.count > 0);
  setText($('btnRoster'), S.roster.name ? 'Değiştir' : 'Dosya seç');
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
  $('btnExtend').hidden = state !== 'RUNNING';

  renderMenuInfo();
  renderBanners();
  renderTimer();
}

function renderMenuInfo() {
  const lines = [];
  const ips = S.health.lan_ips;
  if (ips.length) {
    lines.push(`Ajan sunucuyu kendisi bulamazsa öğrenci şu adresi yazabilir: ${ips.join(' veya ')}`);
    if (S.health.agent_download) {
      lines.push(`Programı kurmamış öğrenci tarayıcısına şunu yazıp indirebilir: ${ips.map((ip) => `http://${ip}:${S.health.port}`).join(' veya ')}`);
    }
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
    messages.push('Ekran görüntüleri alınamıyor ve kayıt yapılmıyor. Birkaç saniye içinde düzelmezse '
      + 'bilgisayarı yeniden başlatıp sistemi yeniden açın; sınav kaldığı yerden sürer.');
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
  // Belirli bir öğrenciye ait olmayan uyarılar burada durur; "Görüldü" ile kalkar.
  const general = generalAlerts().slice(0, 3).reverse();
  const box = $('banners');
  const signature = JSON.stringify([messages, general.map((alert) => alert.id)]);
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  const nodes = messages.map((text) => el('div', 'banner', text));
  general.forEach((alert, index) => {
    const line = el('div', 'banner general');
    line.append(el('span', '', `${fmtClock(alert.ts)} — ${alert.message}`));
    if (index === general.length - 1) {
      const seen = el('button', '', 'Görüldü');
      seen.type = 'button';
      seen.addEventListener('click', async () => {
        try {
          await api('/panel/api/ack', { json: { general: true } });
        } catch (error) {
          toast(error.message, true);
        }
      });
      line.append(seen);
    }
    nodes.push(line);
  });
  box.replaceChildren(...nodes);
}

/* Üst satırdaki küçük başlıklı değerler: başlangıç, kalan süre, kayıt. */
function statItem(label, value, className) {
  const item = el('div', `stat${className ? ` ${className}` : ''}`);
  item.append(el('span', 'stat-label', label), el('span', 'stat-value', value));
  return item;
}

function renderTimer() {
  if (!S) return;
  const exam = S.exam;
  // Sunucunun saatine göre hesaplanır; tarayıcı saati yanlış olsa da doğru kalır.
  const serverNow = S.server_time + (Date.now() - receivedAt) / 1000;
  const stats = [];          // [başlık, değer, sınıf]
  if (exam.state === 'WAITING' && exam.scheduled) {
    stats.push(['Planlanan başlangıç', fmtClock(exam.scheduled.at), '']);
  } else if (exam.state === 'RUNNING' && exam.started_at) {
    stats.push(['Başlangıç', fmtClock(exam.started_at), 'secondary']);
    if (exam.ends_at) {
      const remaining = exam.ends_at - serverNow;
      if (remaining > 0) {
        stats.push(['Kalan süre', fmtRemaining(remaining), remaining <= 300 ? 'ending' : '']);
      } else {
        // Sınav kendiliğinden bitmez; süre dolduğu yalnızca burada görünür.
        stats.push(['Süre aşıldı', `+${fmtRemaining(-remaining)}`, 'over']);
      }
    } else {
      stats.push(['Geçen süre', fmtRemaining(Math.max(0, serverNow - exam.started_at)), '']);
    }
  } else if (exam.state === 'ENDED' && exam.started_at) {
    stats.push(['Başlangıç', fmtClock(exam.started_at), 'secondary']);
    stats.push(['Bitiş', fmtClock(exam.ended_at), '']);
  }
  if (exam.state !== 'WAITING') stats.push(['Kayıt', exam.record ? 'Açık' : 'Kapalı', exam.record ? 'rec' : 'rec off']);

  const box = $('examStats');
  const shape = stats.map((item) => `${item[0]}|${item[2]}`).join(',');
  if (box.dataset.shape !== shape) {
    // Yalnızca yapı değişince yeniden kurulur; saniyede iki kez değişen yalnızca değerdir.
    box.dataset.shape = shape;
    box.replaceChildren(...stats.map(([label, value, className]) => {
      const item = statItem(label, '', className);
      if (className.startsWith('rec')) item.lastChild.append(el('span', 'rec-dot'), el('span', 'rec-text', value));
      else setText(item.lastChild, value);
      return item;
    }));
  } else {
    stats.forEach(([, value, className], index) => {
      const node = box.children[index].lastChild;
      setText(className.startsWith('rec') ? node.lastChild : node, value);
    });
  }
}
setInterval(renderTimer, 500);

/* ----------------------------------------------------------------- öğrenci listesi (sağ) */

/* Durum sayıları: [sınıf, sayı, ad]. Sınav bittikten sonra kırmızı sayı "bağlantısı kopan"
   değil, "teslim etmeyen"dir. "Giriş yapmadı" yalnızca öğrenci listesi varken gösterilir. */
function summaryCells() {
  const sum = S.summary;
  const cells = [
    ['ok', sum.connected, 'Bağlı'],
    ['warn', sum.warned, 'Uyarılı'],
    ['lost', sum.lost, S.exam.state === 'ENDED' ? 'Teslim etmedi' : 'Kopuk'],
    ['done', sum.submitted, 'Teslim etti'],
  ];
  if (S.roster.count > 0) cells.push(['absent', sum.absent || 0, 'Giriş yapmadı']);
  return cells;
}

function summaryCell([className, count, label]) {
  const cell = el('div', `sum-cell ${className}${count ? '' : ' zero'}`);
  const number = el('span', 'sum-count');
  number.append(el('span', 'dot'), el('b', '', String(count)));
  cell.append(number, el('span', 'sum-label', label));
  cell.title = `${count} öğrenci: ${label.toLocaleLowerCase('tr')}`;
  return cell;
}

function railItem([className, count, label]) {
  const item = el('span', className);
  item.title = `${count} ${label.toLocaleLowerCase('tr')}`;
  item.append(el('span', 'dot'), document.createTextNode(String(count)));
  return item;
}

function renderSummary() {
  const cells = summaryCells();
  const signature = JSON.stringify(cells);
  const box = $('summary');
  if (box.dataset.signature !== signature) {
    box.dataset.signature = signature;
    box.style.setProperty('--cells', String(cells.length));
    box.replaceChildren(...cells.map(summaryCell));
    // Daraltılmış şerit: aynı sayılar alt alta.
    $('railSummary').replaceChildren(...cells.map(railItem));
  }
  // Toplam: giriş yapanlar ve listede olup henüz giriş yapmayanlar.
  setText($('countAll'), String(S.students.length));

  const unseenStudents = S.summary.warned;
  $('railAlerts').hidden = unseenStudents === 0;
  setText($('railAlerts'), unseenStudents > 99 ? '99+' : String(unseenStudents));
  $('railAlerts').title = `${unseenStudents} öğrencide görülmemiş uyarı`;
  $('ackBar').hidden = unseenStudents === 0;
  setText($('ackText'), `${unseenStudents} öğrencide görülmemiş uyarı var`);
}

function createRow(numara) {
  const root = el('li', 'row');
  root.dataset.numara = numara;

  // Tek satır: durum noktası, ad soyad, sağda (varsa) son uyarı ya da durum.
  const head = el('button', 'row-head');
  head.type = 'button';
  const who = el('span', 'who');
  const num = el('span', 'num');
  const name = el('span', 'name');
  who.append(num, name);
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
  // Yalnızca "listede yok" uyarısı alan öğrencide görünür.
  const enlist = el('button', '', 'Listeye ekle');
  enlist.type = 'button';
  // Yalnızca listede olup giriş yapmayan öğrencide görünür.
  const remove = el('button', 'danger-link', 'Listeden çıkar');
  remove.type = 'button';
  actions.append(zoom, ack, enlist, remove);
  body.append(events, meta, actions);
  root.append(head, body);

  head.addEventListener('click', () => toggleRow(numara));
  zoom.addEventListener('click', () => openModal(numara));
  ack.addEventListener('click', () => acknowledge(numara));
  enlist.addEventListener('click', () => {
    const st = byNumara.get(numara);
    if (st) openStudentDialog({ numara: st.numara, ad: st.ad, soyad: st.soyad });
  });
  remove.addEventListener('click', () => removeFromRoster(numara));

  return {
    root, head, num, name, note, count, body, events, meta, ack, zoom, enlist, remove,
    statusClass: '', metaSignature: '', eventSignature: '',
  };
}

/* "Görüldü": kaç uyarının işaretlendiği söylenir; listelerde o uyarılar soluklaşıp ✓ alır. */
async function acknowledge(numara) {
  try {
    const data = await api('/panel/api/ack', { json: numara ? { numara } : {} });
    toast(data.count > 0 ? `${data.count} uyarı görüldü olarak işaretlendi.` : 'Görülmemiş uyarı yoktu.');
  } catch (error) {
    toast(error.message, true);
  }
}

function toggleRow(numara) {
  if (expanded.has(numara)) expanded.delete(numara);
  else expanded.add(numara);
  renderList();
}

/* Satırın sağındaki tek satırlık not: görülmemiş son uyarı, yoksa durum. */
function rowNote(st, alert) {
  if (st.status === 'absent') return STATUS_TEXT.absent;
  if (st.status === 'lost' || st.status === 'nofile' || st.status === 'nosubmit') return statusText(st);
  if (alert) return alert.message;
  if (st.status === 'done') return doneText(st);
  return '';
}

function renderList() {
  renderSummary();
  renderStudentList();
}

function renderStudentList() {
  const latest = latestAlerts();
  const list = $('studentList');
  const seen = new Set();
  let previous = null;
  for (const st of inOrder(S.students)) {
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

function updateRow(row, st, alert) {
  const open = expanded.has(st.numara);
  const statusClass = `st-${st.status}`;
  if (row.statusClass !== statusClass) {
    if (row.statusClass) row.root.classList.remove(row.statusClass);
    row.root.classList.add(statusClass);
    row.statusClass = statusClass;
  }
  row.root.classList.toggle('open', open);
  row.root.classList.toggle('late', isLate(st));
  row.head.setAttribute('aria-expanded', open ? 'true' : 'false');
  setWho(row.num, row.name, st);
  const note = rowNote(st, alert);
  setText(row.note, note);
  row.head.title = note ? `${studentLabel(st)} — ${note}` : '';
  row.count.hidden = st.warn_count < 2;
  setText(row.count, String(st.warn_count));

  row.body.hidden = !open;
  if (!open) return;

  const absent = st.status === 'absent';
  row.zoom.hidden = absent;
  row.remove.hidden = !absent;
  row.enlist.hidden = st.roster !== 'not_in_list';
  if (absent) {
    // Giriş yapmayan öğrenci: gösterilecek olay ya da bilgisayar bilgisi yok.
    row.ack.hidden = true;
    const text = st.manual ? 'Elle eklendi; henüz giriş yapmadı.' : 'Henüz giriş yapmadı.';
    if (row.eventSignature !== `absent:${text}`) {
      row.eventSignature = `absent:${text}`;
      row.events.replaceChildren(el('li', 'none', text));
    }
    if (row.metaSignature !== '') {
      row.metaSignature = '';
      row.meta.replaceChildren();
    }
    return;
  }

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
  const ackId = st.ack_id || 0;
  const eventSignature = events ? `${events.map((e) => e.id).join(',')}|${ackId}` : 'loading';
  if (row.eventSignature !== eventSignature) {
    row.eventSignature = eventSignature;
    if (!events) {
      row.events.replaceChildren(el('li', 'none', 'Yükleniyor…'));
    } else if (events.length === 0) {
      row.events.replaceChildren(el('li', 'none', 'Bu öğrenci için uyarı yok.'));
    } else {
      row.events.replaceChildren(...events.map((event) => {
        const seen = event.id <= ackId;
        const li = el('li', seen ? 'seen' : '');
        li.title = `${fmtClockSeconds(event.ts)} — ${event.message}${seen ? ' (görüldü)' : ''}`;
        li.append(el('span', 'when', fmtClock(event.ts)), el('span', 'msg', event.message));
        if (seen) li.append(el('span', 'seen-mark', '✓'));
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
  const absent = byNumara.get(numara);
  if (absent && absent.status === 'absent') return;       // giriş yapmayanın ekranı ve bilgisi yok
  modalNumara = numara;
  modalEvSignature = '';
  $('modalEvents').replaceChildren();
  $('modalLog').replaceChildren();
  $('modalLogDetails').open = false;
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

  setText($('modalTitle'), labelMode() === 'both' ? `${st.numara} — ${fullName(st)}` : studentLabel(st));
  const status = $('modalStatus');
  status.className = `modal-status st-${st.status}`;
  const statusSignature = `${statusText(st)}|${st.roster}`;
  if (status.dataset.signature !== statusSignature) {
    status.dataset.signature = statusSignature;
    status.replaceChildren(el('span', 'dot'), document.createTextNode(statusText(st)));
    if (st.roster === 'not_in_list') {
      // Listede olmayan öğrenci buradan tek tıkla listeye alınır.
      const enlist = el('button', 'link small', 'Listeye ekle');
      enlist.type = 'button';
      enlist.addEventListener('click', () => openStudentDialog({ numara: st.numara, ad: st.ad, soyad: st.soyad }));
      status.append(enlist);
    }
  }

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
  infoRow(info, 'Öğrenci numarası', st.numara);
  infoRow(info, 'Ad soyad', fullName(st));
  infoRow(info, 'IP adresi', st.ip);
  infoRow(info, 'Bilgisayar adı', st.hostname);
  infoRow(info, 'Ağ (MAC) adresi', st.mac);
  infoRow(info, 'Öğrenci listesi', ROSTER_TEXT[st.roster] || st.roster);
  infoRow(info, 'Giriş saati', fmtClockSeconds(st.login_ts) + (st.login_count > 1 ? ` (${st.login_count}. giriş)` : ''));
  infoRow(info, 'Açık pencere', st.fg_process ? `${st.fg_process}${st.fg_title ? ` — ${st.fg_title}` : ''}` : '');
  if (st.monitors > 1) infoRow(info, 'Monitör sayısı', st.monitors);
  if (st.submission) {
    const sub = st.submission;
    infoRow(info, 'Teslim', `${sub.filename}${sub.late ? ' (geç teslim)' : ''}, ${fmtClockSeconds(sub.ts)}`);
    infoRow(info, 'Dosya özeti', sub.sha256);
  }
  if (st.status === 'nofile') infoRow(info, 'Uyarı', 'Teslim dosyası Teslimler klasöründe bulunamıyor');
  if (S.paths.recordings) {
    const sep = S.paths.recordings.includes('\\') ? '\\' : '/';
    infoRow(info, 'Kayıt klasörü', `${S.paths.recordings}${sep}${st.record_folder || st.numara}`);
  }
  $('modalInfo').replaceChildren(info);

  const cached = eventCache.get(st.numara);
  if (!cached || cached.count !== st.ev_count) loadEvents(st.numara, st.ev_count);
  // Üstte yalnızca uyarılar (renkli olanlar); giriş, pencere geçişi gibi öteki kayıtlar
  // "Diğer kayıtlar" başlığı altında, kapalı durur.
  const ackId = st.ack_id || 0;
  const isWarning = (event) => event.alert && event.severity !== 'info';
  const warnings = cached ? cached.events.filter(isWarning) : [];
  const ack = $('modalAck');
  ack.hidden = warnings.length === 0;
  ack.disabled = st.warn_count === 0;
  ack.classList.toggle('done', st.warn_count === 0);
  setText(ack, st.warn_count === 0 ? '✓ Hepsi görüldü' : `Uyarıları görüldü yap (${st.warn_count})`);

  const signature = cached ? `${cached.events.length}|${ackId}` : '';
  if (cached && modalEvSignature !== signature) {
    modalEvSignature = signature;
    const item = (event, minor) => {
      const seen = !minor && event.id <= ackId;
      const li = el('li', minor ? 'minor' : `sev-${event.severity}${seen ? ' seen' : ''}`);
      li.append(el('span', 'when', fmtClockSeconds(event.ts)), document.createTextNode(event.message));
      if (seen) li.append(el('span', 'seen-mark', '✓ görüldü'));
      return li;
    };
    const others = cached.events.filter((event) => !isWarning(event));
    $('modalEvents').replaceChildren(...(warnings.length
      ? warnings.slice().reverse().map((event) => item(event, false))
      : [el('li', 'none', 'Bu öğrenci için uyarı yok.')]));
    $('modalLog').replaceChildren(...others.slice().reverse().map((event) => item(event, true)));
    setText($('modalLogCount'), others.length ? `(${others.length})` : '');
    $('modalLogDetails').hidden = others.length === 0;
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
    askIdentityOnce();
  };
  // Sunucu "Sistemi kapat" ile duruyor (bu pencereden ya da masaüstündeki sorudan).
  source.addEventListener('closed', () => { systemClosed = true; });
  source.onerror = () => {
    const box = $('banners');
    const old = box.querySelector('.server-down');
    if (systemClosed) {
      // "Sistemi kapat" istendi: yeniden bağlanmayı deneme.
      source.close();
      if (old) old.remove();
      box.prepend(el('div', 'banner server-down closed',
        'Sistem kapatıldı. Bu pencereyi kapatabilirsiniz. Yeniden açmak için masaüstündeki Sınav İzleme Sistemi simgesine çift tıklayın.'));
      return;
    }
    // EventSource kendiliğinden yeniden bağlanır; bu arada durumu göster.
    if (!old) {
      box.prepend(el('div', 'banner server-down',
        'Sunucuyla bağlantı kesildi. Yeniden bağlanılıyor… Sistem kapandıysa masaüstündeki simgeden yeniden açın.'));
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

/* Programı hâlâ açık olan, teslim etmemiş öğrenciler. */
function openStudents() {
  return S.students.filter((st) => st.status !== 'done' && st.status !== 'nofile' && st.status !== 'absent'
    && st.last_seen_s < 10);
}

async function resetExam() {
  closeMenu();
  const open = S ? openStudents().length : 0;
  let question = 'Yeni sınav hazırlansın mı?\n\n'
    + 'Bu sınavın ekran kayıtları, teslim dosyaları ve uyarıları sınav klasöründe kalır; hiçbir şey '
    + 'silinmez. Yeni sınav için yeniden klasör seçersiniz. Öğrenci listesi korunur.';
  if (open > 0) {
    question += `\n\nDİKKAT: ${open} öğrenci teslim etmedi ve programı hâlâ açık. Yeni sınav hazırlarsanız `
      + 'programları kapanır ve dosyaları ALINMAZ. Önce teslim etmelerini bekleyin.';
  }
  if (!confirm(question)) return;
  if (open > 0) toast('Öğrenci programları kapatılıyor…');
  try {
    await api('/panel/api/reset');
    toast('Yeni sınav hazır.');
  } catch (error) {
    toast(error.message, true);
  }
}

/* "Sınavı bitir" penceresi: ek süre ver ya da sınavı bitir. */
function openEndDialog() {
  if (!S || S.exam.state !== 'RUNNING') return;
  closeMenu();
  const present = S.students.filter((st) => st.status !== 'absent');
  const total = present.length;
  const waiting = present.filter((st) => st.status !== 'done').length;
  let summary = waiting === 0
    ? (total ? 'Giriş yapan bütün öğrenciler teslim etti.' : 'Giriş yapan öğrenci yok.')
    : `Henüz teslim etmeyen öğrenci: ${waiting} (giriş yapan ${total}).`;
  if (S.summary.absent > 0) summary += ` Listede olup giriş yapmayan: ${S.summary.absent}.`;
  setText($('endSummary'), summary);
  let hint = 'Öğrenciler yazdığınız süreyi geri sayım olarak görür. Süre dolunca sınav kendiliğinden bitmez.';
  if (S.exam.ends_at) {
    const serverNow = S.server_time + (Date.now() - receivedAt) / 1000;
    const remaining = S.exam.ends_at - serverNow;
    hint = remaining > 0
      ? `Şu an kalan süre ${fmtRemaining(remaining)}; yazdığınız süre buna eklenir.`
      : 'Süre aşıldı; öğrenciler yazdığınız süreyi şu andan başlayan yeni bir geri sayım olarak görür.';
  }
  setText($('extendHint'), hint);
  $('extendMinutes').value = '5';
  $('endDialog').hidden = false;
  $('endCancel').focus();
}

async function extendExam() {
  const minutes = Number($('extendMinutes').value);
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 120) {
    toast('Ek süre 1 ile 120 dakika arasında bir sayı olmalı.', true);
    return;
  }
  try {
    const data = await api('/panel/api/extend', { json: { minutes } });
    closeDialogs();
    toast(`${minutes} dakika ek süre verildi. Süre ${fmtClock(data.ends_at)} saatinde doluyor.`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function endExam() {
  try {
    await api('/panel/api/end');
    closeDialogs();
    toast('Sınav bitirildi. Teslim etmeyen öğrenciler dosyalarını geç teslim olarak verebilir.');
  } catch (error) {
    toast(error.message, true);
  }
}

/* "Sistemi kapat": sunucu durur, öğrenci programları kapanır. */
function openShutdownDialog() {
  closeMenu();
  let note = 'Sunucu ve ekran kaydı durur, öğrenci programları kapanır. Kayıtlar, teslimler ve uyarılar '
    + 'sınav klasöründe kalır.';
  const open = S ? openStudents().length : 0;
  if (open > 0) {
    note += ` DİKKAT: ${open} öğrenci teslim etmedi ve programı hâlâ açık; sistemi kapatırsanız dosyaları `
      + 'alınmaz.';
  }
  if (S && S.exam.state === 'RUNNING') note = `Sınav sürüyor: sistemi kapatırsanız sınav biter. ${note}`;
  setText($('shutdownNote'), note);
  $('shutdownDialog').hidden = false;
  $('shutdownCancel').focus();
}

async function shutdownSystem() {
  try {
    systemClosed = true;
    await api('/panel/api/shutdown');
    closeDialogs();
    toast('Sistem kapatılıyor…');
  } catch (error) {
    systemClosed = false;
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

/* ----------------------------------------------------------------- öğrenci listesi penceresi */

/* Dosyanın nasıl olması gerektiğini gösterir; dosya buradan seçilir. */
function openRosterDialog() {
  closeMenu();
  let current = '';
  if (S && S.roster.name) {
    current = `Şu an yüklü: ${S.roster.name} (${S.roster.count} öğrenci). Yeni dosya seçerseniz liste onunla `
      + 'değişir; elle eklediğiniz öğrenciler korunur.';
  }
  setText($('rosterCurrent'), current);
  $('rosterCurrent').hidden = !current;
  setText($('rosterChoose'), S && S.roster.name ? 'Başka dosya seç' : 'Dosya seç');
  $('rosterDialog').hidden = false;
  $('rosterChoose').focus();
}

async function uploadRoster() {
  const input = $('fileRoster');
  const file = input.files[0];
  input.value = '';
  if (!file) return;
  const form = new FormData();
  form.append('file', file, file.name);
  try {
    const data = await api('/panel/api/roster', { body: form });
    closeDialogs();
    toast(`Öğrenci listesi yüklendi: ${data.count} öğrenci`);
  } catch (error) {
    toast(error.message, true);       // pencere açık kalır: biçim orada yazıyor
  }
}

/* ----------------------------------------------------------------- kaydı sonradan başlatma */

function openRecordDialog() {
  if (!S || S.exam.state === 'WAITING' || S.exam.record) return;
  closeMenu();
  $('recordDialog').hidden = false;
  $('recordCancel').focus();
}

function openRecordStopDialog() {
  if (!S || S.exam.state === 'WAITING' || !S.exam.record) return;
  closeMenu();
  $('recordStopDialog').hidden = false;
  $('recordStopCancel').focus();
}

async function stopRecording() {
  try {
    await api('/panel/api/record/stop');
    closeDialogs();
    toast('Ekran kaydı durduruldu. Canlı izleme sürüyor.');
  } catch (error) {
    toast(error.message, true);
  }
}

async function startRecording() {
  try {
    await api('/panel/api/record/start');
    closeDialogs();
    toast('Ekran kaydı başlatıldı. Bu andan sonrası kaydediliyor.');
  } catch (error) {
    toast(error.message, true);
  }
}

/* ----------------------------------------------------------------- elle öğrenci ekleme */

/* prefill: "listede yok" uyarısı alan öğrencinin girişte yazdıkları (tek tıkla eklemek için). */
function openStudentDialog(prefill) {
  closeMenu();
  $('studentNumara').value = prefill ? prefill.numara : '';
  $('studentAd').value = prefill ? prefill.ad : '';
  $('studentSoyad').value = prefill ? prefill.soyad : '';
  $('studentDialog').hidden = false;
  (prefill ? $('studentAd') : $('studentNumara')).focus();
}

async function submitStudent(event) {
  event.preventDefault();
  try {
    const added = await api('/panel/api/roster/add', {
      json: { numara: $('studentNumara').value, ad: $('studentAd').value, soyad: $('studentSoyad').value },
    });
    closeDialogs();
    toast(`${added.ad} ${added.soyad} listeye eklendi.`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function removeFromRoster(numara) {
  const st = byNumara.get(numara);
  const who = st ? studentLabel(st) : numara;
  if (!confirm(`${who} listeden çıkarılsın mı?`)) return;
  try {
    await api('/panel/api/roster/remove', { json: { numara } });
    expanded.delete(numara);
    toast(`${who} listeden çıkarıldı.`);
  } catch (error) {
    toast(error.message, true);
  }
}

/* ----------------------------------------------------------------- ayarlar penceresi */

let settingsInfo = null;          // sunucudan gelen: values, defaults, limits
let settingsPrograms = [];        // penceredeki "izin verilen programlar" listesi
let appCatalog = null;            // "Program ekle" listesi: { catalog, installed, scanning }
let appPoll = 0;

/* Adı bilinen programın dosya adından adına ("chrome.exe" -> "Google Chrome"). */
function programTitle(exe) {
  if (!appCatalog) return '';
  const key = exe.toLowerCase();
  for (const app of appCatalog.catalog) {
    if (app.exe.some((name) => name.toLowerCase() === key)) return app.name;
  }
  const found = appCatalog.installed.find((app) => app.exe.toLowerCase() === key);
  return found ? found.name : '';
}

function hasProgram(exe) {
  return settingsPrograms.some((other) => other.toLowerCase() === exe.toLowerCase());
}

function renderSettingsPrograms() {
  const fixed = el('li', 'fixed');
  fixed.append(el('span', '', 'Packet Tracer'));
  fixed.title = 'Her zaman izinlidir';
  // Bir program birden çok dosya adıyla biliniyorsa (ör. Hesap Makinesi) tek etiket olarak görünür.
  const groups = new Map();
  for (const name of settingsPrograms) {
    const title = programTitle(name) || name;
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(name);
  }
  const items = Array.from(groups, ([title, names]) => {
    const item = el('li');
    item.title = names.join(', ') === title ? title : `${title} (${names.join(', ')})`;
    const remove = el('button', '', '×');
    remove.type = 'button';
    remove.title = `${title} iznini kaldır`;
    remove.setAttribute('aria-label', remove.title);
    remove.addEventListener('click', () => {
      settingsPrograms = settingsPrograms.filter((other) => !names.includes(other));
      renderSettingsPrograms();
      renderProgramList();
    });
    item.append(el('span', '', title), remove);
    return item;
  });
  $('settingsPrograms').replaceChildren(fixed, ...items);
}

/* "putty" -> "putty.exe"; aynı program iki kez eklenmez. Kurallara uymayanı sunucu geri çevirir. */
function addSettingsProgram(text) {
  let name = String(text || '').trim().replace(/^["']+|["']+$/g, '');
  if (!name) return;
  if (!/[\\/:%]/.test(name) && !name.includes('.')) name += '.exe';
  if (!hasProgram(name)) settingsPrograms.push(name);
  renderSettingsPrograms();
  renderProgramList();
}

/* ---- "Program ekle": aşağı doğru açılan panel (arama + hazır liste + bu bilgisayardaki programlar) */

/* Programın kendi simgesi bilinmiyorsa türüne göre sade bir çizim gösterilir. */
const APP_GLYPHS = {
  browser: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
  code: '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12.5 15H17"/>',
  office: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
  network: '<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="18" r="2.2"/><path d="M11 7l-5 9M13 7l5 9M7.2 18h9.6"/>',
  text: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  tool: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h2M12 11h1M15 11h1M8 14.5h2M12 14.5h1M15 14.5h1M8 18h2M12 18h4"/>',
  app: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
};

function appIcon(app) {
  const box = el('span', 'app-icon');
  if (app.icon) {
    const image = document.createElement('img');
    image.alt = '';
    image.src = app.icon;          // sunucunun bu bilgisayardan okuduğu simge (data: adresi)
    box.classList.add('real');
    box.append(image);
    return box;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.6');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.innerHTML = APP_GLYPHS[app.kind] || APP_GLYPHS.app;   // sabit çizimler; dışarıdan metin içermez
  box.append(svg);
  return box;
}

function foldText(text) {
  return String(text).toLocaleLowerCase('tr').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i');
}

function appRow(app) {
  const exes = Array.isArray(app.exe) ? app.exe : [app.exe];
  const row = el('li', 'app');
  const text = el('span', 'app-text');
  text.append(el('span', 'app-name', app.name), el('span', 'app-exe', app.note || exes.join(', ')));
  const added = exes.every(hasProgram);
  const add = el('button', '', added ? 'Eklendi ✓' : 'Ekle');
  add.type = 'button';
  add.disabled = added;
  add.setAttribute('aria-label', `${app.name}: ${added ? 'eklendi' : 'ekle'}`);
  add.addEventListener('click', () => {
    for (const exe of exes) if (!hasProgram(exe)) settingsPrograms.push(exe);
    renderSettingsPrograms();
    renderProgramList();
  });
  row.title = `${app.name} (${exes.join(', ')})`;
  row.append(appIcon(app), text, add);
  return row;
}

function renderProgramList() {
  if ($('programPicker').hidden) return;
  const list = $('programList');
  if (!appCatalog) {
    list.replaceChildren(el('li', 'none', 'Yükleniyor…'));
    return;
  }
  const query = foldText($('programSearch').value.trim());
  const match = (app) => !query || foldText(app.name).includes(query)
    || (Array.isArray(app.exe) ? app.exe : [app.exe]).some((exe) => foldText(exe).includes(query));
  const common = appCatalog.catalog.filter(match);
  const installed = appCatalog.installed.filter(match);
  const nodes = [];
  if (common.length) nodes.push(el('li', 'head', 'Sık kullanılanlar'), ...common.map(appRow));
  if (installed.length) nodes.push(el('li', 'head', 'Bu bilgisayardaki programlar'), ...installed.map(appRow));
  // Listede olmayan bir program, dosya adı yazılarak eklenir.
  const typed = $('programSearch').value.trim().replace(/^["']+|["']+$/g, '');
  if (typed && !/[\\/:*?"<>|%\s]/.test(typed)) {
    const exe = typed.includes('.') ? typed : `${typed}.exe`;
    const known = [...common, ...installed].some((app) => (Array.isArray(app.exe) ? app.exe : [app.exe])
      .some((name) => name.toLowerCase() === exe.toLowerCase()));
    // Aramaya uyan program varken yalnızca tam dosya adı (….exe) yazıldıysa önerilir.
    if (!known && /\.exe$/i.test(exe) && (!nodes.length || /\.exe$/i.test(typed))) {
      nodes.push(el('li', 'head', 'Dosya adıyla ekle'),
        appRow({ name: exe, exe: [exe], kind: 'app', icon: '', note: 'Listede yok; bu dosya adıyla eklenir' }));
    }
  }
  if (!nodes.length) nodes.push(el('li', 'none', 'Bu adla bir program bulunamadı. Dosya adını yazın (ör. putty.exe).'));
  list.replaceChildren(...nodes);
  setText($('programScan'), appCatalog.scanning ? 'Bu bilgisayardaki programlar aranıyor…' : '');
}

/* Liste sunucudan bir kez alınır; bu bilgisayardaki programlar okunana kadar yeniden sorulur. */
async function loadApps() {
  clearTimeout(appPoll);
  try {
    appCatalog = await api('/panel/api/apps', { method: 'GET' });
  } catch (_) {
    if (!appCatalog) appCatalog = { catalog: [], installed: [], scanning: false };
  }
  renderSettingsPrograms();
  renderProgramList();
  if (appCatalog.scanning && !$('settingsDialog').hidden) appPoll = setTimeout(loadApps, 1500);
}

function setProgramPicker(open) {
  $('programPicker').hidden = !open;
  $('programPickerToggle').setAttribute('aria-expanded', open ? 'true' : 'false');
  setText($('programPickerToggle'), open ? 'Listeyi kapat' : '+ Program ekle');
  if (!open) return;
  $('programSearch').value = '';
  renderProgramList();
  $('programSearch').focus();
  $('programPicker').scrollIntoView({ block: 'nearest' });
}

function fillSettings(values) {
  settingsPrograms = values.programs.slice();
  renderSettingsPrograms();
  renderProgramList();
  for (const radio of document.getElementsByName('settingsQuality')) radio.checked = radio.value === values.quality;
  for (const radio of document.getElementsByName('settingsLabel')) radio.checked = radio.value === values.student_label;
  $('setForeground').value = values.foreground_tolerance_s;
  $('setKill').value = values.kill_countdown_s;
  $('setDisconnect').value = values.disconnect_s;
  $('setCloseWait').value = values.close_wait_min;
  $('setNote').value = values.retention_note;
}

async function openSettings() {
  closeMenu();
  try {
    settingsInfo = await api('/panel/api/settings', { method: 'GET' });
  } catch (error) {
    toast(error.message, true);
    return;
  }
  const limits = settingsInfo.limits;
  for (const [id, key] of [['setForeground', 'foreground_tolerance_s'], ['setKill', 'kill_countdown_s'],
    ['setDisconnect', 'disconnect_s'], ['setCloseWait', 'close_wait_min']]) {
    $(id).min = limits[key].min;
    $(id).max = limits[key].max;
  }
  $('setNote').maxLength = settingsInfo.max_note;
  $('settingsDialog').hidden = false;
  setProgramPicker(false);
  fillSettings(settingsInfo.values);
  $('settingsCancel').focus();
  loadApps();
}

async function saveSettings(event) {
  event.preventDefault();
  const checked = (name, fallback) => {
    const radio = Array.from(document.getElementsByName(name)).find((item) => item.checked);
    return radio ? radio.value : fallback;
  };
  try {
    await api('/panel/api/settings', {
      json: {
        programs: settingsPrograms,
        quality: checked('settingsQuality', 'normal'),
        student_label: checked('settingsLabel', 'name'),
        foreground_tolerance_s: $('setForeground').value,
        kill_countdown_s: $('setKill').value,
        disconnect_s: $('setDisconnect').value,
        close_wait_min: $('setCloseWait').value,
        retention_note: $('setNote').value,
      },
    });
    closeDialogs();
    toast('Ayarlar kaydedildi.');
  } catch (error) {
    toast(error.message, true);
  }
}

function bindSettings() {
  $('btnSettings').addEventListener('click', openSettings);
  $('settingsCancel').addEventListener('click', closeDialogs);
  $('settingsForm').addEventListener('submit', saveSettings);
  $('settingsDefaults').addEventListener('click', () => { if (settingsInfo) fillSettings(settingsInfo.defaults); });
  $('programPickerToggle').addEventListener('click', () => setProgramPicker($('programPicker').hidden));
  $('programSearch').addEventListener('input', renderProgramList);
  // Enter, formu kaydetmek yerine listedeki ilk programı ekler.
  $('programSearch').addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const first = $('programList').querySelector('li.app button:not(:disabled)');
    if (first) first.click();
  });
  // Dosya yüklenmez: tarayıcıdan yalnızca seçilen programın adı alınır.
  $('settingsProgramPick').addEventListener('click', () => $('settingsProgramFile').click());
  $('settingsProgramFile').addEventListener('change', () => {
    const file = $('settingsProgramFile').files[0];
    if (file) addSettingsProgram(file.name);
    $('settingsProgramFile').value = '';
  });
}

function openDialog(id, focusId, value) {
  closeMenu();
  $(id).hidden = false;
  const input = $(focusId);
  if (value !== undefined) input.value = value;
  input.focus();
  input.select();
}

const DIALOGS = ['identityDialog', 'folderDialog', 'startDialog', 'endDialog', 'shutdownDialog', 'settingsDialog',
  'studentDialog', 'rosterDialog', 'recordDialog', 'recordStopDialog'];

function closeDialogs() {
  for (const id of DIALOGS) $(id).hidden = true;
}

/* "Sınavı başlat" penceresi: başlangıç (hemen / saat), isteğe bağlı süre, ekran kaydı. */
function openStartDialog() {
  if (!S || !S.exam.file) return;
  closeMenu();
  setText($('startFileNote'),
    'Sınav başladığında öğrenci panelinde “Sınav dosyasını indir” düğmesi çıkar; her öğrenci dosyayı '
    + `(${S.exam.file.name}) istediği yere kendisi indirir. İzin verilmeyen programlar kısa bir geri `
    + 'sayımdan sonra kapatılır.');
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

// İlk açılış: sınıf adı ve ad soyad hiç yazılmamışsa (örnek adlar duruyorsa) bir kez sor.
let identityAsked = false;
function askIdentityOnce() {
  if (identityAsked || !S || S.class.saved || S.exam.state !== 'WAITING') return;
  identityAsked = true;
  if (DIALOGS.some((id) => !$(id).hidden)) return;
  $('identityTeacher').value = '';
  openDialog('identityDialog', 'identityClass', '');
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
      toast('Sınıf bilgileri güncellendi.');
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
  $('btnEnd').addEventListener('click', openEndDialog);
  $('btnExtend').addEventListener('click', openEndDialog);
  $('endCancel').addEventListener('click', closeDialogs);
  $('btnExtendGo').addEventListener('click', extendExam);
  $('btnEndGo').addEventListener('click', endExam);
  $('btnShutdown').addEventListener('click', openShutdownDialog);
  $('shutdownCancel').addEventListener('click', closeDialogs);
  $('btnShutdownGo').addEventListener('click', shutdownSystem);

  for (const id of DIALOGS) {
    $(id).addEventListener('mousedown', (event) => { if (event.target === $(id)) closeDialogs(); });
  }
}

function bindControls() {
  bindDialogs();
  $('btnFolder').addEventListener('click', chooseFolder);
  $('btnOpenFolder').addEventListener('click', openExamFolder);
  bindSettings();
  $('btnAddStudent').addEventListener('click', () => openStudentDialog(null));
  $('btnAddStudentMenu').addEventListener('click', () => openStudentDialog(null));
  $('studentCancel').addEventListener('click', closeDialogs);
  $('studentForm').addEventListener('submit', submitStudent);
  $('btnOpenFolderTop').addEventListener('click', openExamFolder);
  $('ackAll').addEventListener('click', () => acknowledge(null));
  $('btnExamFile').addEventListener('click', () => $('fileExam').click());
  $('fileExam').addEventListener('change', () => uploadFile(
    $('fileExam'), '/panel/api/exam-file', (file) => `Sınav dosyası yüklendi: ${file.name}`));

  $('btnRoster').addEventListener('click', openRosterDialog);
  $('btnRosterMenu').addEventListener('click', openRosterDialog);
  $('rosterChoose').addEventListener('click', () => $('fileRoster').click());
  $('rosterCancel').addEventListener('click', closeDialogs);
  $('fileRoster').addEventListener('change', uploadRoster);
  $('btnRecordStart').addEventListener('click', openRecordDialog);
  $('recordCancel').addEventListener('click', closeDialogs);
  $('recordGo').addEventListener('click', startRecording);
  $('btnRecordStop').addEventListener('click', openRecordStopDialog);
  $('recordStopCancel').addEventListener('click', closeDialogs);
  $('recordStopGo').addEventListener('click', stopRecording);

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


  $('modalAck').addEventListener('click', () => { if (modalNumara) acknowledge(modalNumara); });
  $('modalClose').addEventListener('click', closeModal);
  $('modal').addEventListener('click', (event) => { if (event.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (DIALOGS.some((id) => !$(id).hidden)) closeDialogs();
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
  $('side').parentElement.classList.toggle('side-collapsed', sideCollapsed);
  bindSideResize();
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
