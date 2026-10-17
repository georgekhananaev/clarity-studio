// Isolated browser-state regressions: no network, real credentials or Keychain.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness({holdFirst = false, holdDiscovery = false, provider = 'local', testError = null} = {}) {
  const elements = {};
  const makeElement = () => ({value: '', checked: false, textContent: '', listeners: {}, children: [], style: {setProperty() {}}, dataset: {}, classList: {add() {}, remove() {}, toggle() {}}, addEventListener(name, fn) { this.listeners[name] = fn; }, setAttribute() {}, append(child) { this.children.push(child); }, replaceChildren() { this.children = []; }, focus() {}, showModal() { this.open = true; }, close() { this.open = false; this.listeners.close?.(); }});
  const element = id => elements[id] ||= makeElement();
  let release, started, releaseDiscovery, discoveryStarted;
  const held = new Promise(resolve => { release = resolve; });
  const firstStarted = new Promise(resolve => { started = resolve; });
  const catalogHeld = new Promise(resolve => { releaseDiscovery = resolve; });
  const catalogStarted = new Promise(resolve => { discoveryStarted = resolve; });
  const writes = [], calls = [], tasks = [], toasts = [];
  let saved = {provider, local_base_url: 'http://127.0.0.1:8880/v1', openrouter: {model: 'fish-audio/drama-3', voice: 'cloud-voice', instructions: ''}, local: {model: 'kokoro', voice: 'af_heart', instructions: ''}};
  const sources = new Map();
  const account = (selected, endpoint = saved.local_base_url) => selected === 'local' ? `local:${endpoint}` : 'openrouter';
  const keySource = (selected = 'local', endpoint) => sources.get(account(selected, endpoint)) || 'none';
  const publicSettings = () => JSON.parse(JSON.stringify({...saved, keys: Object.fromEntries(['openrouter', 'local'].map(selected => [selected, {configured: keySource(selected) !== 'none', source: keySource(selected)}]))}));
  const context = vm.createContext({console, setTimeout, clearTimeout, $: element,
    window: {innerWidth: 1440, addEventListener() {}, matchMedia: () => ({matches: true, addEventListener() {}})},
    document: {createTextNode: text => ({textContent: text}), querySelectorAll: () => [], addEventListener() {}, body: makeElement(), documentElement: {dataset: {}, style: {setProperty() {}}}},
    video: {},
    jsonRequest: (method, payload) => ({method, body: JSON.stringify(payload)}),
    api: async (url, request) => {
      const value = request ? JSON.parse(request.body) : undefined;
      calls.push({url, ...value});
      if (!request) return publicSettings();
      if (url === '/api/speech/discover') {
        discoveryStarted();
        if (holdDiscovery) await catalogHeld;
        const prefs = saved[value.provider];
        return {models: [{id: prefs.model, name: prefs.model, voices: [{id: prefs.voice, name: prefs.voice}]}], voices: [], warnings: []};
      }
      if (url === '/api/speech/test') {
        if (testError) throw new Error(testError);
        return {connected: true, message: 'Connection accepted. No audio generated.'};
      }
      writes.push({url, ...value});
      if (writes.length === 1) { started(); if (holdFirst) await held; }
      if (url === '/api/speech/preferences') {
        saved = {...saved, provider: value.provider, [value.provider]: value.preferences};
      } else {
        saved = value.settings;
        const selected = value.credential_provider || saved.provider;
        const selectedAccount = account(selected);
        if (value.clear_key) sources.delete(selectedAccount);
        else if (value.api_key) sources.set(selectedAccount, value.remember_key ? 'keychain' : 'session');
        else if (value.remember_key && keySource(selected) !== 'none') sources.set(selectedAccount, 'keychain');
      }
      return publicSettings();
    }, project: {cues: []}, jobActive: false, health: {}, toast(message) { toasts.push(message); }, node(tag, css, text) { const result = makeElement(); result.textContent = text; return result; }, download() {}, task(url, payload) { tasks.push({url, payload}); }});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/speech.js'), 'utf8'), context);
  vm.runInContext(`speechState = ${JSON.stringify(publicSettings())}; integrationProvider = speechState.provider; integrationInitialized = true; speechChoicesReady = true; $('local-base-url').value = speechState.local_base_url; $('voice-model').value = speechState[speechState.provider].model; $('voice-choice').value = speechState[speechState.provider].voice;`, context);
  return {element, writes, calls, tasks, toasts, release, firstStarted, releaseDiscovery, catalogStarted, run: code => vm.runInContext(code, context), saved: () => saved, keySource, loadPreferences: () => vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/preferences.js'), 'utf8'), context)};
}

test('closing the dialog during a connection save preserves the new endpoint', async () => {
  const h = harness({holdFirst: true});
  h.element('local-base-url').value = 'http://127.0.0.1:8000/v1';
  const explicit = h.run('saveSpeechSettings()');
  await h.firstStarted;
  h.run("$('voice-dialog').listeners.close()");
  h.release();
  await explicit;
  await h.run('speechSaveQueue');
  assert.equal(h.saved().local_base_url, 'http://127.0.0.1:8000/v1');
  assert.equal(h.run('speechState.local_base_url'), h.saved().local_base_url);
  assert.equal(h.writes[1].url, '/api/speech/preferences');
  assert.equal(h.writes[1].settings, undefined);
  assert.equal(h.writes[1].api_key, undefined);
});

test('session-only consent survives later connection tests and generation setup', async () => {
  const h = harness();
  h.element('speech-api-key').value = 'dummy-session-key';
  h.element('remember-speech-key').checked = false;
  await h.run('saveSpeechSettings()');
  assert.equal(h.keySource(), 'session');
  await h.run('saveSpeechSettings()');
  await h.run('saveSpeechSettings()');
  assert.equal(h.keySource(), 'session');
  assert.deepEqual(h.writes.map(item => item.remember_key), [false, false, false]);
});

test('remembering an existing session key requires an explicit checkbox change', async () => {
  const h = harness();
  h.element('speech-api-key').value = 'dummy-session-key';
  await h.run('saveSpeechSettings()');
  h.element('remember-speech-key').checked = true;
  h.run("$('remember-speech-key').onchange()");
  await h.run('saveSpeechSettings()');
  assert.equal(h.keySource(), 'keychain');
});

test('late connection response preserves newer provider selection, edits and typed key', async () => {
  const h = harness({holdFirst: true});
  const explicit = h.run('saveSpeechSettings()');
  await h.firstStarted;
  h.run("speechState.provider = 'openrouter'; speechState.openrouter.voice = 'new-voice'; switchSpeechIntegration('openrouter'); $('speech-api-key').value = 'new-unsaved-key';");
  h.release();
  await explicit;
  assert.equal(h.run('speechState.provider'), 'openrouter');
  assert.equal(h.run('speechState.openrouter.voice'), 'new-voice');
  assert.equal(h.run('integrationProvider'), 'openrouter');
  assert.equal(h.element('speech-api-key').value, 'new-unsaved-key');
});

test('a storage choice made during a pending save is preserved for the next action', async () => {
  const h = harness({holdFirst: true});
  h.element('speech-api-key').value = 'dummy-session-key';
  const explicit = h.run('saveSpeechSettings()');
  await h.firstStarted;
  h.element('remember-speech-key').checked = true;
  h.run("$('remember-speech-key').onchange()");
  h.release();
  await explicit;
  assert.equal(h.keySource(), 'session');
  await h.run('saveSpeechSettings()');
  assert.equal(h.keySource(), 'keychain');
});

test('opening integrations reads settings without loading narration catalogs or emptying choices', async () => {
  const h = harness({provider: 'openrouter'});
  h.run('speechState = null; integrationProvider = null; integrationInitialized = false; speechChoicesReady = false;');
  await h.run('openSpeechIntegrations()');
  assert.equal(h.run('integrationProvider'), 'openrouter');
  assert.equal(h.element('speech-connection').open, true);
  assert.deepEqual(h.calls.map(item => item.url), ['/api/speech/settings']);
  await h.run("$('voice-dialog').listeners.close()");
  assert.equal(h.writes.length, 0);
  assert.equal(h.run('speechState.openrouter.voice'), 'cloud-voice');
});

test('configuring local speech keeps OpenRouter selected for narration and separates credentials', async () => {
  const h = harness({provider: 'openrouter'});
  h.element('speech-api-key').value = 'dummy-cloud-key';
  await h.run('saveSpeechSettings()');
  h.run("switchSpeechIntegration('local')");
  h.element('local-base-url').value = 'http://127.0.0.1:8000/v1';
  h.element('speech-api-key').value = 'dummy-local-key';
  await h.run("$('speech-connection-form').onsubmit({preventDefault() {}})");
  assert.equal(h.saved().provider, 'openrouter');
  assert.equal(h.saved().openrouter.voice, 'cloud-voice');
  assert.equal(h.element('voice-model').value, 'fish-audio/drama-3');
  assert.equal(h.writes[1].credential_provider, 'local');
  assert.equal(h.keySource('openrouter'), 'session');
  assert.equal(h.keySource('local'), 'keychain');
  assert.equal(h.keySource('local', 'http://127.0.0.1:8880/v1'), 'none');
  assert.equal(h.calls.some(item => item.url.includes('/discover')), false);
  await h.run("$('clear-speech-key').onclick()");
  assert.equal(h.keySource('local'), 'none');
  assert.equal(h.keySource('openrouter'), 'session');
});

test('narration provider selection leaves integration drafts and provider untouched', async () => {
  const h = harness({provider: 'openrouter'});
  h.element('speech-api-key').value = 'unsaved-cloud-key';
  h.element('local-base-url').value = 'http://127.0.0.1:8000/v1';
  await h.run("switchSpeechProvider('local')");
  await h.run('saveSpeechChoices()');
  assert.equal(h.run('integrationProvider'), 'openrouter');
  assert.equal(h.element('speech-api-key').value, 'unsaved-cloud-key');
  assert.equal(h.element('local-base-url').value, 'http://127.0.0.1:8000/v1');
  assert.equal(h.saved().provider, 'local');
  assert.equal(h.calls.find(item => item.url.endsWith('/discover')).base_url, 'http://127.0.0.1:8880/v1');
  assert.ok(h.writes.every(item => item.url === '/api/speech/preferences'));
});

test('connection tests target the selected integration and display safe failures as text', async () => {
  const h = harness({provider: 'openrouter', testError: 'Local speech server could not be reached. Check the server.'});
  h.run("switchSpeechIntegration('local')");
  await h.run("$('test-speech-connection').onclick()");
  assert.equal(h.calls.find(item => item.url === '/api/speech/test').provider, 'local');
  assert.equal(h.saved().provider, 'openrouter');
  assert.match(h.element('connection-feedback').textContent, /could not be reached/);
  assert.equal(h.element('test-speech-connection').disabled, false);
  assert.equal(h.calls.some(item => item.url.includes('/discover')), false);
  assert.equal(h.tasks.length, 0);
});

test('narration submission saves choices without applying integration drafts or credentials', async () => {
  const h = harness({provider: 'openrouter'});
  h.run("switchSpeechIntegration('local')");
  h.element('local-base-url').value = 'http://127.0.0.1:8000/v1';
  h.element('speech-api-key').value = 'unsaved-local-key';
  await h.run("$('voice-form').onsubmit({preventDefault() {}})");
  await h.run('speechSaveQueue');
  assert.ok(h.writes.every(item => item.url === '/api/speech/preferences'));
  assert.equal(h.saved().local_base_url, 'http://127.0.0.1:8880/v1');
  assert.equal(h.keySource('local'), 'none');
  assert.equal(h.tasks[0].url, '/narrate');
  assert.equal(h.tasks[0].payload.provider, 'openrouter');
  assert.equal(h.tasks[0].payload.voice, 'cloud-voice');
  assert.equal(h.element('speech-api-key').value, 'unsaved-local-key');
});

test('late catalog responses retain model and voice edits made while loading', async () => {
  const h = harness({holdDiscovery: true});
  const catalog = h.run('loadSpeechCatalog()');
  await h.catalogStarted;
  h.run("$('voice-model').value = 'new-model'; $('voice-choice').value = customChoice; $('voice-id').value = 'new-voice'; scheduleSpeechChoices();");
  h.releaseDiscovery();
  await catalog;
  await h.run('saveSpeechChoices()');
  assert.equal(h.saved().local.model, 'new-model');
  assert.equal(h.saved().local.voice, 'new-voice');
});

test('opening integrations waits for a pending endpoint save without replacing its newer draft', async () => {
  const h = harness({holdFirst: true});
  h.element('local-base-url').value = 'http://127.0.0.1:8000/v1';
  const explicit = h.run('saveSpeechSettings()');
  await h.firstStarted;
  h.element('local-base-url').value = 'http://127.0.0.1:8001/v1';
  const opening = h.run('openSpeechIntegrations()');
  assert.equal(h.calls.length, 1);
  h.release();
  await Promise.all([explicit, opening]);
  assert.equal(h.run('speechState.local_base_url'), 'http://127.0.0.1:8000/v1');
  assert.equal(h.element('local-base-url').value, 'http://127.0.0.1:8001/v1');
  assert.equal(h.calls[1].url, '/api/speech/settings');
});

test('Preferences close clears an unsaved integration key without saving it', () => {
  const h = harness();
  h.loadPreferences();
  h.element('speech-api-key').value = 'private-unsaved-key';
  h.element('preferences-dialog').close();
  assert.equal(h.element('speech-api-key').value, '');
  assert.equal(h.writes.length, 0);
  assert.equal(h.tasks.length, 0);
});

test('opening Preferences flushes narration edits before loading integrations', async () => {
  const h = harness({provider: 'openrouter'});
  h.loadPreferences();
  h.element('voice-dialog').open = true;
  h.run("$('voice-choice').value = customChoice; $('voice-id').value = 'latest-cloud-voice'; scheduleSpeechChoices();");
  await h.run("openPreferences('integrations')");
  await h.run('speechSaveQueue');
  assert.equal(h.element('voice-dialog').open, false);
  assert.equal(h.element('preferences-dialog').open, true);
  assert.equal(h.saved().openrouter.voice, 'latest-cloud-voice');
  assert.equal(h.run('speechState.openrouter.voice'), 'latest-cloud-voice');
  assert.equal(h.calls.at(-1).url, '/api/speech/settings');
  assert.equal(h.calls.some(item => item.url.includes('/discover')), false);
});
