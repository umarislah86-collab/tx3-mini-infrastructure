// ================= TX3 POCKETBOARD APP =================
// Connect to PocketBase on current origin (LAN 192.168.100.232:8090 or Cloud https://pb.umiaq.top)
const pbUrl = window.location.origin.includes('8090') || window.location.origin.includes('pb.umiaq.top')
  ? window.location.origin
  : 'http://192.168.100.232:8090';

const pb = new PocketBase(pbUrl);

// Application State
let allNotes = [];
let activeCategory = 'All';
let searchQuery = '';
let selectedAttachmentFile = null;
let currentAuthMode = 'login'; // 'login' or 'register'

// DOM Elements
const notesGrid = document.getElementById('notesGrid');
const sseDot = document.getElementById('sseDot');
const sseText = document.getElementById('sseText');
const realtimeToast = document.getElementById('realtimeToast');
const toastMsg = document.getElementById('toastMsg');
const countAll = document.getElementById('countAll');

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
  setupKeyboardShortcuts();
  updateUserUI();
  fetchNotes();
  initRealtimeSubscription();
});

// ================= REALTIME SSE SUBSCRIPTION =================
async function initRealtimeSubscription() {
  try {
    setConnectionStatus('connecting', 'Connecting SSE stream...');

    await pb.collection('notes').subscribe('*', function (e) {
      handleRealtimeEvent(e);
    });

    setConnectionStatus('connected', '⚡ Realtime SSE Live');
  } catch (err) {
    console.warn('Realtime subscription issue:', err);
    setConnectionStatus('offline', 'Realtime reconnecting...');
    // Retry in 4s
    setTimeout(initRealtimeSubscription, 4000);
  }
}

function setConnectionStatus(status, text) {
  sseDot.className = 'status-dot';
  if (status === 'connected') {
    sseDot.classList.add('dot-connected');
  } else if (status === 'connecting') {
    sseDot.classList.add('dot-connecting');
  } else {
    sseDot.classList.add('dot-offline');
  }
  sseText.innerText = text;
}

function handleRealtimeEvent(e) {
  const { action, record } = e;

  if (action === 'create') {
    // Avoid duplicate if already inserted
    if (!allNotes.some(n => n.id === record.id)) {
      allNotes.unshift(record);
      showRealtimeToast(`⚡ Added note: "${record.title}"`);
    }
  } else if (action === 'update') {
    const idx = allNotes.findIndex(n => n.id === record.id);
    if (idx !== -1) {
      allNotes[idx] = record;
      showRealtimeToast(`✏️ Updated: "${record.title}"`);
    } else {
      allNotes.unshift(record);
    }
  } else if (action === 'delete') {
    allNotes = allNotes.filter(n => n.id !== record.id);
    showRealtimeToast(`🗑️ Note deleted`);
  }

  renderNotes();
}

let toastTimer = null;
function showRealtimeToast(msg) {
  if (toastTimer) clearTimeout(toastTimer);
  toastMsg.innerText = msg;
  realtimeToast.classList.add('active');
  toastTimer = setTimeout(() => {
    realtimeToast.classList.remove('active');
  }, 2800);
}

// ================= FETCH & RENDER NOTES =================
async function fetchNotes() {
  try {
    // Sort by pinned descending, then created descending
    const records = await pb.collection('notes').getFullList({
      sort: '-pinned,-created',
      requestKey: null
    });
    allNotes = records;
    renderNotes();
  } catch (err) {
    console.error('Failed to load notes:', err);
    notesGrid.innerHTML = `
      <div class="empty-state">
        <p>Gagal memuatkan nota dari PocketBase: ${escapeHtml(err.message)}</p>
        <button class="filter-chip" style="margin-top:12px;" onclick="fetchNotes()">Cuba Semula</button>
      </div>
    `;
  }
}

function renderNotes() {
  // Update counts
  if (countAll) countAll.innerText = allNotes.length;

  // Filter notes
  const filtered = allNotes.filter(n => {
    const matchesCat = (activeCategory === 'All') || (n.category === activeCategory);
    const q = searchQuery.toLowerCase().trim();
    const matchesQuery = !q ||
      (n.title && n.title.toLowerCase().includes(q)) ||
      (n.content && n.content.toLowerCase().includes(q)) ||
      (n.author && n.author.toLowerCase().includes(q));
    return matchesCat && matchesQuery;
  });

  // Sort pinned to top
  filtered.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    return new Date(b.created) - new Date(a.created);
  });

  if (filtered.length === 0) {
    notesGrid.innerHTML = `
      <div class="empty-state">
        <div style="font-size: 38px; margin-bottom: 8px;">📝</div>
        <h3>Tiada Nota Dijumpai</h3>
        <p style="margin-top:4px; font-size:12px;">Cipta nota pertama di atas untuk test realtime PocketBase!</p>
      </div>
    `;
    return;
  }

  notesGrid.innerHTML = filtered.map(note => {
    const colorClass = note.color && note.color !== 'slate' ? `card-${note.color}` : '';
    const pinnedClass = note.pinned ? 'pinned' : '';
    const dateFormatted = formatTimeAgo(note.created);
    const authorName = escapeHtml(note.author || 'Guest');

    // Attachment rendering
    let attachmentHtml = '';
    if (note.attachment) {
      const fileUrl = `${pb.baseUrl}/api/files/${note.collectionId}/${note.id}/${encodeURIComponent(note.attachment)}`;
      const thumbUrl = `${fileUrl}?thumb=400x300`;
      const isImg = isImageFile(note.attachment);

      if (isImg) {
        attachmentHtml = `
          <div class="note-attachment-wrap">
            <img class="note-attachment-img" src="${thumbUrl}" alt="Attachment" loading="lazy" onclick="openLightbox('${fileUrl}')">
          </div>
        `;
      } else {
        attachmentHtml = `
          <div class="note-attachment-wrap">
            <a href="${fileUrl}" target="_blank" class="note-attachment-file" download>
              <span>📄</span>
              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(note.attachment)}</span>
            </a>
          </div>
        `;
      }
    }

    return `
      <article class="note-card ${colorClass} ${pinnedClass}" id="card-${note.id}">
        <div>
          <div class="note-card-header">
            <span class="note-category-badge">${escapeHtml(note.category || 'General')}</span>
            <div class="note-card-actions">
              <button class="btn-card-icon ${note.pinned ? 'pinned-active' : ''}" onclick="togglePin('${note.id}', ${!note.pinned})" title="${note.pinned ? 'Unpin' : 'Pin to top'}">
                📌
              </button>
              <button class="btn-card-icon delete" onclick="deleteNote('${note.id}')" title="Delete note">
                ✕
              </button>
            </div>
          </div>

          <h3 class="note-title">${escapeHtml(note.title)}</h3>
          ${note.content ? `<p class="note-content">${escapeHtml(note.content)}</p>` : ''}
          ${attachmentHtml}
        </div>

        <div class="note-card-footer">
          <span class="note-author">👤 ${authorName}</span>
          <span title="${new Date(note.created).toLocaleString()}">${dateFormatted}</span>
        </div>
      </article>
    `;
  }).join('');
}

// ================= NOTE ACTIONS (CRUD) =================
async function handleCreateNote(e) {
  e.preventDefault();
  const btn = document.getElementById('btnSubmit');
  const titleInput = document.getElementById('noteTitle');
  const contentInput = document.getElementById('noteContent');
  const categorySelect = document.getElementById('noteCategory');
  const pinnedCheckbox = document.getElementById('notePinned');
  const colorInput = document.querySelector('input[name="noteColor"]:checked');

  const title = titleInput.value.trim();
  if (!title) return;

  const content = contentInput.value.trim();
  const category = categorySelect.value;
  const pinned = pinnedCheckbox.checked;
  const color = colorInput ? colorInput.value : 'slate';

  // Author identity
  let author = 'Guest';
  if (pb.authStore.isValid && pb.authStore.record) {
    author = pb.authStore.record.name || pb.authStore.record.email.split('@')[0];
  }

  btn.disabled = true;
  btn.innerText = 'Posting...';

  try {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('content', content);
    formData.append('category', category);
    formData.append('pinned', pinned);
    formData.append('color', color);
    formData.append('author', author);

    if (selectedAttachmentFile) {
      formData.append('attachment', selectedAttachmentFile);
    }

    await pb.collection('notes').create(formData);

    // Reset Form
    titleInput.value = '';
    contentInput.value = '';
    pinnedCheckbox.checked = false;
    document.querySelector('.pin-toggle').classList.remove('active');
    clearAttachment();

    // Default to slate color
    document.querySelector('input[name="noteColor"][value="slate"]').checked = true;
    updateColorDots();
  } catch (err) {
    alert(`Error creating note: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg viewBox="0 0 24 24" class="btn-send-icon"><path fill="currentColor" d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      <span>Post to TX3</span>
    `;
  }
}

async function togglePin(noteId, newPinnedState) {
  try {
    await pb.collection('notes').update(noteId, { pinned: newPinnedState });
  } catch (err) {
    console.error('Failed to toggle pin:', err);
  }
}

async function deleteNote(noteId) {
  if (!confirm('Padam nota ini dari PocketBase?')) return;
  try {
    await pb.collection('notes').delete(noteId);
  } catch (err) {
    alert(`Gagal memadam nota: ${err.message}`);
  }
}

// ================= ATTACHMENT HANDLER =================
function handleFileSelected(e) {
  const file = e.target.files[0];
  if (!file) return;

  if (file.size > 10 * 1024 * 1024) {
    alert('Saiz fail melebihi had 10MB.');
    e.target.value = '';
    return;
  }

  selectedAttachmentFile = file;
  const box = document.getElementById('attachmentPreviewBox');
  const nameEl = document.getElementById('previewFilename');
  const sizeEl = document.getElementById('previewSize');
  const iconEl = document.getElementById('previewIcon');

  nameEl.innerText = file.name;
  sizeEl.innerText = `(${formatBytes(file.size)})`;
  iconEl.innerText = isImageFile(file.name) ? '🖼️' : '📄';
  box.style.display = 'flex';
}

function clearAttachment() {
  selectedAttachmentFile = null;
  const fileInput = document.getElementById('noteFile');
  if (fileInput) fileInput.value = '';
  const box = document.getElementById('attachmentPreviewBox');
  if (box) box.style.display = 'none';
}

function isImageFile(filename) {
  return /\.(jpe?g|png|webp|gif|svg)$/i.test(filename || '');
}

// ================= FILTER & SEARCH =================
function setCategoryFilter(category) {
  activeCategory = category;
  const chips = document.querySelectorAll('.filter-chip');
  chips.forEach(c => {
    if (c.innerText.includes(category)) {
      c.classList.add('active');
    } else {
      c.classList.remove('active');
    }
  });
  renderNotes();
}

function handleSearch(val) {
  searchQuery = val;
  renderNotes();
}

// ================= COLOR PICKER & PIN TOGGLE =================
document.querySelectorAll('input[name="noteColor"]').forEach(radio => {
  radio.addEventListener('change', updateColorDots);
});

function updateColorDots() {
  document.querySelectorAll('.color-dot').forEach(dot => {
    const radio = dot.querySelector('input');
    if (radio && radio.checked) {
      dot.classList.add('active');
    } else {
      dot.classList.remove('active');
    }
  });
}

const pinInput = document.getElementById('notePinned');
if (pinInput) {
  pinInput.addEventListener('change', (e) => {
    e.target.closest('.pin-toggle').classList.toggle('active', e.target.checked);
  });
}

// ================= AUTH MODAL & POCKETBASE USERS =================
function openAuthModal() {
  const modal = document.getElementById('authModal');
  const msgBox = document.getElementById('authMsgBox');
  if (msgBox) msgBox.style.display = 'none';

  if (pb.authStore.isValid && pb.authStore.record) {
    document.getElementById('authForm').style.display = 'none';
    document.querySelector('.modal-tabs').style.display = 'none';
    const activeCard = document.getElementById('userActiveCard');
    activeCard.style.display = 'block';
    document.getElementById('profileName').innerText = pb.authStore.record.name || 'Member';
    document.getElementById('profileEmail').innerText = pb.authStore.record.email;
  } else {
    document.getElementById('authForm').style.display = 'block';
    document.querySelector('.modal-tabs').style.display = 'flex';
    document.getElementById('userActiveCard').style.display = 'none';
    switchAuthMode(currentAuthMode);
  }

  modal.classList.add('active');
}

function closeAuthModal() {
  document.getElementById('authModal').classList.remove('active');
}

function switchAuthMode(mode) {
  currentAuthMode = mode;
  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');
  const groupName = document.getElementById('groupName');
  const groupConfirm = document.getElementById('groupPasswordConfirm');
  const btn = document.getElementById('btnAuthSubmit');
  const title = document.getElementById('authModalTitle');

  if (mode === 'login') {
    tabLogin.classList.add('active');
    tabRegister.classList.remove('active');
    groupName.style.display = 'none';
    groupConfirm.style.display = 'none';
    btn.innerText = 'Sign In';
    title.innerText = 'Login to PocketBase';
  } else {
    tabLogin.classList.remove('active');
    tabRegister.classList.add('active');
    groupName.style.display = 'block';
    groupConfirm.style.display = 'block';
    btn.innerText = 'Create Account';
    title.innerText = 'Create PocketBase User';
  }
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const email = document.getElementById('authEmail').value.trim();
  const password = document.getElementById('authPassword').value;
  const msgBox = document.getElementById('authMsgBox');
  const btn = document.getElementById('btnAuthSubmit');

  msgBox.style.display = 'none';
  btn.disabled = true;

  try {
    if (currentAuthMode === 'login') {
      await pb.collection('users').authWithPassword(email, password);
      msgBox.className = 'auth-msg-box success';
      msgBox.innerText = 'Berjaya log masuk!';
      msgBox.style.display = 'block';
      setTimeout(() => {
        closeAuthModal();
        updateUserUI();
      }, 700);
    } else {
      const name = document.getElementById('authName').value.trim();
      const confirmPass = document.getElementById('authPasswordConfirm').value;
      if (password !== confirmPass) {
        throw new Error('Kata laluan pengesahan tidak sepadan.');
      }

      await pb.collection('users').create({
        email: email,
        password: password,
        passwordConfirm: confirmPass,
        name: name
      });

      // Auto login after register
      await pb.collection('users').authWithPassword(email, password);
      msgBox.className = 'auth-msg-box success';
      msgBox.innerText = 'Akaun berjaya dicipta & log masuk!';
      msgBox.style.display = 'block';
      setTimeout(() => {
        closeAuthModal();
        updateUserUI();
      }, 700);
    }
  } catch (err) {
    msgBox.className = 'auth-msg-box error';
    msgBox.innerText = err.message || 'Ralat log masuk';
    msgBox.style.display = 'block';
  } finally {
    btn.disabled = false;
  }
}

function handleLogout() {
  pb.authStore.clear();
  updateUserUI();
  closeAuthModal();
  showRealtimeToast('Logged out of PocketBase');
}

function updateUserUI() {
  const pillBtn = document.getElementById('userDisplayName');
  const avatarIcon = document.getElementById('userAvatarIcon');

  if (pb.authStore.isValid && pb.authStore.record) {
    const user = pb.authStore.record;
    pillBtn.innerText = user.name || user.email.split('@')[0];
    avatarIcon.innerText = '🟢';
  } else {
    pillBtn.innerText = 'Guest Mode';
    avatarIcon.innerText = '👤';
  }
}

// ================= LIGHTBOX =================
function openLightbox(imgUrl) {
  const lb = document.getElementById('imageLightbox');
  const img = document.getElementById('lbImage');
  img.src = imgUrl;
  lb.classList.add('active');
}

function closeLightbox() {
  document.getElementById('imageLightbox').classList.remove('active');
}

// ================= HELPER FUNCTIONS =================
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return 'Just now';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return 'Recently';
  const now = new Date();
  const diffSec = Math.floor((now - date) / 1000);

  if (diffSec < 45) return 'Just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
  return date.toLocaleDateString();
}

function setupKeyboardShortcuts() {
  const contentInput = document.getElementById('noteContent');
  const titleInput = document.getElementById('noteTitle');

  const handleKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('noteForm').requestSubmit();
    }
  };

  if (contentInput) contentInput.addEventListener('keydown', handleKey);
  if (titleInput) titleInput.addEventListener('keydown', handleKey);
}
