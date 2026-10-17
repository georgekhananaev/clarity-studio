'use strict';
let editorPreferences = {appearance: 'dark', playback_speed: 1, muted: false, caption_size: 22, last_project: null, sidebar_collapsed: false, sidebar_width: 216, preview_share: 0.66, preferences_pane: 'general'};
let preferenceWrites = Promise.resolve(), pendingPreferenceWrites = 0;
const systemAppearance = window.matchMedia('(prefers-color-scheme: dark)');

function applyEditorPreferences() {
  const theme = editorPreferences.appearance === 'system' ? (systemAppearance.matches ? 'dark' : 'light') : editorPreferences.appearance;
  document.documentElement.dataset.theme = theme;
  document.body.classList.toggle('library-collapsed', editorPreferences.sidebar_collapsed);
  $('toggle-library').setAttribute('aria-expanded', String(!editorPreferences.sidebar_collapsed));
  const libraryAction = editorPreferences.sidebar_collapsed ? 'Expand recordings' : 'Collapse recordings';
  $('toggle-library').setAttribute('aria-label', libraryAction);
  $('toggle-library').title = libraryAction;
  applySidebarWidth(sidebarDrag ? sidebarDrag.width : editorPreferences.sidebar_width);
  applyPreviewShare(editorPreferences.preview_share);
  document.documentElement.style.setProperty('--caption-size', `${editorPreferences.caption_size}px`);
  document.querySelectorAll('[data-appearance]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.appearance === editorPreferences.appearance)));
  $('speed').value = String(editorPreferences.playback_speed);
  $('preference-speed').value = String(editorPreferences.playback_speed);
  $('preference-caption-size').value = String(editorPreferences.caption_size);
  video.playbackRate = editorPreferences.playback_speed;
  video.muted = editorPreferences.muted;
  $('mute-button').textContent = video.muted ? '× ♪' : '♪';
  $('mute-button').setAttribute('aria-label', video.muted ? 'Unmute audio' : 'Mute audio');
  $('mute-button').setAttribute('aria-pressed', String(video.muted));
  if (editorPreferences.storage) {
    $('preferences-database').textContent = editorPreferences.storage.database;
    $('preferences-projects').textContent = editorPreferences.storage.projects;
  }
}

async function loadEditorPreferences() {
  editorPreferences = {...editorPreferences, ...await api('/api/preferences')};
  applyEditorPreferences();
}

function saveEditorPreferences(patch) {
  editorPreferences = {...editorPreferences, ...patch};
  applyEditorPreferences();
  pendingPreferenceWrites++;
  $('preferences-status').textContent = 'Saving preferences…';
  const write = preferenceWrites.catch(() => {}).then(async () => {
    const saved = await api('/api/preferences', jsonRequest('PUT', patch));
    editorPreferences.storage = saved.storage;
  });
  preferenceWrites = write;
  return write.then(() => {
    pendingPreferenceWrites--;
    if (!pendingPreferenceWrites) $('preferences-status').textContent = 'Saved on this Mac.';
  }, error => {
    pendingPreferenceWrites--;
    $('preferences-status').textContent = 'Could not save. Try changing the setting again.';
    throw error;
  });
}

systemAppearance.addEventListener('change', applyEditorPreferences);
async function selectPreferencesPane(pane, remember = true) {
  if (!['general', 'integrations'].includes(pane)) pane = 'general';
  document.querySelectorAll('[data-preferences-pane]').forEach(button => {
    const active = button.dataset.preferencesPane === pane;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $('preferences-general').hidden = pane !== 'general';
  $('preferences-integrations').hidden = pane !== 'integrations';
  $('preferences-title').textContent = pane === 'integrations' ? 'Preferences · Integrations' : 'Preferences';
  if (remember && editorPreferences.preferences_pane !== pane) {
    saveEditorPreferences({preferences_pane: pane}).catch(error => toast(error.message, true));
  }
  if (pane === 'integrations') {
    try { await openSpeechIntegrations(); }
    catch (error) { $('connection-feedback').textContent = error.message; }
  }
}

async function openPreferences(pane = editorPreferences.preferences_pane) {
  if ($('voice-dialog').open) $('voice-dialog').close();
  applyEditorPreferences();
  if (!$('preferences-dialog').open) $('preferences-dialog').showModal();
  $('preferences-button').setAttribute('aria-expanded', 'true');
  await selectPreferencesPane(pane || 'general', false);
}

$('preferences-button').onclick = () => openPreferences();
$('preferences-dialog').addEventListener('close', () => { $('speech-api-key').value = ''; $('preferences-button').setAttribute('aria-expanded', 'false'); });
document.querySelectorAll('[data-preferences-pane]').forEach(button => {
  button.onclick = () => selectPreferencesPane(button.dataset.preferencesPane);
  button.onkeydown = event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const pane = event.key === 'Home' ? 'general' : event.key === 'End' ? 'integrations' : button.dataset.preferencesPane === 'general' ? 'integrations' : 'general';
    $('preferences-tab-' + pane).focus();
    selectPreferencesPane(pane);
  };
});
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === ',') { event.preventDefault(); openPreferences(); }
});
$('toggle-library').onclick = () => saveEditorPreferences({sidebar_collapsed: !editorPreferences.sidebar_collapsed}).catch(error => toast(error.message, true));

// Keep the user's saved width while fitting smaller windows without overwriting it.
let sidebarDrag = null;
const sidebarResizer = $('sidebar-resizer');
function sidebarWidthLimit() {
  return Math.max(168, Math.min(360, window.innerWidth - 760));
}
function applySidebarWidth(value) {
  const width = Math.round(Math.min(sidebarWidthLimit(), Math.max(168, Number(value) || 216)));
  document.documentElement.style.setProperty('--library-width', `${width}px`);
  sidebarResizer.setAttribute('aria-valuemax', String(sidebarWidthLimit()));
  sidebarResizer.setAttribute('aria-valuenow', String(width));
  sidebarResizer.setAttribute('aria-valuetext', `${width} pixels`);
  const available = !editorPreferences.sidebar_collapsed && window.innerWidth > 600;
  sidebarResizer.hidden = !available;
  sidebarResizer.tabIndex = available ? 0 : -1;
  return width;
}
function cancelSidebarResize() {
  if (!sidebarDrag) return;
  const pointerId = sidebarDrag.pointerId;
  sidebarDrag = null;
  document.body.classList.remove('resizing-sidebar');
  if (sidebarResizer.hasPointerCapture(pointerId)) sidebarResizer.releasePointerCapture(pointerId);
  applySidebarWidth(editorPreferences.sidebar_width);
}
sidebarResizer.onpointerdown = event => {
  if (event.button !== 0 || editorPreferences.sidebar_collapsed || window.innerWidth <= 600) return;
  event.preventDefault();
  sidebarResizer.focus({preventScroll: true});
  sidebarDrag = {pointerId: event.pointerId, width: applySidebarWidth(editorPreferences.sidebar_width)};
  sidebarResizer.setPointerCapture(event.pointerId);
  document.body.classList.add('resizing-sidebar');
};
sidebarResizer.onpointermove = event => {
  if (!sidebarDrag || sidebarDrag.pointerId !== event.pointerId) return;
  sidebarDrag.width = applySidebarWidth(event.clientX - $('recordings-sidebar').getBoundingClientRect().left);
};
sidebarResizer.onpointerup = event => {
  if (!sidebarDrag || sidebarDrag.pointerId !== event.pointerId) return;
  const width = sidebarDrag.width;
  sidebarDrag = null;
  document.body.classList.remove('resizing-sidebar');
  if (sidebarResizer.hasPointerCapture(event.pointerId)) sidebarResizer.releasePointerCapture(event.pointerId);
  saveEditorPreferences({sidebar_width: width}).catch(error => toast(error.message, true));
};
sidebarResizer.onpointercancel = sidebarResizer.onlostpointercapture = cancelSidebarResize;
sidebarResizer.ondblclick = () => saveEditorPreferences({sidebar_width: 216}).catch(error => toast(error.message, true));
sidebarResizer.onkeydown = event => {
  if (event.key === 'Escape' && sidebarDrag) { event.preventDefault(); event.stopPropagation(); cancelSidebarResize(); return; }
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  event.stopPropagation();
  const current = sidebarDrag ? sidebarDrag.width : Number(sidebarResizer.getAttribute('aria-valuenow'));
  cancelSidebarResize();
  const width = event.key === 'Home' ? 168 : event.key === 'End' ? sidebarWidthLimit() : current + (event.key === 'ArrowRight' ? 16 : -16);
  saveEditorPreferences({sidebar_width: applySidebarWidth(width)}).catch(error => toast(error.message, true));
};
window.addEventListener('resize', () => { cancelSidebarResize(); applySidebarWidth(editorPreferences.sidebar_width); });
window.addEventListener('blur', cancelSidebarResize);

function applyPreviewShare(value) {
  const share = Math.min(0.75, Math.max(0.5, Number(value) || 0.66));
  document.documentElement.style.setProperty('--preview-ratio', `${share / (1 - share)}fr`);
  $('editor-splitter').setAttribute('aria-valuenow', String(Math.round(share * 100)));
  $('editor-splitter').setAttribute('aria-valuetext', `${Math.round(share * 100)}% video preview`);
  return share;
}
let resizingPanels = false, shareBeforeResize = 0.66;
const splitter = $('editor-splitter');
splitter.onpointerdown = event => {
  if (event.button !== 0) return;
  event.preventDefault();
  shareBeforeResize = editorPreferences.preview_share;
  resizingPanels = true;
  splitter.setPointerCapture(event.pointerId);
  document.body.classList.add('resizing');
};
splitter.onpointermove = event => {
  if (!resizingPanels) return;
  const box = document.querySelector('.editor-grid').getBoundingClientRect();
  editorPreferences.preview_share = applyPreviewShare((event.clientX - box.left) / box.width);
};
splitter.onpointerup = event => {
  if (!resizingPanels) return;
  resizingPanels = false;
  document.body.classList.remove('resizing');
  splitter.releasePointerCapture(event.pointerId);
  saveEditorPreferences({preview_share: editorPreferences.preview_share}).catch(error => toast(error.message, true));
};
splitter.onpointercancel = () => {
  resizingPanels = false;
  document.body.classList.remove('resizing');
  editorPreferences.preview_share = applyPreviewShare(shareBeforeResize);
};
splitter.onkeydown = event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const share = event.key === 'Home' ? 0.5 : event.key === 'End' ? 0.75 : editorPreferences.preview_share + (event.key === 'ArrowRight' ? 0.02 : -0.02);
  saveEditorPreferences({preview_share: applyPreviewShare(share)}).catch(error => toast(error.message, true));
};
document.querySelectorAll('[data-appearance]').forEach(button => button.onclick = () => saveEditorPreferences({appearance: button.dataset.appearance}).catch(error => toast(error.message, true)));
$('preference-speed').onchange = event => saveEditorPreferences({playback_speed: Number(event.target.value)}).catch(error => toast(error.message, true));
$('preference-caption-size').onchange = event => saveEditorPreferences({caption_size: Number(event.target.value)}).catch(error => toast(error.message, true));
