/**
 * TX3 Command Center - Core Controller
 * LinkedIn Professional Theme
 */

const CONFIG_DEFAULTS = {
  routeMode: 'auto', // 'auto', 'lan', 'cloudflare'
  lanUrl: 'http://192.168.100.232:3030',
  cloudUrl: 'https://vault.umiaq.top',
  fbLanUrl: 'http://192.168.100.232:8080',
  fbCloudUrl: 'https://files.umiaq.top'
};

let config = { ...CONFIG_DEFAULTS };
let activeBaseUrl = config.lanUrl;
let isLanActive = true;
let heartbeatTimer = null;
let currentClips = [];

// Native Android Bridge Helper
const Native = {
  vibrate(ms = 35) {
    if (window.AndroidBridge && typeof window.AndroidBridge.vibrate === 'function') {
      window.AndroidBridge.vibrate(ms);
    } else if (navigator.vibrate) {
      navigator.vibrate(ms);
    }
  },
  toast(msg) {
    if (window.AndroidBridge && typeof window.AndroidBridge.showToast === 'function') {
      window.AndroidBridge.showToast(msg);
    } else {
      console.log('[Toast]', msg);
    }
  },
  openExternal(url) {
    if (window.AndroidBridge && typeof window.AndroidBridge.openExternalUrl === 'function') {
      window.AndroidBridge.openExternalUrl(url);
    } else {
      window.open(url, '_blank');
    }
  },
  stopRefreshing() {
    if (window.AndroidBridge && typeof window.AndroidBridge.stopRefreshing === 'function') {
      window.AndroidBridge.stopRefreshing();
    }
  }
};

// Initialize App
window.addEventListener('DOMContentLoaded', () => {
  loadStoredConfig();
  detectNetworkAndInit();
});

function loadStoredConfig() {
  try {
    const saved = localStorage.getItem('tx3_config');
    if (saved) {
      const parsed = JSON.parse(saved);
      // Auto-migrate obsolete temporary quick tunnels (*.trycloudflare.com, *.loca.lt, etc.)
      if (parsed.cloudUrl && (parsed.cloudUrl.includes('trycloudflare.com') || parsed.cloudUrl.includes('loca.lt') || parsed.cloudUrl.includes('ngrok'))) {
        console.warn('Auto-migrated legacy quick tunnel to vault.umiaq.top');
        parsed.cloudUrl = CONFIG_DEFAULTS.cloudUrl;
      }
      if (parsed.fbCloudUrl && (parsed.fbCloudUrl.includes('trycloudflare.com') || parsed.fbCloudUrl.includes('loca.lt') || parsed.fbCloudUrl.includes('ngrok'))) {
        parsed.fbCloudUrl = CONFIG_DEFAULTS.fbCloudUrl;
      }
      // Migrate case where fbLanUrl was saved with cloud URL
      if (parsed.fbLanUrl && parsed.fbLanUrl.startsWith('https://')) {
        parsed.fbCloudUrl = parsed.fbLanUrl;
        parsed.fbLanUrl = CONFIG_DEFAULTS.fbLanUrl;
      }
      config = { ...CONFIG_DEFAULTS, ...parsed };
      // Save back sanitized configuration
      localStorage.setItem('tx3_config', JSON.stringify(config));
    }
  } catch (e) {
    console.error('Failed to load settings', e);
  }
}

function saveSettings() {
  config.lanUrl = document.getElementById('cfgLanUrl').value.trim();
  config.cloudUrl = document.getElementById('cfgCloudUrl').value.trim();
  config.fbCloudUrl = document.getElementById('cfgFbUrl').value.trim();
  localStorage.setItem('tx3_config', JSON.stringify(config));
  Native.toast('Settings saved. Reconnecting...');
  closeSettingsModal();
  detectNetworkAndInit();
}

function resetSettingsToDefault() {
  Native.vibrate(30);
  config = { ...CONFIG_DEFAULTS };
  localStorage.removeItem('tx3_config');
  document.getElementById('cfgLanUrl').value = config.lanUrl;
  document.getElementById('cfgCloudUrl').value = config.cloudUrl;
  document.getElementById('cfgFbUrl').value = config.fbCloudUrl;
  setRouteMode('auto');
  Native.toast('Reset to default (vault.umiaq.top)');
  closeSettingsModal();
  detectNetworkAndInit();
}

function setRouteMode(mode) {
  config.routeMode = mode;
  document.getElementById('segAuto').classList.toggle('active', mode === 'auto');
  document.getElementById('segLan').classList.toggle('active', mode === 'lan');
  document.getElementById('segCloud').classList.toggle('active', mode === 'cloudflare');
}

// Network detection & route auto-failover
async function detectNetworkAndInit() {
  updateNetworkBadge('probing', 'Probing Route...');

  if (config.routeMode === 'cloudflare') {
    activeBaseUrl = config.cloudUrl;
    isLanActive = false;
    updateNetworkBadge('fallback', 'Cloudflare Tunnel');
    initPolling();
    return;
  }

  if (config.routeMode === 'lan') {
    activeBaseUrl = config.lanUrl;
    isLanActive = true;
    updateNetworkBadge('online', 'LAN: 192.168.100.232');
    initPolling();
    return;
  }

  // AUTO-DETECT: Fast probe LAN with 1200ms timeout
  const start = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1200);

    const res = await fetch(`${config.lanUrl}/api/pc-status`, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (res.ok) {
      const ping = Math.round(performance.now() - start);
      activeBaseUrl = config.lanUrl;
      isLanActive = true;
      updateNetworkBadge('online', `LAN Direct (${ping}ms)`);
      initPolling();
      return;
    }
  } catch (err) {
    console.log('LAN probe unreachable, falling back to Cloudflare Tunnel', err);
  }

  // Fallback to Cloudflare Tunnel
  activeBaseUrl = config.cloudUrl;
  isLanActive = false;
  updateNetworkBadge('fallback', 'Cloudflare (Remote)');
  initPolling();
}

function updateNetworkBadge(state, text) {
  const dot = document.getElementById('badgeDot');
  const label = document.getElementById('netRouteText');
  label.innerText = text;

  dot.className = 'badge-dot';
  if (state === 'online') dot.classList.add('online');
  else if (state === 'fallback') dot.classList.add('fallback');
  else if (state === 'error') dot.classList.add('error');
}

function initPolling() {
  fetchPcStatus();
  fetchSystemStats();
  fetchDotaSummary();

  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(() => {
    fetchPcStatus(true);
    fetchSystemStats(true);
  }, 4000);
}

// Refresh Dashboard
window.refreshDashboard = function () {
  Native.vibrate(20);
  detectNetworkAndInit();
  setTimeout(() => Native.stopRefreshing(), 600);
};

// Power Actions
async function sendPowerAction(action) {
  Native.vibrate(40);
  Native.toast(`Sending ${action.toUpperCase()} command...`);

  let endpoint = '';
  if (action === 'wake') endpoint = '/api/wake-pc';
  else if (action === 'shutdown') endpoint = '/api/shutdown-pc';
  else if (action === 'sleep') endpoint = '/api/sleep-pc';

  try {
    const res = await fetch(`${activeBaseUrl}${endpoint}`);
    const data = await res.json();
    Native.toast(data.status || data.message || `${action} sent`);
    setTimeout(() => fetchPcStatus(false), 1500);
  } catch (err) {
    Native.toast(`Failed: ${err.message}`);
  }
}

function confirmShutdown() {
  Native.vibrate(40);
  document.getElementById('shutdownModal').classList.add('active');
}

function closeShutdownModal() {
  document.getElementById('shutdownModal').classList.remove('active');
}

function executeShutdown() {
  closeShutdownModal();
  sendPowerAction('shutdown');
}

// PC Status Heartbeat
async function fetchPcStatus(isSilent = false) {
  try {
    const res = await fetch(`${activeBaseUrl}/api/pc-status`);
    const data = await res.json();
    renderPcStatus(data);
  } catch (err) {
    if (!isSilent) console.error('fetchPcStatus error', err);
    renderPcStatus({ online: false, error: true });
  }
}

function testPcStatus() {
  Native.vibrate(25);
  Native.toast('Pinging workstation agent...');
  fetchPcStatus();
}

function renderPcStatus(data) {
  const pill = document.getElementById('pcStatusPill');
  const txt = document.getElementById('pcStatusText');
  const hb = document.getElementById('pcHeartbeat');

  pill.className = 'status-pill';

  if (data && data.online) {
    pill.classList.add('pill-online');
    txt.innerText = 'ONLINE';
    const s = data.last_seen_seconds_ago != null ? Math.round(data.last_seen_seconds_ago) : (data.last_seen_seconds != null ? Math.round(data.last_seen_seconds) : 0);
    hb.innerText = `${s}s ago (DESKTOP-S700VJ0)`;
  } else {
    pill.classList.add('pill-offline');
    txt.innerText = 'OFFLINE';
    const s = data && data.last_seen_seconds_ago != null ? `${Math.round(data.last_seen_seconds_ago)}s ago` : 'Standby / Powered Off';
    hb.innerText = `Last seen: ${s}`;
  }
}

// TX3 Mini System Telemetry
async function fetchSystemStats(isSilent = false) {
  try {
    const res = await fetch(`${activeBaseUrl}/api/system-stats`);
    if (!res.ok) return;
    const data = await res.json();
    renderSystemStats(data);
  } catch (err) {
    if (!isSilent) console.error('fetchSystemStats error', err);
  }
}

function renderSystemStats(data) {
  if (!data) return;

  // Temperature
  const tempEl = document.getElementById('teleTemp');
  const tempBadge = document.getElementById('teleTempBadge');
  if (data.temp_c != null) {
    tempEl.innerText = `${data.temp_c}°C`;
    tempBadge.className = 'tele-badge badge-temp';
    if (data.temp_c < 65) {
      tempBadge.innerText = 'Optimal';
    } else if (data.temp_c < 75) {
      tempBadge.classList.add('warm');
      tempBadge.innerText = 'Warm';
    } else {
      tempBadge.classList.add('hot');
      tempBadge.innerText = 'High';
    }
  }

  // CPU Telemetry
  if (data.cpu) {
    document.getElementById('teleCpuPct').innerText = `${data.cpu.est_usage_pct}%`;
    document.getElementById('teleLoadAvg').innerText = `Load: ${data.cpu.load1}, ${data.cpu.load5}`;
    if (data.cpu.model) {
      document.getElementById('tx3SocModel').innerText = data.cpu.model.toUpperCase();
    }
  }

  // RAM Telemetry
  if (data.ram) {
    document.getElementById('teleRamVal').innerText = `${data.ram.used_mb} / ${data.ram.total_mb} MB`;
    document.getElementById('teleRamAvail').innerText = `${data.ram.avail_mb} MB Free`;
    document.getElementById('teleRamBar').style.width = `${data.ram.pct}%`;
  }

  // Uptime
  if (data.uptime) {
    document.getElementById('tx3Uptime').innerText = `Up: ${data.uptime}`;
  }

  // Storage Disks
  if (data.storage_vault) {
    document.getElementById('teleVaultLabel').innerText = data.storage_vault.label;
    document.getElementById('teleVaultCap').innerText = `${data.storage_vault.free_gb} GB Free / ${data.storage_vault.total_gb} GB`;
    document.getElementById('teleVaultBar').style.width = `${data.storage_vault.pct}%`;
  }

  if (data.storage_root) {
    document.getElementById('teleRootLabel').innerText = data.storage_root.label;
    document.getElementById('teleRootCap').innerText = `${data.storage_root.free_gb} GB Free / ${data.storage_root.total_gb} GB`;
    document.getElementById('teleRootBar').style.width = `${data.storage_root.pct}%`;
  }
}

// Dota 2 Command Hub & Recent Matches
let allDotaRecent = [];

async function fetchDotaSummary() {
  const container = document.getElementById('vaultList');
  try {
    const res = await fetch(`${activeBaseUrl}/api/dota/summary`);
    const data = await res.json();

    document.getElementById('dotaStatMatches').innerText = `${data.total_matches}`;
    document.getElementById('dotaBadgeCount').innerText = `${data.total_matches} Matches`;
    document.getElementById('dotaStatClips').innerText = `${data.total_clips}`;
    document.getElementById('dotaStatSize').innerText = `${data.total_size_gb} GB`;

    if (data.latest_match && data.latest_match.date) {
      document.getElementById('dotaLatestDate').innerText = `Latest: ${data.latest_match.date}`;
    }

    allDotaRecent = data.recent_matches || [];
    renderRecentDotaMatches(allDotaRecent);
  } catch (err) {
    console.error('fetchDotaSummary error', err);
    fetchVaultSessions(); // Fallback to legacy sessions list
  }
}

function handleDotaSearch(query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) {
    renderRecentDotaMatches(allDotaRecent);
    return;
  }
  const filtered = allDotaRecent.filter(s => {
    return (s.folder_name && s.folder_name.toLowerCase().includes(q)) ||
           (s.date && s.date.toLowerCase().includes(q)) ||
           (s.session_label && s.session_label.toLowerCase().includes(q));
  });
  renderRecentDotaMatches(filtered);
}

function renderRecentDotaMatches(matches) {
  const container = document.getElementById('vaultList');
  if (!matches || matches.length === 0) {
    container.innerHTML = '<div class="empty-state">No matching match sessions found.</div>';
    return;
  }

  container.innerHTML = matches.map(s => {
    const folder = s.folder_name || s.folder || '';
    const dateStr = s.date || '';
    const timeStr = s.session_label || '';
    const displayTitle = dateStr ? `${dateStr} • ${timeStr}` : folder;
    const count = s.clip_count != null ? s.clip_count : 0;
    const sizeMb = s.total_mb != null ? s.total_mb : 0;
    const sizeGb = (sizeMb / 1024).toFixed(1);
    const sizeDisplay = sizeMb >= 1000 ? `${sizeGb} GB` : `${sizeMb} MB`;

    return `
      <div class="session-item" onclick="openSessionClips('${encodeURIComponent(folder)}')">
        <div class="session-left">
          <div class="session-icon">
            <svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>
          </div>
          <div>
            <div class="session-title">${escapeHtml(displayTitle)}</div>
            <div class="session-meta">${count} clips • ${sizeDisplay}</div>
          </div>
        </div>
        <button class="btn-watch">Watch</button>
      </div>
    `;
  }).join('');
}

// Fallback legacy sessions loader
async function fetchVaultSessions() {
  const container = document.getElementById('vaultList');
  try {
    const res = await fetch(`${activeBaseUrl}/api/sessions`);
    const data = await res.json();
    const sessions = Array.isArray(data) ? data : (data.sessions || []);
    allDotaRecent = sessions.slice(0, 15);
    renderRecentDotaMatches(allDotaRecent);
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Unable to load Vault (${err.message}).</div>`;
  }
}

async function openSessionClips(encodedFolder) {
  Native.vibrate(25);
  const folder = decodeURIComponent(encodedFolder);
  const modal = document.getElementById('videoModal');
  const title = document.getElementById('modalVideoTitle');
  const subtitle = document.getElementById('modalVideoSubtitle');
  const clipList = document.getElementById('modalClipList');

  title.innerText = folder;
  subtitle.innerText = 'Loading clips...';
  clipList.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';
  modal.classList.add('active');

  try {
    const res = await fetch(`${activeBaseUrl}/api/clips?folder=${encodeURIComponent(folder)}`);
    const data = await res.json();
    currentClips = Array.isArray(data) ? data : (data.clips || []);

    subtitle.innerText = `${currentClips.length} clips recorded`;

    if (currentClips.length > 0) {
      renderClipList(0);
      playClip(0);
    } else {
      clipList.innerHTML = '<div class="empty-state">No mp4 video files found.</div>';
    }
  } catch (err) {
    subtitle.innerText = 'Failed to load clips';
    clipList.innerHTML = `<div class="empty-state">${err.message}</div>`;
  }
}

function renderClipList(activeIndex) {
  const clipList = document.getElementById('modalClipList');
  clipList.innerHTML = currentClips.map((c, i) => `
    <div class="clip-chip ${i === activeIndex ? 'active' : ''}" onclick="playClip(${i})">
      <span>▶ ${escapeHtml(c.name)}</span>
      <span>${c.size_mb} MB</span>
    </div>
  `).join('');
}

function playClip(index) {
  Native.vibrate(20);
  renderClipList(index);
  const clip = currentClips[index];
  const player = document.getElementById('videoPlayer');
  player.src = `${activeBaseUrl}/api/video?path=${encodeURIComponent(clip.path)}`;
  player.play().catch(e => console.log('Autoplay deferred', e));
}

function closeVideoModal() {
  const modal = document.getElementById('videoModal');
  const player = document.getElementById('videoPlayer');
  player.pause();
  player.src = '';
  modal.classList.remove('active');
}

// Quick Launch App URLs
function launchAppUrl(appKey) {
  Native.vibrate(25);
  let targetUrl = '';
  if (appKey === 'files') {
    targetUrl = isLanActive ? config.fbLanUrl : config.fbCloudUrl;
    Native.toast('Opening FileBrowser Cloud...');
  } else if (appKey === 'pocketbase') {
    targetUrl = isLanActive ? 'http://192.168.100.232:8090/_/' : 'https://pb.umiaq.top/_/';
    Native.toast('Opening PocketBase Admin Dashboard...');
  } else if (appKey === 'photos') {
    targetUrl = isLanActive ? 'http://192.168.100.232:3030/photos' : 'https://photos.umiaq.top';
    Native.toast('Opening Google Photos Web Vault...');
  } else if (appKey === 'jellyfin') {
    targetUrl = isLanActive ? 'http://192.168.100.232:8096' : 'https://tv.umiaq.top';
    Native.toast('Opening Jellyfin TV...');
  } else if (appKey === 'dota') {
    targetUrl = isLanActive ? 'http://192.168.100.232:3030' : config.cloudUrl;
    Native.toast('Opening Dota 2 Web Vault...');
  }
  if (targetUrl) {
    Native.openExternal(targetUrl);
  }
}

function launchDotaWeb() {
  launchAppUrl('dota');
}

function launchFileBrowser() {
  launchAppUrl('files');
}

function copyCredentials(text) {
  Native.vibrate(20);
  navigator.clipboard.writeText(text).then(() => {
    Native.toast('Credentials copied to clipboard!');
  }).catch(() => {
    Native.toast(`Login: ${text}`);
  });
}

// Settings Modal
function showSettings() {
  Native.vibrate(25);
  setRouteMode(config.routeMode);
  document.getElementById('cfgLanUrl').value = config.lanUrl;
  document.getElementById('cfgCloudUrl').value = config.cloudUrl;
  document.getElementById('cfgFbUrl').value = config.fbCloudUrl || CONFIG_DEFAULTS.fbCloudUrl;
  const currentActiveEl = document.getElementById('cfgActiveRouteInfo');
  if (currentActiveEl) {
    currentActiveEl.innerText = `Active: ${activeBaseUrl} (${isLanActive ? 'LAN Direct' : 'Cloudflare Tunnel'})`;
  }
  document.getElementById('settingsModal').classList.add('active');
}

function closeSettingsModal() {
  document.getElementById('settingsModal').classList.remove('active');
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


// ================= TABS LOGIC =================
let activeTab = 'power';

function switchTab(tabName) {
  Native.vibrate(20);
  activeTab = tabName;

  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

  const fab = document.getElementById('driveFab');
  if (fab) fab.classList.toggle('active', tabName === 'drive');

  if (tabName === 'power') {
    document.getElementById('tabPower').classList.add('active');
    document.getElementById('panePower').classList.add('active');
  } else if (tabName === 'drive') {
    document.getElementById('tabDrive').classList.add('active');
    document.getElementById('paneDrive').classList.add('active');
    fetchDriveStorages();
    if (!driveData.breadcrumbs || driveData.breadcrumbs.length === 0) {
      fetchDriveFolder('');
    }
  } else if (tabName === 'photos') {
    document.getElementById('tabPhotos').classList.add('active');
    document.getElementById('panePhotos').classList.add('active');
    if (!photoCatalog.timeline || photoCatalog.timeline.length === 0) {
      fetchPhotosCatalog();
    }
  } else if (tabName === 'dota') {
    document.getElementById('tabDota').classList.add('active');
    document.getElementById('paneDota').classList.add('active');
    fetchDotaSummary();
  }
}

// ================= PHOTOS VAULT CONTROLLER =================
let photoCatalog = { albums: [], total_count: 0, timeline: [] };
let activePhotoAlbum = 'All';
let filteredPhotos = [];
let currentPhotoIndex = 0;
let isPhotoExifOpen = false;

async function fetchPhotosCatalog(forceRescan = false) {
  const container = document.getElementById('appPhotoStream');
  const endpoint = forceRescan ? '/api/photos/rescan' : '/api/photos/catalog';

  try {
    const res = await fetch(`${activeBaseUrl}${endpoint}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    photoCatalog = await res.json();
    renderAppAlbumChips();
    applyPhotoFilter();
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Failed to connect to Photos Vault: ${escapeHtml(err.message)}</p>
        <button class="btn btn-subtle" style="margin-top: 10px;" onclick="fetchPhotosCatalog()">Retry</button>
      </div>
    `;
  }
}

function renderAppAlbumChips() {
  const bar = document.getElementById('appAlbumChips');
  const albums = ['All', ...(photoCatalog.albums || [])];

  bar.innerHTML = albums.map(a => {
    let count = a === 'All' ? photoCatalog.total_count : 0;
    if (a !== 'All' && photoCatalog.timeline) {
      for (const t of photoCatalog.timeline) {
        for (const p of t.photos) {
          if (p.album === a) count++;
        }
      }
    }
    return `
      <button class="album-chip ${a === activePhotoAlbum ? 'active' : ''}" onclick="filterPhotoAlbum('${escapeHtml(a)}')">
        ${a === 'All' ? 'All Photos' : escapeHtml(a)} (${count})
      </button>
    `;
  }).join('');
}

function filterPhotoAlbum(albumName) {
  Native.vibrate(15);
  activePhotoAlbum = albumName;
  renderAppAlbumChips();
  applyPhotoFilter();
}

function handlePhotoSearch(query) {
  applyPhotoFilter(query.trim().toLowerCase());
}

function applyPhotoFilter(searchQuery = '') {
  filteredPhotos = [];
  const groups = [];

  if (photoCatalog && photoCatalog.timeline) {
    for (const section of photoCatalog.timeline) {
      const matching = section.photos.filter(p => {
        const matchAlbum = (activePhotoAlbum === 'All' || p.album === activePhotoAlbum);
        if (!matchAlbum) return false;
        if (!searchQuery) return true;
        return p.name.toLowerCase().includes(searchQuery) ||
               p.date_str.toLowerCase().includes(searchQuery) ||
               p.album.toLowerCase().includes(searchQuery);
      });

      if (matching.length > 0) {
        groups.push({
          month_year: section.month_year,
          photos: matching
        });
        filteredPhotos.push(...matching);
      }
    }
  }

  renderAppPhotoTimeline(groups);
}

function renderAppPhotoTimeline(groups) {
  const container = document.getElementById('appPhotoStream');
  if (!groups || groups.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No photos found matching criteria.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = groups.map(g => `
    <div class="photo-timeline-group">
      <div class="photo-timeline-title">
        <span>${escapeHtml(g.month_year)}</span>
        <span class="photo-timeline-count">${g.photos.length} item${g.photos.length > 1 ? 's' : ''}</span>
      </div>
      <div class="companion-photo-grid">
        ${g.photos.map(p => `
          <div class="companion-photo-tile" onclick="openPhotoLightbox('${p.id}')">
            <img class="companion-photo-thumb"
                 loading="lazy"
                 src="${activeBaseUrl}/api/photos/thumb?id=${p.id}"
                 alt="${escapeHtml(p.name)}">
            ${p.is_video ? `<div class="companion-vid-badge">▶ VID</div>` : ''}
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

// Photo Lightbox
function openPhotoLightbox(photoId) {
  Native.vibrate(25);
  const idx = filteredPhotos.findIndex(p => p.id === photoId);
  if (idx === -1) return;
  currentPhotoIndex = idx;
  showPhotoInLightbox(currentPhotoIndex);
  document.getElementById('photoLightbox').classList.add('active');
}

function closePhotoLightbox() {
  Native.vibrate(15);
  const lb = document.getElementById('photoLightbox');
  lb.classList.remove('active');
  const vid = document.getElementById('lbVideo');
  vid.pause();
  vid.src = '';
  isPhotoExifOpen = false;
  document.getElementById('exifDrawer').classList.remove('open');
}

function showPhotoInLightbox(idx) {
  if (idx < 0 || idx >= filteredPhotos.length) return;
  currentPhotoIndex = idx;
  const p = filteredPhotos[idx];

  document.getElementById('lbTitle').innerText = p.name;
  document.getElementById('lbCounter').innerText = `${idx + 1} / ${filteredPhotos.length}`;

  const img = document.getElementById('lbImg');
  const vid = document.getElementById('lbVideo');

  if (p.is_video) {
    img.style.display = 'none';
    vid.style.display = 'block';
    vid.src = `${activeBaseUrl}/api/photos/raw?id=${p.id}`;
    vid.play().catch(() => {});
  } else {
    vid.pause();
    vid.style.display = 'none';
    img.style.display = 'block';
    img.src = `${activeBaseUrl}/api/photos/raw?id=${p.id}`;
  }

  // Update EXIF
  const content = document.getElementById('exifDrawerContent');
  let exifHtml = `
    <div class="exif-row">
      <span class="exif-label">Filename</span>
      <span class="exif-val">${escapeHtml(p.name)}</span>
    </div>
    <div class="exif-row">
      <span class="exif-label">Date Taken</span>
      <span class="exif-val">${escapeHtml(p.date_str)} (${escapeHtml(p.time_str)})</span>
    </div>
    <div class="exif-row">
      <span class="exif-label">Album & Size</span>
      <span class="exif-val">${escapeHtml(p.album)} • ${p.size_mb} MB</span>
    </div>
  `;

  if (p.exif && (p.exif.model || p.exif.make)) {
    exifHtml += `
      <div class="exif-row">
        <span class="exif-label">Camera</span>
        <span class="exif-val">${escapeHtml(p.exif.make || '')} ${escapeHtml(p.exif.model || '')}</span>
      </div>
    `;
    const params = [];
    if (p.exif.focal_length) params.push(p.exif.focal_length);
    if (p.exif.fnumber) params.push(p.exif.fnumber);
    if (p.exif.exposure) params.push(p.exif.exposure);
    if (p.exif.iso) params.push(p.exif.iso);
    if (params.length > 0) {
      exifHtml += `
        <div class="exif-row">
          <span class="exif-label">Settings</span>
          <span class="exif-val">${escapeHtml(params.join(' • '))}</span>
        </div>
      `;
    }
  }

  content.innerHTML = exifHtml;
}

function prevPhoto() {
  Native.vibrate(15);
  if (currentPhotoIndex > 0) {
    showPhotoInLightbox(currentPhotoIndex - 1);
  } else {
    showPhotoInLightbox(filteredPhotos.length - 1);
  }
}

function nextPhoto() {
  Native.vibrate(15);
  if (currentPhotoIndex < filteredPhotos.length - 1) {
    showPhotoInLightbox(currentPhotoIndex + 1);
  } else {
    showPhotoInLightbox(0);
  }
}

function togglePhotoExif() {
  Native.vibrate(15);
  isPhotoExifOpen = !isPhotoExifOpen;
  document.getElementById('exifDrawer').classList.toggle('open', isPhotoExifOpen);
}

function downloadCurrentPhoto() {
  Native.vibrate(25);
  const p = filteredPhotos[currentPhotoIndex];
  if (!p) return;
  const url = `${activeBaseUrl}/api/photos/raw?id=${p.id}&download=1`;
  Native.openExternal(url);
}

function rescanPhotoCatalog() {
  Native.vibrate(30);
  Native.toast('Rescanning photo library on TX3 Mini...');
  fetchPhotosCatalog(true);
}


// ================= GOOGLE DRIVE CONTROLLER =================
let currentStorageId = '3tb_ext';
let availableStorages = [];
let driveCurrentPath = '';
let driveViewMode = localStorage.getItem('tx3_drive_view') || 'grid'; // 'grid' | 'list'
let driveSortBy = 'name'; // 'name' | 'date' | 'size'
let driveSortOrder = 'asc';
let driveData = { storage_id: '3tb_ext', storage_name: '3TB-ext', current_path: '', breadcrumbs: [], folders: [], files: [] };
let selectedDriveItem = null;
let isItemFolder = false;

async function fetchDriveStorages() {
  try {
    const res = await fetch(`${activeBaseUrl}/api/drive/storages`);
    if (res.ok) {
      const data = await res.json();
      availableStorages = data.storages || [];
      if (availableStorages.length > 0) {
        if (!availableStorages.some(s => s.id === currentStorageId)) {
          currentStorageId = availableStorages[0].id;
        }
      }
      renderStorageChips();
    }
  } catch (e) {
    console.warn('Failed to load storages', e);
  }
}

function renderStorageChips() {
  const container = document.getElementById('driveStorageChips');
  if (!container) return;
  if (!availableStorages || availableStorages.length === 0) {
    availableStorages = [
      { id: '3tb_ext', name: '3TB-ext', icon: '💾', free_human: 'Active' },
      { id: '500gb_ext', name: '500GB-ext', icon: '🗄️', free_human: 'Active' }
    ];
  }

  container.innerHTML = availableStorages.map(s => {
    const isActive = (s.id === currentStorageId);
    return `
      <button class="storage-chip ${isActive ? 'active' : ''}" onclick="selectStorage('${s.id}')">
        <span>${s.icon || '💾'}</span>
        <span>${escapeHtml(s.name)}</span>
        <span class="chip-free">(${s.free_human || ''})</span>
      </button>
    `;
  }).join('');
}

function selectStorage(storageId) {
  if (currentStorageId === storageId && driveCurrentPath === '') return;
  Native.vibrate(15);
  currentStorageId = storageId;
  driveCurrentPath = '';
  renderStorageChips();
  fetchDriveFolder('');
}

async function fetchDriveFolder(path = driveCurrentPath) {
  driveCurrentPath = path;
  const area = document.getElementById('driveContentArea');
  area.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Reading folder...</p></div>';

  try {
    const res = await fetch(`${activeBaseUrl}/api/drive/list?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(path)}&sort=${driveSortBy}&order=${driveSortOrder}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    driveData = await res.json();
    if (driveData.storage_id) {
      currentStorageId = driveData.storage_id;
      renderStorageChips();
    }
    renderDriveBreadcrumbs(driveData.breadcrumbs || []);
    renderDriveUI();
  } catch (err) {
    area.innerHTML = `
      <div class="empty-state">
        <p>Failed to load drive: ${escapeHtml(err.message)}</p>
        <button class="btn btn-subtle" style="margin-top: 10px;" onclick="fetchDriveFolder('${escapeHtml(path)}')">Retry</button>
      </div>
    `;
  }
}

function renderDriveBreadcrumbs(crumbs) {
  const bar = document.getElementById('driveBreadcrumbs');
  const rootTitle = driveData.storage_name ? `📁 ${driveData.storage_name}` : '📁 Vault';
  if (!crumbs || crumbs.length === 0) {
    bar.innerHTML = `<span class="crumb active">${escapeHtml(rootTitle)}</span>`;
    return;
  }

  bar.innerHTML = crumbs.map((c, idx) => {
    const isLast = (idx === crumbs.length - 1);
    const label = idx === 0 ? rootTitle : escapeHtml(c.name);
    if (isLast) {
      return `<span class="crumb active">${label}</span>`;
    } else {
      return `
        <span class="crumb" onclick="navigateDrive('${escapeHtml(c.path)}')">${label}</span>
        <span class="crumb-sep">›</span>
      `;
    }
  }).join('');
}

function renderDriveUI(filterQuery = '') {
  const area = document.getElementById('driveContentArea');
  const q = (filterQuery || '').trim().toLowerCase();

  const folders = (driveData.folders || []).filter(f => !q || f.name.toLowerCase().includes(q));
  const files = (driveData.files || []).filter(f => !q || f.name.toLowerCase().includes(q));

  if (folders.length === 0 && files.length === 0) {
    area.innerHTML = `
      <div class="empty-state">
        <div style="font-size: 42px; margin-bottom: 8px;">📁</div>
        <h3>Folder is empty</h3>
        <p style="margin-top: 6px; font-size: 12px;">Tap (+) to upload files or create a subfolder.</p>
      </div>
    `;
    return;
  }

  let html = '';

  // Folders Section
  if (folders.length > 0) {
    html += `
      <div class="drive-section-title">
        <span>Folders (${folders.length})</span>
      </div>
      <div class="drive-folders-grid ${driveViewMode === 'list' ? 'list-view' : ''}">
        ${folders.map((f, i) => `
          <div class="drive-folder-card" onclick="navigateDrive('${escapeHtml(f.path)}')">
            <div class="folder-left">
              <svg viewBox="0 0 24 24" class="folder-icon"><path fill="currentColor" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>
              <div class="folder-meta">
                <span class="folder-name">${escapeHtml(f.name)}</span>
                <span class="folder-count">${f.item_count} items</span>
              </div>
            </div>
            <button class="btn-item-more" onclick="event.stopPropagation(); openItemSheet(driveData.folders[${i}], true)">
              <svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
            </button>
          </div>
        `).join('')}
      </div>
    `;
  }

  // Files Section
  if (files.length > 0) {
    html += `
      <div class="drive-section-title">
        <span>Files (${files.length})</span>
        <span style="font-weight: 500; font-size: 11px;">View: ${driveViewMode.toUpperCase()}</span>
      </div>
    `;

    if (driveViewMode === 'grid') {
      html += `
        <div class="drive-files-grid">
          ${files.map((f, i) => {
            const isImg = f.type === 'image';
            const isVid = f.type === 'video';
            const thumbUrl = isImg ? `${activeBaseUrl}/api/drive/raw?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(f.path)}` : '';

            return `
              <div class="drive-file-card" onclick="openDriveItem(driveData.files[${i}])">
                <div class="drive-file-preview">
                  ${isImg ? `
                    <img class="drive-file-thumb" loading="lazy" src="${thumbUrl}" alt="${escapeHtml(f.name)}">
                  ` : `
                    <div class="drive-file-badge-icon">${getFileIconSvg(f.type, f.ext)}</div>
                  `}
                  ${isVid ? `<div class="companion-vid-badge">▶ VIDEO</div>` : ''}
                </div>
                <div class="drive-file-footer">
                  <div class="drive-file-info">
                    <span class="drive-file-name">${escapeHtml(f.name)}</span>
                    <span class="drive-file-sub">${f.size_str} • ${f.date_str}</span>
                  </div>
                  <button class="btn-item-more" onclick="event.stopPropagation(); openItemSheet(driveData.files[${i}], false)">
                    <svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
                  </button>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    } else {
      // List View
      html += `
        <div class="drive-files-list">
          ${files.map((f, i) => `
            <div class="drive-file-row" onclick="openDriveItem(driveData.files[${i}])">
              <div class="row-left">
                <div class="row-icon">${getFileIconSvg(f.type, f.ext)}</div>
                <div class="row-text">
                  <span class="row-title">${escapeHtml(f.name)}</span>
                  <span class="row-sub">${f.size_str} • ${f.date_str}</span>
                </div>
              </div>
              <button class="btn-item-more" onclick="event.stopPropagation(); openItemSheet(driveData.files[${i}], false)">
                <svg viewBox="0 0 24 24"><path fill="currentColor" d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
              </button>
            </div>
          `).join('')}
        </div>
      `;
    }
  }

  area.innerHTML = html;
}

function getFileIconSvg(type, ext) {
  if (type === 'video') {
    return `<svg viewBox="0 0 24 24"><path fill="#EA4335" d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z"/></svg>`;
  }
  if (type === 'image') {
    return `<svg viewBox="0 0 24 24"><path fill="#34A853" d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>`;
  }
  if (type === 'audio') {
    return `<svg viewBox="0 0 24 24"><path fill="#FBBC04" d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>`;
  }
  if (type === 'pdf') {
    return `<svg viewBox="0 0 24 24"><path fill="#EA4335" d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3H19v1h1.5V11H19v2h-1.5V7h3v1.5z"/></svg>`;
  }
  if (type === 'archive') {
    return `<svg viewBox="0 0 24 24"><path fill="#4285F4" d="M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 10h-4v-2h4v2zm0-4h-4v-2h4v2z"/></svg>`;
  }
  if (type === 'apk') {
    return `<svg viewBox="0 0 24 24"><path fill="#3DDC84" d="M17.6 9.48l1.84-3.18c.16-.31.04-.69-.26-.85-.29-.15-.68-.05-.85.26l-1.88 3.24c-1.34-.58-2.85-.92-4.45-.92-1.6 0-3.11.34-4.45.92L5.67 5.71c-.17-.31-.56-.41-.85-.26-.3.16-.42.54-.26.85l1.84 3.18C3.12 11.23 1 14.33 1 18h22c0-3.67-2.12-6.77-5.4-8.52zM7 15.25c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25zm10 0c-.69 0-1.25-.56-1.25-1.25s.56-1.25 1.25-1.25 1.25.56 1.25 1.25-.56 1.25-1.25 1.25z"/></svg>`;
  }
  return `<svg viewBox="0 0 24 24"><path fill="#5F6368" d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>`;
}

function navigateDrive(targetPath) {
  Native.vibrate(15);
  fetchDriveFolder(targetPath);
}

function toggleDriveView() {
  Native.vibrate(15);
  driveViewMode = (driveViewMode === 'grid') ? 'list' : 'grid';
  localStorage.setItem('tx3_drive_view', driveViewMode);
  renderDriveUI();
  Native.toast(`Switched to ${driveViewMode.toUpperCase()} view`);
}

function toggleDriveSort() {
  Native.vibrate(15);
  if (driveSortBy === 'name') {
    driveSortBy = 'date';
    driveSortOrder = 'desc';
    Native.toast('Sorted by Last Modified');
  } else if (driveSortBy === 'date') {
    driveSortBy = 'size';
    driveSortOrder = 'desc';
    Native.toast('Sorted by File Size');
  } else {
    driveSortBy = 'name';
    driveSortOrder = 'asc';
    Native.toast('Sorted by Name (A-Z)');
  }
  fetchDriveFolder();
}

function handleDriveSearch(query) {
  renderDriveUI(query);
}

// FAB Sheet
function openFabSheet() {
  Native.vibrate(20);
  document.getElementById('fabSheetModal').classList.add('active');
}

function closeFabSheet() {
  document.getElementById('fabSheetModal').classList.remove('active');
}

function triggerNewFolder() {
  closeFabSheet();
  setTimeout(async () => {
    const name = prompt('Create New Folder:');
    if (!name || !name.trim()) return;

    Native.vibrate(20);
    Native.toast(`Creating folder "${name.trim()}"...`);

    try {
      const res = await fetch(`${activeBaseUrl}/api/drive/mkdir`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage: currentStorageId, path: driveCurrentPath, name: name.trim() })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        Native.toast('Folder created successfully!');
        fetchDriveFolder();
      } else {
        alert('Failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }, 200);
}

function triggerFileUpload() {
  closeFabSheet();
  setTimeout(() => {
    const input = document.getElementById('driveFileInput');
    if (input) {
      input.value = '';
      input.click();
    }
  }, 100);
}

function triggerMediaUpload() {
  closeFabSheet();
  setTimeout(() => {
    const input = document.getElementById('driveMediaInput');
    if (input) {
      input.value = '';
      input.click();
    }
  }, 100);
}

// Native Upload with Live Streaming Progress
async function handleNativeUpload(files) {
  if (!files || files.length === 0) return;

  const card = document.getElementById('uploadProgressCard');
  const titleEl = document.getElementById('uploadFilename');
  const pctEl = document.getElementById('uploadPct');
  const barEl = document.getElementById('uploadBar');
  const statusEl = document.getElementById('uploadStatusText');

  card.classList.add('active');

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    titleEl.innerText = `[${i + 1}/${files.length}] ${file.name}`;
    pctEl.innerText = '0%';
    barEl.style.width = '0%';
    statusEl.innerText = `Starting upload (${formatBytes(file.size)})...`;

    await uploadSingleFile(file, pctEl, barEl, statusEl);
  }

  Native.vibrate(35);
  Native.toast(`Successfully uploaded ${files.length} file(s)!`);
  setTimeout(() => card.classList.remove('active'), 1200);

  const fileIn = document.getElementById('driveFileInput');
  if (fileIn) fileIn.value = '';
  const mediaIn = document.getElementById('driveMediaInput');
  if (mediaIn) mediaIn.value = '';

  fetchDriveFolder();
}

function uploadSingleFile(file, pctEl, barEl, statusEl) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = `${activeBaseUrl}/api/drive/upload?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(driveCurrentPath)}&filename=${encodeURIComponent(file.name)}`;

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        pctEl.innerText = `${pct}%`;
        barEl.style.width = `${pct}%`;
        statusEl.innerText = `${formatBytes(e.loaded)} of ${formatBytes(e.total)}`;
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200) {
        resolve();
      } else {
        Native.toast(`Upload failed for ${file.name}`);
        resolve();
      }
    };

    xhr.onerror = () => {
      Native.toast(`Connection error uploading ${file.name}`);
      resolve();
    };

    xhr.open('POST', url, true);
    xhr.send(file);
  });
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// 3-Dots Action Sheet
function openItemSheet(item, isFolderItem) {
  Native.vibrate(20);
  selectedDriveItem = item;
  isItemFolder = isFolderItem;

  document.getElementById('itemSheetTitle').innerText = item.name;
  document.getElementById('itemSheetIcon').innerText = isFolderItem ? '📁' : (item.type === 'video' ? '🎬' : (item.type === 'image' ? '🖼️' : '📄'));
  document.getElementById('itemSheetSub').innerText = isFolderItem ? `${item.item_count} items • ${item.date_str}` : `${item.size_str} • ${item.date_str}`;

  const dlBtn = document.getElementById('btnSheetDownload');
  if (dlBtn) dlBtn.style.display = isFolderItem ? 'none' : 'flex';

  document.getElementById('driveItemSheetModal').classList.add('active');
}

function closeItemSheet() {
  document.getElementById('driveItemSheetModal').classList.remove('active');
}

function executeItemDownload() {
  closeItemSheet();
  if (!selectedDriveItem || isItemFolder) return;
  Native.vibrate(20);
  Native.toast(`Downloading ${selectedDriveItem.name}...`);
  const url = `${activeBaseUrl}/api/drive/raw?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(selectedDriveItem.path)}&download=1`;
  Native.openExternal(url);
}

function executeItemRename() {
  closeItemSheet();
  if (!selectedDriveItem) return;
  const current = selectedDriveItem.name;
  setTimeout(async () => {
    const newName = prompt('Rename to:', current);
    if (!newName || !newName.trim() || newName.trim() === current) return;

    Native.vibrate(20);
    Native.toast(`Renaming to "${newName.trim()}"...`);

    try {
      const res = await fetch(`${activeBaseUrl}/api/drive/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage: currentStorageId, path: selectedDriveItem.path, new_name: newName.trim() })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        Native.toast('Renamed successfully!');
        fetchDriveFolder();
      } else {
        alert('Failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }, 200);
}

function executeItemDetails() {
  closeItemSheet();
  if (!selectedDriveItem) return;
  const it = selectedDriveItem;
  const storageName = driveData.storage_name || 'Storage';
  const info = `
📁 Name: ${it.name}
📍 Location: [${storageName}] /${it.path}
📦 Size: ${isItemFolder ? `${it.item_count} items` : it.size_str}
🕒 Modified: ${it.date_str}
  `.trim();
  alert(info);
}

function executeItemDelete() {
  closeItemSheet();
  if (!selectedDriveItem) return;
  const it = selectedDriveItem;
  setTimeout(async () => {
    if (!confirm(`Are you sure you want to delete "${it.name}"?`)) return;

    Native.vibrate(30);
    Native.toast(`Deleting ${it.name}...`);

    try {
      const res = await fetch(`${activeBaseUrl}/api/drive/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage: currentStorageId, path: it.path })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        Native.toast('Deleted successfully!');
        fetchDriveFolder();
      } else {
        alert('Failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }, 200);
}

function openDriveItem(file) {
  Native.vibrate(15);
  if (file.type === 'video') {
    // Open in video modal
    const modal = document.getElementById('videoModal');
    const title = document.getElementById('modalVideoTitle');
    const subtitle = document.getElementById('modalVideoSubtitle');
    const player = document.getElementById('videoPlayer');
    const clipList = document.getElementById('modalClipList');

    title.innerText = file.name;
    subtitle.innerText = `${file.size_str} • Direct Stream`;
    clipList.innerHTML = '';
    player.src = `${activeBaseUrl}/api/drive/raw?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(file.path)}`;
    modal.classList.add('active');
    player.play().catch(() => {});
  } else if (file.type === 'image') {
    // Open in lightbox
    const lb = document.getElementById('photoLightbox');
    document.getElementById('lbTitle').innerText = file.name;
    document.getElementById('lbCounter').innerText = file.size_str;
    const img = document.getElementById('lbImg');
    const vid = document.getElementById('lbVideo');
    vid.style.display = 'none';
    img.style.display = 'block';
    img.src = `${activeBaseUrl}/api/drive/raw?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(file.path)}`;
    lb.classList.add('active');
  } else {
    // Download or open external
    Native.toast(`Opening ${file.name}...`);
    Native.openExternal(`${activeBaseUrl}/api/drive/raw?storage=${encodeURIComponent(currentStorageId)}&path=${encodeURIComponent(file.path)}&download=1`);
  }
}

// ================= ANDROID SYSTEM BACK NAVIGATION =================
window.handleAndroidBack = function() {
  // 0. Close Incoming Quick Share Modal
  const shareModal = document.getElementById('incomingShareModal');
  if (shareModal && shareModal.classList.contains('active')) {
    closeShareModal();
    return true;
  }

  // 1. Close Video Modal
  const vidModal = document.getElementById('videoModal');
  if (vidModal && vidModal.classList.contains('active')) {
    closeVideoModal();
    return true;
  }

  // 2. Close Photo Lightbox
  const lb = document.getElementById('photoLightbox');
  if (lb && lb.classList.contains('active')) {
    closeLightbox();
    return true;
  }

  // 3. Close Settings Modal
  const settingsModal = document.getElementById('settingsModal');
  if (settingsModal && settingsModal.classList.contains('active')) {
    closeSettingsModal();
    return true;
  }

  // 4. Close Drive FAB Action Sheet
  const fabSheet = document.getElementById('fabSheetModal');
  if (fabSheet && fabSheet.classList.contains('active')) {
    closeFabSheet();
    return true;
  }

  // 5. Close Drive File Item Action Sheet
  const itemSheet = document.getElementById('driveItemSheetModal');
  if (itemSheet && itemSheet.classList.contains('active')) {
    closeItemSheet();
    return true;
  }

  // 6. Drive Folder Navigation Hierarchy
  if (activeTab === 'drive') {
    if (driveCurrentPath && driveCurrentPath !== '') {
      const crumbs = driveData.breadcrumbs || [];
      if (crumbs.length > 1) {
        const parentCrumb = crumbs[crumbs.length - 2];
        navigateDrive(parentCrumb.path);
        return true;
      } else {
        navigateDrive('');
        return true;
      }
    } else {
      // At root of Drive -> return to Power & Telemetry tab
      switchTab('power');
      return true;
    }
  }

  // 7. Photos or Dota Tab -> return to Power tab
  if (activeTab === 'photos' || activeTab === 'dota') {
    switchTab('power');
    return true;
  }

  // 8. On Home/Power tab with no modals -> let Android handle double-tap to exit
  return false;
};

// ================= DIRECT QUICK SHARE (ANDROID ACTION_SEND) =================
let incomingShareFiles = [];
let selectedShareStorage = '';

window.handleIncomingShare = function(files) {
  if (!files || files.length === 0) return;
  incomingShareFiles = files;

  const modal = document.getElementById('incomingShareModal');
  const countEl = document.getElementById('incomingShareCount');
  const listEl = document.getElementById('shareFileList');
  const sizeEl = document.getElementById('shareTotalSize');
  const progressCard = document.getElementById('shareProgressCard');
  const btnUpload = document.getElementById('btnUploadShare');
  const btnCancel = document.getElementById('btnCancelShare');

  if (progressCard) progressCard.style.display = 'none';
  if (btnUpload) btnUpload.disabled = false;
  if (btnCancel) btnCancel.disabled = false;

  let totalBytes = 0;
  if (listEl) {
    listEl.innerHTML = '';
    files.forEach(f => {
      totalBytes += (f.size || 0);
      const row = document.createElement('div');
      row.className = 'share-file-row';
      row.innerHTML = `
        <span class="share-file-name" title="${escapeHtml(f.name)}">📄 ${escapeHtml(f.name)}</span>
        <span class="share-file-size">${formatBytes(f.size || 0)}</span>
      `;
      listEl.appendChild(row);
    });
  }

  if (countEl) countEl.innerText = `${files.length} file${files.length > 1 ? 's' : ''} received`;
  if (sizeEl) sizeEl.innerText = formatBytes(totalBytes);

  // Default to active drive folder if available
  const pathInput = document.getElementById('shareFolderPath');
  if (pathInput && (!pathInput.value || pathInput.value === '')) {
    pathInput.value = driveCurrentPath || '/';
  }

  // Render storages chips
  renderShareStorageChips();

  // Show modal
  if (modal) modal.classList.add('active');
  Native.vibrate(35);
};

function renderShareStorageChips() {
  const chipsEl = document.getElementById('shareStorageChips');
  if (!chipsEl) return;
  chipsEl.innerHTML = '';

  const storages = (availableStorages && availableStorages.length > 0)
    ? availableStorages
    : [
        { id: 'pendrive', name: 'Pendrive 128GB', icon: '💾' },
        { id: 'sdcard', name: 'MicroSD 64GB', icon: '🗄️' }
      ];

  if (!selectedShareStorage) {
    selectedShareStorage = currentStorageId || storages[0].id;
  }

  storages.forEach(s => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `share-chip ${s.id === selectedShareStorage ? 'active' : ''}`;
    chip.innerHTML = `<span>${s.icon || '💾'} ${escapeHtml(s.name || s.id)}</span>`;
    chip.onclick = () => {
      selectedShareStorage = s.id;
      renderShareStorageChips();
    };
    chipsEl.appendChild(chip);
  });
}

function useCurrentDriveFolder() {
  const pathInput = document.getElementById('shareFolderPath');
  if (pathInput) {
    pathInput.value = driveCurrentPath || '/';
  }
}

function closeShareModal() {
  const modal = document.getElementById('incomingShareModal');
  if (modal) modal.classList.remove('active');
  incomingShareFiles = [];
  if (window.AndroidBridge && window.AndroidBridge.clearPendingShares) {
    window.AndroidBridge.clearPendingShares();
  }
}

function startShareUpload() {
  if (!incomingShareFiles || incomingShareFiles.length === 0) {
    Native.toast('No files to upload');
    return;
  }

  const targetPath = (document.getElementById('shareFolderPath')?.value || '/').trim();
  const storageId = selectedShareStorage || currentStorageId || 'pendrive';

  const progressCard = document.getElementById('shareProgressCard');
  const btnUpload = document.getElementById('btnUploadShare');
  const btnCancel = document.getElementById('btnCancelShare');

  if (progressCard) progressCard.style.display = 'block';
  if (btnUpload) btnUpload.disabled = true;
  if (btnCancel) btnCancel.disabled = true;

  updateShareUploadProgress(1, incomingShareFiles.length, 0, incomingShareFiles[0]?.size || 0, incomingShareFiles[0]?.name || '');

  if (window.AndroidBridge && window.AndroidBridge.executeShareUpload) {
    window.AndroidBridge.executeShareUpload(activeBaseUrl, storageId, targetPath);
  } else {
    Native.toast('Android Bridge not available');
    if (btnUpload) btnUpload.disabled = false;
    if (btnCancel) btnCancel.disabled = false;
  }
}

window.updateShareUploadProgress = function(currentIndex, totalFiles, bytesSent, totalBytes, filename) {
  const titleEl = document.getElementById('shareProgressTitle');
  const pctEl = document.getElementById('shareProgressPct');
  const barEl = document.getElementById('shareProgressBar');
  const metaEl = document.getElementById('shareProgressMeta');

  let pct = 0;
  if (totalBytes > 0) {
    pct = Math.min(100, Math.round((bytesSent / totalBytes) * 100));
  }

  if (titleEl) titleEl.innerText = `[${currentIndex}/${totalFiles}] ${filename}`;
  if (pctEl) pctEl.innerText = `${pct}%`;
  if (barEl) barEl.style.width = `${pct}%`;
  if (metaEl) metaEl.innerText = `${formatBytes(bytesSent)} of ${formatBytes(totalBytes)}`;
};

window.onShareUploadComplete = function(successCount, failCount) {
  Native.toast(`Uploaded ${successCount} file(s) successfully!`);
  const modal = document.getElementById('incomingShareModal');
  if (modal) modal.classList.remove('active');

  const btnUpload = document.getElementById('btnUploadShare');
  const btnCancel = document.getElementById('btnCancelShare');
  if (btnUpload) btnUpload.disabled = false;
  if (btnCancel) btnCancel.disabled = false;

  // Refresh drive view if user is in drive
  if (typeof fetchDriveFolder === 'function') {
    fetchDriveFolder(driveCurrentPath);
  }
};
