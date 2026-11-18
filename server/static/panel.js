/* Sınav İzleme Paneli. Harici kaynak kullanılmaz; her şey bu sunucudan ve yerel MediaMTX'ten gelir.
 * Öğrenciden gelen tüm metinler (ad, bilgisayar adı, pencere başlığı…) yalnızca textContent ile
 * yazılır; hiçbir zaman HTML olarak yorumlanmaz. */
'use strict';

const $ = (id) => document.getElementById(id);

const STATUS_LABEL = {
  ok: 'Normal',
  warn: 'Uyarı',
  lost: 'Bağlantı yok',
  done: 'Teslim etti',
  nosubmit: 'Teslim yok',
};
const STATE_LABEL = { WAITING: 'BEKLİYOR', RUNNING: 'SINAV SÜRÜYOR', ENDED: 'SINAV BİTTİ' };
const ROSTER_LABEL = {
  no_roster: 'Liste yüklü değil',
  ok: 'Listede, ad uyuşuyor',
  name_mismatch: 'Listede, AD UYUŞMUYOR',
  not_in_list: 'LİSTEDE YOK',
};

let S = null;               // son durum (sunucudan)
let clockOffset = 0;        // sunucu saati - yerel saat (sn)
let lastAlertId = null;     // sesli bildirim için
let alertSignature = '';
let modalNumara = null;
let modalEvCount = -1;
const tiles = new Map();    // numara -> { root, parçalar, player, visible }

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
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour12: false });
}

function fmtDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function fmtBytes(n) {
  if (n < 1024) return `${n} bayt`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
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
    throw new Error('Sunucuya ulaşılamadı. Sunucu penceresi açık mı?');
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

/* ----------------------------------------------------------------- öğrenci kutuları */

function createTile(numara) {
  const root = el('div', 'tile');
  root.dataset.numara = numara;
  const videoBox = el('div', 'video');
  const video = document.createElement('video');
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  const noVideo = el('div', 'novideo', 'Görüntü yok');
  videoBox.append(video, noVideo);

  const meta = el('div', 'meta');
  const row1 = el('div', 'row1');
  const num = el('span', 'num', numara);
  const warn = el('span', 'warncount');
  warn.hidden = true;
  const badge = el('span', 'badge');
  row1.append(num, warn, badge);
  const name = el('div', 'name');
  const net = el('div', 'net');
  const fg = el('div', 'fg');
  meta.append(row1, name, net, fg);
  root.append(videoBox, meta);

  root.addEventListener('click', () => openModal(numara));
  const tile = {
    root, video, noVideo, warn, badge, name, net, fg,
    player: new Player(numara, video, videoBox),
    visible: true,
    data: null,
    statusClass: '',
  };
  visibility.observe(root);
  return tile;
}

function noVideoText(st) {
  if (st.status === 'done') return 'Teslim etti';
  if (st.status === 'nosubmit') return 'Sınav bitti — teslim yok';
  if (st.status === 'lost') return `Bağlantı yok — ${st.lost_reason || 'sinyal gelmiyor'}`;
  if (!st.stream_ready) return 'Ekran yayını bekleniyor…';
  return 'Görüntü bağlanıyor…';
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
    setText(tile.badge, STATUS_LABEL[st.status] || st.status);
    setText(tile.name, `${st.ad} ${st.soyad}`.trim());
    setText(tile.net, [st.ip || '?', st.hostname || '?', st.mac || 'MAC yok'].join(' · '));
    tile.net.title = `IP: ${st.ip}\nBilgisayar: ${st.hostname}\nMAC: ${st.mac}`;
    setText(tile.fg, st.fg_process ? `Önde: ${st.fg_process}` : '');
    tile.fg.title = st.fg_title || '';
    tile.warn.hidden = st.warn_count === 0;
    setText(tile.warn, String(st.warn_count));
    tile.warn.title = `${st.warn_count} görülmemiş uyarı`;
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
}

/* ----------------------------------------------------------------- üst bölüm */

function renderHeader() {
  setText($('className'), `Sınıf: ${S.class.sinif_adi}`);
  setText($('teacherName'), `Öğretmen: ${S.class.ogretmen_adi}`);
  document.title = `Sınav — ${S.class.sinif_adi}`;

  const state = S.exam.state;
  const stateNode = $('examState');
  setText(stateNode, STATE_LABEL[state] || state);
  stateNode.className = `state state-${state.toLowerCase()}`;

  setText($('sumConnected'), String(S.summary.connected));
  setText($('sumWarned'), String(S.summary.warned));
  setText($('sumLost'), String(S.summary.lost));
  setText($('sumSubmitted'), String(S.summary.submitted));

  const file = S.exam.file;
  const fileInfo = $('examFileInfo');
  setText(fileInfo, file ? `${file.name} (${fmtBytes(file.size)})` : 'Dosya yüklenmedi');
  fileInfo.classList.toggle('set', Boolean(file));
  fileInfo.title = file ? `SHA-256: ${file.sha256}` : '';

  const rosterInfo = $('rosterInfo');
  setText(rosterInfo, S.roster.count ? `${S.roster.name} — ${S.roster.count} öğrenci` : 'Liste yüklenmedi');
  rosterInfo.classList.toggle('set', S.roster.count > 0);

  $('btnExamFile').disabled = state !== 'WAITING';
  $('btnStart').disabled = state !== 'WAITING';
  $('duration').disabled = state !== 'WAITING';
  $('btnEnd').disabled = state !== 'RUNNING';
  $('btnReset').disabled = state === 'RUNNING';
  $('btnStart').title = state === 'WAITING' && !file ? 'Önce sınav dosyasını yükleyin' : '';

  const missing = S.roster.missing;
  $('missing').hidden = missing.length === 0;
  setText($('missingCount'), String(missing.length));
  const signature = missing.map((m) => m.numara).join(',');
  const list = $('missingList');
  if (list.dataset.signature !== signature) {
    list.dataset.signature = signature;
    list.replaceChildren(...missing.map((m) => el('span', '', `${m.numara} ${m.ad} ${m.soyad}`.trim())));
  }

  renderBanners();
  renderFooter();
  renderTimer();
}

function renderBanners() {
  const messages = [];
  const health = S.health;
  if (!health.mediamtx_ok) {
    messages.push(['', 'MediaMTX çalışmıyor veya yanıt vermiyor: ekran görüntüleri gelmez ve kayıt yapılmaz. '
      + 'start-teacher.bat ile açılan MediaMTX penceresini kontrol edin.']);
  }
  if (health.discovery_error) messages.push(['', health.discovery_error]);
  if (health.config_error) messages.push(['', health.config_error]);
  if (!health.lan_ips.length) {
    messages.push(['', 'Bu bilgisayarın ağ bağlantısı bulunamadı. Sınıf modemine bağlı olduğunuzdan emin olun.']);
  } else if (S.exam.state === 'WAITING') {
    messages.push(['note', `Keşif çalışmazsa öğrenciler ajana elle şu IP adresini girebilir: ${health.lan_ips.join('  veya  ')}`]);
  }
  const box = $('banners');
  const signature = JSON.stringify(messages);
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  box.replaceChildren(...messages.map(([kind, text]) => el('div', `banner ${kind}`.trim(), text)));
}

function renderFooter() {
  const parts = [];
  if (S.retention_note) parts.push(`Kayıt saklama: ${S.retention_note}`);
  parts.push(`Teslimler: ${S.paths.submissions}`);
  parts.push(`Ekran kayıtları: ${S.paths.recordings}`);
  setText($('footer'), parts.join('   •   '));
}

function renderTimer() {
  if (!S) return;
  const now = Date.now() / 1000 + clockOffset;
  const exam = S.exam;
  let text = '';
  if (exam.state === 'RUNNING') {
    text = `Geçen: ${fmtDuration(now - exam.started_at)}`;
    if (exam.ends_at) {
      const left = exam.ends_at - now;
      text += left >= 0 ? `   Kalan: ${fmtDuration(left)}` : `   Süre doldu (+${fmtDuration(-left)})`;
    }
  } else if (exam.state === 'ENDED' && exam.started_at) {
    text = `Süre: ${fmtDuration(exam.ended_at - exam.started_at)}`;
  }
  setText($('timer'), text);
}
setInterval(renderTimer, 1000);

/* ----------------------------------------------------------------- uyarı akışı */

function renderAlerts() {
  const alerts = S.alerts;   // en yeni üstte
  const signature = alerts.length ? `${alerts[0].id}:${alerts.length}` : '';
  if (signature === alertSignature) return;
  alertSignature = signature;

  const newest = alerts.length ? alerts[0].id : 0;
  if (lastAlertId !== null && newest > lastAlertId) {
    const fresh = alerts.filter((a) => a.id > lastAlertId && a.severity !== 'info');
    if (fresh.length) beep(fresh.some((a) => a.severity === 'critical'));
  }
  lastAlertId = newest;

  // Art arda gelen aynı uyarıları tek satırda topla.
  const groups = [];
  for (const alert of alerts) {
    const last = groups[groups.length - 1];
    if (last && last.alert.numara === alert.numara && last.alert.message === alert.message) {
      last.count += 1;
    } else {
      groups.push({ alert, count: 1 });
    }
  }

  const items = groups.map(({ alert, count }) => {
    const li = el('li', `sev-${alert.severity}`);
    const head = el('div', 'a-head');
    const who = alert.numara ? `${alert.numara} ${alert.name}`.trim() : 'Genel';
    head.append(el('span', 'who', who), el('span', 'when', fmtClock(alert.ts)));
    const message = el('div', 'a-msg', alert.message);
    if (count > 1) message.append(el('span', 'a-repeat', `×${count}`));
    li.append(head, message);
    if (alert.numara) li.addEventListener('click', () => openModal(alert.numara));
    else li.classList.add('general');
    return li;
  });
  $('alertList').replaceChildren(...items);
  $('alertEmpty').hidden = items.length > 0;
}

/* ----------------------------------------------------------------- büyük pencere */

function openModal(numara) {
  if (!tiles.has(numara)) {
    toast(`${numara} şu anda listede değil.`, true);
    return;
  }
  modalNumara = numara;
  modalEvCount = -1;
  $('modalEvents').replaceChildren();
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
  list.append(el('dt', '', label), el('dd', '', value === '' || value == null ? '—' : String(value)));
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

  setText($('modalTitle'), `${st.numara} — ${st.ad} ${st.soyad}`);
  const badge = $('modalBadge');
  setText(badge, STATUS_LABEL[st.status] || st.status);
  badge.className = `badge st-badge-${st.status}`;
  badge.style.background = getComputedStyle(tile.badge).backgroundColor;
  badge.style.color = getComputedStyle(tile.badge).color;
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
  infoRow(info, 'Durum', (STATUS_LABEL[st.status] || st.status) + (st.lost_reason ? ` — ${st.lost_reason}` : ''));
  infoRow(info, 'IP adresi', st.ip);
  infoRow(info, 'Bilgisayar adı', st.hostname);
  infoRow(info, 'MAC adresi', st.mac);
  infoRow(info, 'Liste', ROSTER_LABEL[st.roster] || st.roster);
  infoRow(info, 'Giriş', `${fmtClock(st.login_ts)}${st.login_count > 1 ? ` (${st.login_count}. giriş)` : ''}`);
  infoRow(info, 'Son sinyal', `${st.last_seen_s} sn önce`);
  infoRow(info, 'Öndeki pencere', st.fg_process ? `${st.fg_process}${st.fg_title ? ` — ${st.fg_title}` : ''}` : '');
  infoRow(info, 'Monitör sayısı', st.monitors || '');
  infoRow(info, 'Ekran yayını', `${st.stream_ready ? 'var' : 'YOK'} (ffmpeg ${st.ffmpeg_alive ? 'çalışıyor' : 'çalışmıyor'})`);
  infoRow(info, 'Görülmemiş uyarı', st.warn_count);
  if (st.submission) {
    const sub = st.submission;
    infoRow(info, 'Teslim', `${sub.filename}${sub.auto ? ' (otomatik)' : ''} — ${fmtClock(sub.ts)}`
      + (st.submission_count > 1 ? `, toplam ${st.submission_count} sürüm` : ''));
    infoRow(info, 'SHA-256', sub.sha256);
  } else {
    infoRow(info, 'Teslim', 'yok');
  }
  const sep = S.paths.recordings.includes('\\') ? '\\' : '/';
  infoRow(info, 'Kayıt klasörü', `${S.paths.recordings}${sep}s${sep}${st.numara}`);
  infoRow(info, 'Ajan sürümü', st.agent_version);
  $('modalInfo').replaceChildren(info);

  if (st.ev_count !== modalEvCount) {
    modalEvCount = st.ev_count;
    loadModalEvents(st.numara);
  }
}

async function loadModalEvents(numara) {
  let data;
  try {
    data = await api(`/panel/api/events?numara=${encodeURIComponent(numara)}`, { method: 'GET' });
  } catch (_) {
    return;
  }
  if (modalNumara !== numara) return;
  const items = data.events.slice().reverse().map((event) => {
    const li = el('li', `sev-${event.severity}`);
    li.append(el('span', 'when', fmtClock(event.ts)), document.createTextNode(event.message));
    return li;
  });
  $('modalEvents').replaceChildren(...items);
}

/* ----------------------------------------------------------------- ana çizim + canlı bağlantı */

function render() {
  renderHeader();
  renderTiles();
  renderAlerts();
  renderModal();
}

function connectStream() {
  const source = new EventSource('/panel/api/stream');
  source.onmessage = (message) => {
    S = JSON.parse(message.data);
    clockOffset = S.server_time - Date.now() / 1000;
    document.body.classList.remove('offline');
    const banner = $('banners').querySelector('.server-down');
    if (banner) { banner.remove(); $('banners').dataset.signature = ''; }
    render();
  };
  source.onerror = () => {
    // EventSource kendiliğinden yeniden bağlanır; bu arada durumu göster.
    const box = $('banners');
    if (!box.querySelector('.server-down')) {
      box.prepend(el('div', 'banner server-down',
        'Sunucuyla bağlantı kesildi. Sunucu penceresi (start-teacher.bat) açık mı? Yeniden bağlanılıyor…'));
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

function bindControls() {
  $('btnExamFile').addEventListener('click', () => $('fileExam').click());
  $('fileExam').addEventListener('change', () => uploadFile(
    $('fileExam'), '/panel/api/exam-file', (file) => `Sınav dosyası yüklendi: ${file.name}`));

  $('btnRoster').addEventListener('click', () => $('fileRoster').click());
  $('fileRoster').addEventListener('change', () => uploadFile(
    $('fileRoster'), '/panel/api/roster', (file, data) => `Öğrenci listesi yüklendi: ${data.count} öğrenci`));

  $('btnStart').addEventListener('click', async () => {
    const duration = parseInt($('duration').value, 10) || 0;
    const question = 'Sınav başlatılsın mı?\n\n'
      + 'Tüm öğrencilerde sınav dosyası açılacak ve izin verilmeyen programlar kısa bir geri sayımdan sonra kapatılacak.'
      + (duration ? `\nSüre: ${duration} dakika.` : '');
    if (!confirm(question)) return;
    try {
      await api('/panel/api/start', { json: { duration_min: duration } });
      toast('Sınav başlatıldı.');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnEnd').addEventListener('click', async () => {
    const question = 'Sınavı bitirmek istediğinize emin misiniz?\n\n'
      + 'Teslim etmemiş öğrencilerin son kaydettiği dosya otomatik toplanacak ve ajanlar kapanacak. Bu işlem geri alınamaz.';
    if (!confirm(question)) return;
    try {
      await api('/panel/api/end');
      toast('Sınav bitirildi. Otomatik teslimler toplanıyor…');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('btnReset').addEventListener('click', async () => {
    const question = 'Yeni sınav hazırlansın mı?\n\n'
      + 'Mevcut öğrenci oturumları, olay kaydı ve teslim dosyaları silinmez; data/arsiv/ altında '
      + 'tarihli bir klasöre taşınır. Öğrenci listesi korunur, sınav dosyasını yeniden yüklemeniz gerekir.';
    if (!confirm(question)) return;
    try {
      const data = await api('/panel/api/reset');
      toast(data.archive ? `Yeni sınav hazır. Önceki sınav arşivlendi: ${data.archive}` : 'Yeni sınav hazır.');
    } catch (error) {
      toast(error.message, true);
    }
  });

  $('ackAll').addEventListener('click', async () => {
    try { await api('/panel/api/ack', { json: {} }); } catch (error) { toast(error.message, true); }
  });
  $('modalAck').addEventListener('click', async () => {
    if (!modalNumara) return;
    try { await api('/panel/api/ack', { json: { numara: modalNumara } }); } catch (error) { toast(error.message, true); }
  });
  $('modalClose').addEventListener('click', closeModal);
  $('modal').addEventListener('click', (event) => { if (event.target === $('modal')) closeModal(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && modalNumara) closeModal(); });

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

  const size = $('tileSize');
  size.value = pref('tileSize', '230');
  const applySize = () => document.documentElement.style.setProperty('--tile', `${size.value}px`);
  applySize();
  size.addEventListener('input', () => { applySize(); setPref('tileSize', size.value); });
}

bindControls();
connectStream();
