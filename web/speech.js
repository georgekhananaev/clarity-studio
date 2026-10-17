'use strict';
let speechState = null, speechCatalog = null, speechLoading = false, speechRequest = 0;
let speechSaveQueue = Promise.resolve(), speechChoiceTimer, rememberChoiceChanged = false, rememberChoiceVersion = 0;
let integrationProvider = null, integrationInitialized = false, speechChoicesReady = false;
let speechChoiceVersion = 0, speechConnectionVersion = 0;
const customChoice = '__custom__';
const selectedSpeechModel = () => $('voice-model').value === customChoice ? $('custom-speech-model').value.trim() : $('voice-model').value;
const selectedSpeechVoice = () => $('voice-choice').value === customChoice ? $('voice-id').value.trim() : $('voice-choice').value;

function rememberSpeechChoice() {
  if (!speechState || !speechChoicesReady) return;
  speechState[speechState.provider] = {model: selectedSpeechModel(), voice: selectedSpeechVoice(), instructions: $('voice-instructions').value};
}

function persistSpeech(payload, choicesOnly = false) {
  const request = jsonRequest(choicesOnly ? 'PATCH' : 'PUT', payload);
  const pending = speechSaveQueue.catch(() => {}).then(() => api(choicesOnly ? '/api/speech/preferences' : '/api/speech/settings', request));
  speechSaveQueue = pending;
  return pending;
}

async function saveSpeechChoices() {
  clearTimeout(speechChoiceTimer);
  speechChoiceTimer = null;
  if (!speechState || !speechChoicesReady) return;
  rememberSpeechChoice();
  const provider = speechState.provider;
  $('speech-choice-status').textContent = 'Saving model and voice choices…';
  await persistSpeech({provider, preferences: speechState[provider]}, true);
  $('speech-choice-status').textContent = 'Model and voice choices saved on this Mac.';
}

function scheduleSpeechChoices() {
  speechChoiceVersion++;
  clearTimeout(speechChoiceTimer);
  speechChoiceTimer = setTimeout(() => saveSpeechChoices().catch(error => {
    $('speech-choice-status').textContent = 'Choices could not be saved. ' + error.message;
  }), 500);
}

function updateSpeechReady() {
  if (!speechState) { $('generate-voice').disabled = true; return; }
  const provider = speechState.provider;
  const configured = provider === 'local' || speechState.keys.openrouter.configured;
  $('generate-voice').disabled = jobActive || speechLoading || !configured || !selectedSpeechModel() || !selectedSpeechVoice() || !project?.cues.length;
  const ready = project?.cues.length > 0 && project.narration?.length === project.cues.length && project.narration.every(c => c.status === 'ready');
  $('speech-export-mp3').disabled = jobActive || !ready;
  $('speech-export-wav').disabled = jobActive || !ready;
  const audio = project?.narration || [];
  const count = audio.filter(c => c.status === 'ready').length;
  const overflow = audio.filter(c => c.status === 'overflow').length;
  const models = [...new Set(audio.filter(c => c.duration).map(c => c.model))];
  $('speech-audio-summary').textContent = `${count} / ${project?.cues.length || 0} captions have audio that fits.${overflow ? ` ${overflow} need more time.` : ''}${models.length ? ` Saved audio: ${models.join(', ')}. Generate again to apply a different model or voice.` : ' Generate narration to export an audio track.'}`;
}

function renderSpeechVoices(preferred) {
  const model = speechCatalog?.models.find(m => m.id === selectedSpeechModel());
  const voices = model?.voices?.length ? model.voices : speechCatalog?.voices || [];
  $('voice-choice').replaceChildren();
  for (const voice of voices) {
    const option = node('option', '', voice.name); option.value = voice.id; $('voice-choice').append(option);
  }
  const custom = node('option', '', voices.length ? 'Use a custom voice ID…' : 'Enter a provider voice ID…');
  custom.value = customChoice; $('voice-choice').append(custom);
  $('voice-choice').value = preferred && voices.some(v => v.id === preferred) ? preferred : preferred || !voices.length ? customChoice : voices[0].id;
  $('voice-id').value = preferred && !voices.some(v => v.id === preferred) ? preferred : '';
  const hint = $('speech-voice-hint'); hint.replaceChildren();
  if (!voices.length) {
    hint.append(document.createTextNode('This model does not publish a voice list. Enter a voice ID from its provider. '));
    if (speechState.provider === 'openrouter' && selectedSpeechModel()) {
      const link = node('a', '', 'Model details ↗');
      link.href = 'https://openrouter.ai/' + selectedSpeechModel().split('/').map(encodeURIComponent).join('/'); link.target = '_blank'; link.rel = 'noopener'; hint.append(link);
    }
  } else hint.textContent = `${voices.length} voices available. Custom voice IDs are also supported.`;
  $('speech-model-description').textContent = model?.description?.slice(0, 240) || 'Use the exact speech model ID served by your provider.';
  updateSpeechVoiceField();
}

function updateSpeechVoiceField() {
  const custom = $('voice-choice').value === customChoice;
  $('voice-id').hidden = $('custom-voice-label').hidden = !custom;
  $('voice-id').required = custom;
  updateSpeechReady();
}

function renderSpeechModels(preferred, voice) {
  const query = $('model-search').value.trim().toLowerCase();
  const models = speechCatalog?.models || [];
  const matches = models.filter(m => `${m.name} ${m.id}`.toLowerCase().includes(query));
  const selected = models.find(m => m.id === preferred);
  $('voice-model').replaceChildren();
  if (selected && !matches.includes(selected)) matches.unshift(selected);
  for (const model of matches) {
    const option = node('option', '', model.name); option.value = model.id; $('voice-model').append(option);
  }
  if (preferred && !models.some(m => m.id === preferred)) {
    const option = node('option', '', `Saved model · ${preferred}`); option.value = preferred; $('voice-model').append(option);
  }
  const custom = node('option', '', 'Use a custom model ID…'); custom.value = customChoice; $('voice-model').append(custom);
  $('voice-model').value = preferred || matches[0]?.id || customChoice;
  if (!$('voice-model').value) $('voice-model').value = customChoice;
  $('custom-speech-model').value = '';
  const isCustom = $('voice-model').value === customChoice;
  $('custom-speech-model').hidden = $('custom-model-label').hidden = !isCustom;
  $('custom-speech-model').required = isCustom;
  renderSpeechVoices(voice);
}

async function loadSpeechCatalog({resetVoice = false} = {}) {
  const request = ++speechRequest;
  const choicesVersion = speechChoiceVersion;
  const provider = speechState.provider, preferred = selectedSpeechModel() || speechState[provider].model;
  const voice = resetVoice ? '' : selectedSpeechVoice() || speechState[provider].voice;
  speechLoading = true; updateSpeechReady();
  $('speech-catalog-status').textContent = 'Loading speech models and voices…';
  $('refresh-speech-models').disabled = true;
  try {
    const result = await api('/api/speech/discover', jsonRequest('POST', {provider, base_url: provider === 'local' ? speechState.local_base_url : null, model: preferred || null}));
    if (request !== speechRequest) return;
    speechCatalog = result;
    renderSpeechModels(choicesVersion === speechChoiceVersion ? preferred : selectedSpeechModel(), choicesVersion === speechChoiceVersion ? voice : selectedSpeechVoice());
    $('speech-catalog-status').textContent = `${result.models.length} speech models${result.cached ? ' · Saved catalog' : ''}. ${result.warnings.join(' ')}`;
    $('speech-catalog-status').classList.remove('warning');
  } catch (error) {
    if (request !== speechRequest) return;
    speechCatalog = null;
    renderSpeechModels(choicesVersion === speechChoiceVersion ? preferred : selectedSpeechModel(), choicesVersion === speechChoiceVersion ? voice : selectedSpeechVoice());
    $('speech-catalog-status').textContent = error.message + ' You can still enter model and voice IDs manually.';
    $('speech-catalog-status').classList.add('warning');
  } finally {
    if (request === speechRequest) { speechLoading = false; $('refresh-speech-models').disabled = false; updateSpeechReady(); }
  }
}

function speechConnectionStatus() {
  if (!speechState || !integrationProvider) return;
  const source = speechState.keys[integrationProvider];
  $('key-status').textContent = source.configured ? `Key: ${source.source}` : integrationProvider === 'local' ? 'Key optional' : 'Add API key';
  $('speech-key-label').textContent = integrationProvider === 'local' ? 'Local server API key (optional)' : 'OpenRouter API key';
  $('clear-speech-key').disabled = !source.configured;
}

function switchSpeechIntegration(provider) {
  integrationProvider = provider;
  if (!speechState) return;
  integrationInitialized = true;
  $('provider-openrouter').setAttribute('aria-pressed', String(provider === 'openrouter'));
  $('provider-local').setAttribute('aria-pressed', String(provider === 'local'));
  $('local-connection').hidden = provider !== 'local';
  $('local-base-url').value = speechState.local_base_url;
  $('local-preset').value = ['http://127.0.0.1:8880/v1', 'http://127.0.0.1:8000/v1'].includes(speechState.local_base_url) ? speechState.local_base_url : 'custom';
  $('speech-api-key').value = '';
  const source = speechState.keys[provider];
  $('remember-speech-key').checked = !source.configured || source.source === 'keychain';
  rememberChoiceChanged = false;
  rememberChoiceVersion++;
  $('connection-feedback').textContent = '';
  $('speech-connection').open = true;
  speechConnectionStatus();
}

async function refreshSpeechSettings() {
  // Native dialog close events arrive later; flush edits before reading settings.
  if (speechChoiceTimer) await saveSpeechChoices();
  await speechSaveQueue.catch(() => {});
  const choicesVersion = speechChoiceVersion, connectionVersion = speechConnectionVersion;
  const result = await api('/api/speech/settings');
  if (!speechState) speechState = result;
  else {
    if (choicesVersion === speechChoiceVersion) {
      speechState.provider = result.provider;
      speechState.openrouter = result.openrouter;
      speechState.local = result.local;
    }
    if (connectionVersion === speechConnectionVersion) {
      speechState.keys = result.keys;
      speechState.local_base_url = result.local_base_url;
    }
  }
}

async function openSpeechIntegrations() {
  await refreshSpeechSettings();
  if (!integrationInitialized) switchSpeechIntegration(integrationProvider || speechState.provider);
  else speechConnectionStatus();
  $('speech-connection').open = true;
}

async function switchSpeechProvider(provider, initial = false) {
  if (!initial) saveSpeechChoices().catch(error => toast(error.message, true));
  speechState.provider = provider;
  speechChoiceVersion++;
  speechChoicesReady = true;
  speechCatalog = null;
  $('narration-provider').value = provider;
  $('speech-delivery').hidden = provider === 'local';
  $('speech-privacy').textContent = provider === 'local' ? 'Caption text is sent to your saved local speech server. No OpenRouter credits are used.' : 'Generating narration sends caption text to OpenRouter and the speech provider, and uses your credits. Browsing models is free.';
  $('voice-instructions').value = speechState[provider].instructions;
  $('model-search').value = '';
  renderSpeechModels(speechState[provider].model, speechState[provider].voice);
  if (!initial) scheduleSpeechChoices();
  await loadSpeechCatalog();
}

async function saveSpeechSettings({clear = false} = {}) {
  const provider = integrationProvider;
  if (!speechState || !provider) throw new Error('Load the integration settings first.');
  const settings = {provider: speechState.provider, local_base_url: provider === 'local' ? $('local-base-url').value.trim() || speechState.local_base_url : speechState.local_base_url, openrouter: speechState.openrouter, local: speechState.local};
  const key = $('speech-api-key').value.trim();
  const consentVersion = rememberChoiceVersion;
  const remember = $('remember-speech-key').checked && !!(key || (rememberChoiceChanged && speechState.keys[provider].configured));
  const result = await persistSpeech({settings, credential_provider: provider, api_key: key || null, remember_key: remember, clear_key: clear});
  // A late connection response must not replace choices edited while it saved.
  speechConnectionVersion++;
  speechState.keys = result.keys;
  speechState.local_base_url = result.local_base_url;
  if (integrationProvider === provider && $('speech-api-key').value.trim() === key) {
    $('speech-api-key').value = '';
  }
  if (integrationProvider === provider && rememberChoiceVersion === consentVersion) rememberChoiceChanged = false;
  speechConnectionStatus(); updateSpeechReady();
  return result;
}

$('voice-button').onclick = async () => {
  $('voice-dialog').showModal();
  $('generate-voice').disabled = true;
  try {
    await refreshSpeechSettings();
    if (!speechState.openrouter.voice && health.default_voice) speechState.openrouter.voice = health.default_voice;
    await switchSpeechProvider(speechState.provider, true);
  } catch (error) { toast(error.message, true); }
};
$('voice-dialog').addEventListener('close', () => {
  saveSpeechChoices().catch(error => toast('Could not save voice preferences. ' + error.message, true));
});
for (const provider of ['openrouter', 'local']) $('provider-' + provider).onclick = () => switchSpeechIntegration(provider);
$('narration-provider').onchange = event => switchSpeechProvider(event.target.value).catch(error => toast(error.message, true));
$('manage-integrations').onclick = () => { $('voice-dialog').close(); openPreferences('integrations'); };
$('refresh-speech-models').onclick = () => loadSpeechCatalog();
$('local-preset').onchange = event => { if (event.target.value !== 'custom') $('local-base-url').value = event.target.value; };
$('local-base-url').oninput = () => { $('local-preset').value = 'custom'; };
$('model-search').oninput = () => renderSpeechModels(selectedSpeechModel(), selectedSpeechVoice());
$('voice-model').onchange = () => {
  const custom = $('voice-model').value === customChoice;
  $('custom-speech-model').hidden = $('custom-model-label').hidden = !custom;
  $('custom-speech-model').required = custom;
  renderSpeechVoices('');
  if (speechState.provider === 'local') loadSpeechCatalog({resetVoice: true});
  scheduleSpeechChoices();
};
$('custom-speech-model').oninput = () => { renderSpeechVoices(selectedSpeechVoice()); scheduleSpeechChoices(); };
$('voice-choice').onchange = () => { updateSpeechVoiceField(); scheduleSpeechChoices(); };
$('voice-id').oninput = () => { updateSpeechReady(); scheduleSpeechChoices(); };
$('voice-instructions').oninput = scheduleSpeechChoices;
$('remember-speech-key').onchange = () => { rememberChoiceChanged = true; rememberChoiceVersion++; };
$('speech-connection-form').onsubmit = async event => {
  event.preventDefault();
  const provider = integrationProvider;
  try { await saveSpeechSettings(); if (integrationProvider === provider) $('connection-feedback').textContent = 'Connection saved. Keys are never written to the project files.'; }
  catch (error) { if (integrationProvider === provider) $('connection-feedback').textContent = error.message; }
};
$('test-speech-connection').onclick = async () => {
  const provider = integrationProvider;
  $('test-speech-connection').disabled = true;
  try {
    await saveSpeechSettings();
    if (integrationProvider === provider) $('connection-feedback').textContent = 'Testing connection without generating audio…';
    const result = await api('/api/speech/test', jsonRequest('POST', {provider}));
    if (integrationProvider === provider) $('connection-feedback').textContent = result.message;
  } catch (error) { if (integrationProvider === provider) $('connection-feedback').textContent = error.message; }
  finally { $('test-speech-connection').disabled = false; }
};
$('clear-speech-key').onclick = async () => {
  const provider = integrationProvider;
  try { await saveSpeechSettings({clear: true}); if (integrationProvider === provider) $('connection-feedback').textContent = 'The saved key was removed and is disabled for this session.'; }
  catch (error) { if (integrationProvider === provider) $('connection-feedback').textContent = error.message; }
};
$('voice-form').onsubmit = async event => {
  event.preventDefault();
  if (jobActive) return;
  try {
    await saveSpeechChoices();
    const settings = speechState[speechState.provider];
    const cueIds = $('speech-scope').value === 'selected' ? [currentCue()?.id].filter(Boolean) : null;
    if (cueIds && !cueIds.length) throw new Error('Select a caption first.');
    $('voice-dialog').close();
    await task('/narrate', {provider: speechState.provider, ...settings, cue_ids: cueIds}, result => {
      const overflow = result.segments.filter(s => s.status === 'overflow').length;
      toast(overflow ? `Audio generated. ${overflow} caption(s) need more time before export.` : 'Audio generated. Listen beside each caption or export the narration track.', !!overflow);
    });
  } catch (error) { toast(error.message, true); }
};
for (const format of ['mp3', 'wav']) $('speech-export-' + format).onclick = () => {
  $('voice-dialog').close();
  task('/audio?format=' + format, {}, (result, id) => { download(base(id) + '/files/' + result.file + '?download=true'); toast('Narration exported. A copy is saved in the project exports folder.'); });
};
