'use strict';
const $ = id => document.getElementById(id);
let project = null, selectedId = null, dirty = false, editVersion = 0, saving = null, jobActive = false, health = {};
let toastTimer;
const video = $('video');

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  if ($('toast').showPopover && !$('toast').matches(':popover-open')) $('toast').showPopover();
  toastTimer = setTimeout(() => {
    if ($('toast').hidePopover && $('toast').matches(':popover-open')) $('toast').hidePopover();
    $('toast').hidden = true;
  }, error ? 9000 : 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    const message = Array.isArray(result.detail) ? result.detail.map(e => e.msg).join('; ') : result.detail;
    throw new Error(message || `Request failed (${response.status}).`);
  }
  return response.json();
}
const jsonRequest = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const base = id => `/api/projects/${encodeURIComponent(id || project.id)}`;
const currentCue = () => project?.cues.find(c => c.id === selectedId);
function clock(value, tenths = false) {
  value = Math.max(0, Number(value) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor(value / 60) % 60;
  const secs = Math.floor(value % 60).toString().padStart(2, '0');
  return `${hours ? String(hours).padStart(2, '0') + ':' : ''}${String(minutes).padStart(2, '0')}:${secs}${tenths ? '.' + Math.floor(value * 10 % 10) : ''}`;
}
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function markDirty() {
  dirty = true; editVersion++;
  $('save-state').textContent = 'Unsaved changes';
  $('save-state').classList.remove('warning');
  $('save-button').disabled = false;
}
function localError() {
  const sorted = [...project.cues].sort((a, b) => a.start - b.start);
  for (let i = 0; i < sorted.length; i++) {
    const c = sorted[i];
    if (!c.text.trim()) return 'Write text for each caption before saving.';
    if (!Number.isFinite(c.start) || !Number.isFinite(c.end) || c.start < 0 || c.end <= c.start) return 'Each caption needs an end time after its start.';
    if (c.end > project.video.duration + 0.001) return 'A caption ends beyond the recording.';
    if (i && c.start < sorted[i - 1].end) return 'Captions overlap. Adjust their start or end times.';
  }
  if (!$('project-title').value.trim()) return 'Give the recording a title.';
  return null;
}
async function save() {
  if (saving) {
    await saving;
    return dirty ? save() : true;
  }
  if (!project || !dirty) return true;
  const problem = localError();
  if (problem) { toast(problem, true); return false; }
  const sentVersion = editVersion, id = project.id;
  $('save-state').textContent = 'Saving…';
  saving = (async () => {
    try {
      const result = await api(base(id) + '/cues', jsonRequest('PUT', {revision: project.revision, title: $('project-title').value, cues: project.cues.map(({id, start, end, text}) => ({id, start, end, text}))}));
      if (project.id !== id) return true;
      if (editVersion === sentVersion) {
        project = result; dirty = false;
        $('save-state').textContent = 'All changes saved';
        $('save-button').disabled = true;
        renderCues(); renderEditor(); renderTimeline();
      } else {
        project.revision = result.revision;
        $('save-state').textContent = 'Unsaved changes';
      }
      $('revision-label').textContent = `REVISION ${String(result.revision).padStart(3, '0')} · SAVED LOCALLY`;
      await loadLibrary();
      return !dirty;
    } catch (error) {
      $('save-state').textContent = 'Save needs attention';
      $('save-state').classList.add('warning');
      toast(error.message, true);
      return false;
    } finally { saving = null; }
  })();
  return saving;
}

let libraryProjects = [];
async function loadLibrary() {
  libraryProjects = await api('/api/projects');
  renderLibrary();
  return libraryProjects;
}
function renderLibrary() {
  const query = $('project-filter').value.trim().toLocaleLowerCase();
  const projects = libraryProjects.filter(p => p.title.toLocaleLowerCase().includes(query));
  $('project-list').replaceChildren();
  $('project-list').classList.toggle('is-empty', projects.length === 0);
  $('project-count').textContent = String(libraryProjects.length);
  for (const p of projects) {
    const button = node('button', 'project-item' + (project?.id === p.id ? ' active' : ''));
    if (project?.id === p.id) button.setAttribute('aria-current', 'true');
    button.title = p.title;
    button.setAttribute('aria-label', `${p.title}, ${p.cue_count} captions`);
    const icon = node('span', 'recording-icon');
    icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 9 5 3-5 3V9Z" stroke-linejoin="round"/></svg>';
    button.append(icon);
    const content = node('span', 'recording-details');
    content.append(node('strong', '', p.title), node('small', '', `${clock(p.duration)}  ·  ${p.cue_count} captions`));
    button.append(content);
    button.addEventListener('click', () => openProject(p.id).catch(e => toast(e.message, true)));
    $('project-list').append(button);
  }
  if (!projects.length) {
    const empty = node('div', 'library-empty');
    empty.setAttribute('role', 'status');
    empty.append(node('strong', '', query ? 'No matching recordings' : 'Your recordings go here'), node('span', '', query ? 'Try a different title.' : 'Add a video to get started.'));
    if (query) {
      const clear = node('button', 'text-button', 'Clear search');
      clear.onclick = () => { $('project-filter').value = ''; renderLibrary(); $('project-filter').focus(); };
      empty.append(clear);
    }
    $('project-list').append(empty);
  }
}
$('project-filter').addEventListener('input', renderLibrary);

async function openProject(id) {
  if (dirty && !await save()) return;
  video.pause();
  project = await api(base(id));
  saveEditorPreferences({last_project: id}).catch(e => toast('Could not remember the last recording. ' + e.message, true));
  selectedId = project.cues[0]?.id || null;
  dirty = false;
  $('empty').hidden = true; $('workspace').hidden = false;
  $('project-heading').hidden = $('project-actions').hidden = false;
  $('workspace-name').hidden = true;
  $('project-title').value = project.title;
  $('video-meta').textContent = `${project.video.width} × ${project.video.height} · ${clock(project.video.duration)} · ${project.video.name}`;
  $('video-meta').title = $('video-meta').textContent;
  $('save-state').textContent = 'All changes saved';
  $('save-state').classList.remove('warning');
  $('save-button').disabled = true;
  $('revision-label').textContent = `REVISION ${String(project.revision).padStart(3, '0')} · SAVED LOCALLY`;
  $('scrubber').max = project.video.duration;
  $('scrubber').value = 0;
  $('media-error').hidden = true;
  video.src = project.preview_available ? base() + '/files/preview.mp4' : base() + '/media';
  video.load();
  renderCues(); renderEditor(); renderTimeline(); updatePlayback();
  await loadLibrary();
}

function selectCue(id, seek = true) {
  selectedId = id;
  const cue = currentCue();
  if (cue && seek) video.currentTime = cue.start;
  renderCues(); renderEditor(); renderTimeline(); updatePlayback();
}
function renderCues() {
  const list = $('cue-list'); list.replaceChildren();
  const sorted = [...project.cues].sort((a,b) => a.start - b.start);
  $('cue-count').textContent = sorted.length;
  if (!sorted.length) {
    const empty = node('div', 'cue-empty');
    empty.append(node('strong', '', 'Every good explanation starts somewhere.'), node('span', '', 'Play your recording and press N to add a caption. Or prepare frames for your AI to inspect.'));
    list.append(empty);
  }
  sorted.forEach((cue, index) => {
    const button = node('button', 'cue-row' + (cue.id === selectedId ? ' active' : ''));
    button.setAttribute('aria-pressed', String(cue.id === selectedId));
    button.append(node('span', 'cue-number', String(index + 1).padStart(2, '0')));
    const content = node('div', 'cue-content');
    content.append(node('div', 'cue-time', `${clock(cue.start, true)}  →  ${clock(cue.end, true)}`), node('div', 'cue-copy', cue.text || 'Write your explanation…'));
    button.append(content);
    button.addEventListener('click', () => selectCue(cue.id));
    list.append(button);
  });
}
function renderEditor() {
  const cue = currentCue();
  $('cue-editor').hidden = !cue;
  if (!cue) return;
  const sorted = [...project.cues].sort((a,b) => a.start - b.start);
  $('editing-label').textContent = `EDIT CAPTION ${String(sorted.findIndex(c => c.id === cue.id) + 1).padStart(2, '0')}`;
  $('cue-text').value = cue.text;
  $('cue-start').value = cue.start;
  $('cue-end').value = cue.end;
  updateQuality();
}
function updateQuality() {
  const cue = currentCue(); if (!cue) return;
  const duration = cue.end - cue.start;
  const rate = duration > 0 ? Math.round(cue.text.replaceAll('\n', '').length / duration) : 0;
  const problem = localError();
  $('cue-quality').textContent = problem || `${duration.toFixed(1)} sec · ${rate} characters / sec${rate > 22 ? ' · Try a shorter explanation' : ' · Comfortable pacing'}`;
  $('cue-quality').classList.toggle('warning', !!problem || rate > 22);
  const narration = project.narration?.find(n => n.cue_id === cue.id);
  const status = dirty ? 'Check after saving' : narration?.status;
  $('cue-voice').replaceChildren();
  if (status === 'ready' || status === 'overflow') {
    $('cue-voice').append(node('span', status === 'overflow' ? 'warning' : '', `Voice: ${narration.duration.toFixed(2)} sec${status === 'overflow' ? ' — too long for this caption' : ' · Fits this caption'} `));
    const listen = node('button', 'text-button', 'Listen ↗');
    listen.addEventListener('click', () => {
      const audio = new Audio(base() + '/files/narration/' + encodeURIComponent(narration.file));
      audio.play().catch(e => toast(e.message, true));
    });
    $('cue-voice').append(listen);
  } else if (status === 'stale') $('cue-voice').textContent = 'Voice is outdated. Regenerate after editing the text.';
}
function renderTimeline() {
  $('ruler').replaceChildren();
  for (let i = 0; i <= 5; i++) $('ruler').append(node('span', '', clock(project.video.duration * i / 5)));
  $('timeline-cues').replaceChildren();
  project.cues.forEach((cue, index) => {
    const button = node('button', 'timeline-cue' + (cue.id === selectedId ? ' active' : ''), cue.text || `Caption ${index + 1}`);
    button.style.left = `${cue.start / project.video.duration * 100}%`;
    button.style.width = `${Math.max(0, cue.end - cue.start) / project.video.duration * 100}%`;
    button.title = `${clock(cue.start, true)} — ${cue.text}`;
    button.setAttribute('aria-label', `Caption ${index + 1}: ${cue.text}`);
    button.addEventListener('click', event => { event.stopPropagation(); selectCue(cue.id); });
    $('timeline-cues').append(button);
  });
  updatePlayback();
}
function updatePlayback() {
  if (!project) return;
  const time = video.currentTime || 0;
  $('timecode').replaceChildren(document.createTextNode(clock(time, true)), node('span', '', '/ ' + clock(project.video.duration, true)));
  $('scrubber').value = time;
  $('playhead').style.left = `${Math.min(100, time / project.video.duration * 100)}%`;
  const cue = project.cues.find(c => c.start <= time && c.end > time);
  $('caption-overlay').textContent = cue?.text || '';
  $('play-button').textContent = video.paused ? '▶' : 'Ⅱ';
  $('play-button').setAttribute('aria-label', video.paused ? 'Play video' : 'Pause video');
}
function positionCaptionOverlay() {
  if (!video.videoWidth || !video.videoHeight) return;
  const stage = video.parentElement;
  const scale = Math.min(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight);
  const width = video.videoWidth * scale, height = video.videoHeight * scale;
  const overlay = $('caption-overlay');
  overlay.style.left = `${(stage.clientWidth - width) / 2 + width * 0.06}px`;
  overlay.style.width = `${width * 0.88}px`;
  overlay.style.bottom = `${(stage.clientHeight - height) / 2 + height * 0.035}px`;
}
new ResizeObserver(positionCaptionOverlay).observe(video.parentElement);
function addCue() {
  if (!project) return;
  const start = Math.round(video.currentTime * 1000) / 1000;
  const existing = project.cues.find(c => c.start <= start && c.end > start);
  if (existing) { selectCue(existing.id, false); toast('A caption already covers this moment. Move the playhead to a gap to add another.'); return; }
  const next = [...project.cues].sort((a,b) => a.start - b.start).find(c => c.start > start);
  const end = Math.round(Math.min(start + 4, next?.start ?? Infinity, project.video.duration) * 1000) / 1000;
  if (end - start < 0.05) { toast('Move the playhead earlier to leave room for a caption.', true); return; }
  video.pause();
  const cue = {id: crypto.randomUUID().replaceAll('-', '').slice(0, 12), start, end, text: ''};
  project.cues.push(cue); markDirty(); selectCue(cue.id, false); $('cue-text').focus();
}
function editCue(field, value) {
  const cue = currentCue(); if (!cue) return;
  cue[field] = value; markDirty(); renderCues(); renderTimeline(); updateQuality(); updatePlayback();
}
async function task(endpoint, body, complete) {
  if (!await save()) return;
  if (dirty && !await save()) return;
  const id = project.id;
  jobActive = true;
  ['ai-button', 'prepare-button', 'render-button', 'render-voice-button', 'generate-voice', 'proxy-button'].forEach(name => $(name).disabled = true);
  $('job-banner').hidden = false; $('job-message').textContent = 'Starting…';
  try {
    const result = await api(base(id) + endpoint, jsonRequest('POST', body));
    while (true) {
      const job = await api('/api/jobs/' + result.job_id);
      $('job-message').textContent = job.message;
      if (job.status === 'error') throw new Error(job.message);
      if (job.status === 'done') { await complete?.(job.result, id); break; }
      await new Promise(resolve => setTimeout(resolve, 850));
    }
    if (project.id === id && !dirty) {
      const fresh = await api(base(id));
      project.narration = fresh.narration; updateQuality();
    }
  } catch (error) { toast(error.message, true); }
  finally {
    jobActive = false; $('job-banner').hidden = true;
    ['ai-button', 'prepare-button', 'render-button', 'render-voice-button', 'generate-voice', 'proxy-button'].forEach(name => $(name).disabled = false);
    if (typeof updateSpeechReady === 'function') updateSpeechReady();
  }
}
function download(url) {
  const anchor = node('a'); anchor.href = url; anchor.download = ''; document.body.append(anchor); anchor.click(); anchor.remove();
}
async function upload(file) {
  if (!file || (dirty && !await save())) return;
  $('import-progress').textContent = 'Copying and inspecting the recording…';
  try {
    const data = new FormData(); data.append('file', file);
    const result = await api('/api/upload', {method: 'POST', body: data});
    $('import-dialog').close(); await openProject(result.id); toast('Recording added. Play it and press N to start an explanation.');
  } catch (error) { toast(error.message, true); }
  finally { $('import-progress').textContent = ''; $('file-input').value = ''; }
}

$('import-button').onclick = $('empty-import').onclick = () => $('import-dialog').showModal();
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
$('file-input').onchange = event => upload(event.target.files[0]);
for (const name of ['dragenter', 'dragover']) $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.add('dragging'); });
$('dropzone').ondragleave = () => $('dropzone').classList.remove('dragging');
$('dropzone').ondrop = event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); upload(event.dataTransfer.files[0]); };
$('path-form').onsubmit = async event => {
  event.preventDefault(); if (dirty && !await save()) return;
  $('import-progress').textContent = 'Inspecting the recording…';
  try {
    const result = await api('/api/projects', jsonRequest('POST', {path: $('local-path').value}));
    $('import-dialog').close(); await openProject(result.id);
  } catch (error) { toast(error.message, true); }
  finally { $('import-progress').textContent = ''; }
};
$('play-button').onclick = () => { if (video.paused) video.play().catch(e => toast(e.message, true)); else video.pause(); };
['timeupdate', 'play', 'pause', 'loadedmetadata', 'seeked'].forEach(name => video.addEventListener(name, updatePlayback));
video.addEventListener('error', () => { if (video.getAttribute('src')) $('media-error').hidden = false; });
video.addEventListener('loadeddata', () => { $('media-error').hidden = true; });
video.addEventListener('loadedmetadata', () => { applyEditorPreferences(); positionCaptionOverlay(); });
$('scrubber').oninput = event => { video.currentTime = Number(event.target.value); updatePlayback(); };
$('speed').onchange = event => saveEditorPreferences({playback_speed: Number(event.target.value)}).catch(e => toast(e.message, true));
$('mute-button').onclick = () => saveEditorPreferences({muted: !video.muted}).catch(e => toast(e.message, true));
$('project-title').oninput = markDirty;
$('save-button').onclick = save;
$('add-button').onclick = addCue;
$('cue-text').oninput = event => editCue('text', event.target.value);
$('cue-start').oninput = event => editCue('start', event.target.value === '' ? NaN : Number(event.target.value));
$('cue-end').oninput = event => editCue('end', event.target.value === '' ? NaN : Number(event.target.value));
$('start-now').onclick = () => { editCue('start', Math.round(video.currentTime * 1000) / 1000); renderEditor(); };
$('end-now').onclick = () => { editCue('end', Math.round(video.currentTime * 1000) / 1000); renderEditor(); };
$('delete-button').onclick = () => { project.cues = project.cues.filter(c => c.id !== selectedId); selectedId = project.cues[0]?.id || null; markDirty(); renderCues(); renderEditor(); renderTimeline(); };
$('timeline-track').onclick = event => { const box = $('timeline-track').getBoundingClientRect(); video.currentTime = Math.max(0, Math.min(project.video.duration, (event.clientX - box.left) / box.width * project.video.duration)); updatePlayback(); };
$('export-button').onclick = async () => { if (await save()) $('export-dialog').showModal(); };
document.querySelectorAll('[data-export]').forEach(button => button.onclick = async () => { if (await save()) download(base() + '/export/' + button.dataset.export); });
for (const [id, narrated] of [['render-button', false], ['render-voice-button', true]]) $(id).onclick = () => {
  $('export-dialog').close();
  task('/render?narrated=' + narrated, {}, (result, projectId) => { download(base(projectId) + '/files/' + result.file + '?download=true'); toast('Your video is ready. A copy is saved in the project exports folder.'); });
};
$('ai-button').onclick = () => { $('ai-command').textContent = `Inspect project ${project.id} in Clarity Studio and write concise explanations for the visible screen actions. Use ./clarity-cli show, inspect, frame, and cues. Validate the result and export SRT.`; $('ai-results').replaceChildren(); $('ai-dialog').showModal(); };
$('prepare-button').onclick = () => { $('ai-dialog').close(); task('/inspect', {every: 5, max_frames: 48}, (result, id) => {
  $('ai-results').replaceChildren();
  for (const path of result.contact_sheets) {
    const img = node('img', 'ai-sheet'); img.src = base(id) + '/files/inspection/' + path.split('/').pop(); img.alt = 'Timestamped contact sheet of the recording'; $('ai-results').append(img);
  }
  for (const [file, label] of [['AI-BRIEF.md', 'Task brief ↗'], ['manifest.json', 'Frame manifest ↗']]) {
    const link = node('a', 'ai-link', label); link.href = base(id) + '/files/inspection/' + file; link.target = '_blank'; link.rel = 'noopener'; $('ai-results').append(link);
  }
  $('ai-dialog').showModal(); toast(`${result.frames.length} timestamped frames ready for your AI.`);
}); };
$('copy-command').onclick = () => navigator.clipboard.writeText($('ai-command').textContent).then(() => toast('AI instructions copied.')).catch(() => toast('Select and copy the text in this window.', true));
$('proxy-button').onclick = () => task('/preview', {}, (result, id) => { if (project.id === id) { video.src = base(id) + '/files/' + result.file; video.load(); } toast('Browser preview ready.'); });
$('help-button').onclick = () => $('help-dialog').showModal();
document.addEventListener('keydown', event => {
  if (event.defaultPrevented) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
  if (!project || event.target.closest('input,textarea,select,[contenteditable]') || document.querySelector('dialog[open]') || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.code === 'Space') { event.preventDefault(); $('play-button').click(); }
  if (event.key.toLowerCase() === 'n') { event.preventDefault(); addCue(); }
  if (event.key === '[' && currentCue()) $('start-now').click();
  if (event.key === ']' && currentCue()) $('end-now').click();
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); video.currentTime = Math.max(0, Math.min(project.video.duration, video.currentTime + (event.key === 'ArrowLeft' ? -1 : 1))); }
});
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
setInterval(async () => {
  if (!project || dirty || saving || jobActive || document.activeElement?.matches('input,textarea')) return;
  try {
    const fresh = await api(base());
    if (fresh.revision !== project.revision) {
      project = fresh;
      if (!currentCue()) selectedId = project.cues[0]?.id || null;
      $('project-title').value = fresh.title;
      $('revision-label').textContent = `REVISION ${String(project.revision).padStart(3, '0')} · SAVED LOCALLY`;
      renderCues(); renderEditor(); renderTimeline(); await loadLibrary();
      toast('Captions updated from the local workspace.');
    } else { project.narration = fresh.narration; updateQuality(); }
  } catch (_) { /* The next poll will reconnect; unsaved work stays in memory. */ }
}, 3000);
document.addEventListener('DOMContentLoaded', async () => {
  try {
    health = await api('/api/health');
    try { await loadEditorPreferences(); }
    catch (error) { toast('Preferences could not be loaded. ' + error.message, true); }
    const projects = await loadLibrary();
    const last = editorPreferences.last_project || localStorage.getItem('clarity-project');
    if (projects.length) await openProject(projects.some(p => p.id === last) ? last : projects[0].id);
    localStorage.removeItem('clarity-project');
  } catch (error) { toast('Could not connect to the local app. ' + error.message, true); }
});
