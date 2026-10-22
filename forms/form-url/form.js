import {mount, action} from '/runtime/runtime.js';

const urlInput = document.getElementById('url');
const choices = ['bookmark', 'read', 'index'];
function validURL(value) {
  if (!/^https?:\/\//i.test(value) || /\s/.test(value)) return false;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && Boolean(url.hostname);
  } catch { return false; }
}

const definition = {
  defaults: {url: '', bookmark: false, read: false, index: false},
  collect() {
    return {url: urlInput.value, ...Object.fromEntries(choices.map(name => [name, document.getElementById(name).checked]))};
  },
  render(data) {
    if (typeof data.url !== 'string') throw new Error('url must be text');
    urlInput.value = data.url;
    for (const name of choices) {
      const value = name === 'read' && !Object.hasOwn(data, name) ? false : data[name];
      if (typeof value !== 'boolean') throw new Error(`${name} must be a boolean`);
      document.getElementById(name).checked = value;
    }
  },
  validate(data) {
    return validURL(data.url) ? [] : [{field: 'url', message: 'Enter a valid HTTP(S) URL.'}];
  }
};

urlInput.addEventListener('input', () => {
  urlInput.setCustomValidity('');
});
document.querySelector('[data-action="reader"]').addEventListener('click', async () => {
  urlInput.setCustomValidity(validURL(urlInput.value) ? '' : 'Enter a valid HTTP(S) URL.');
  if (!urlInput.reportValidity() || document.querySelector('[data-fields]').disabled) return;
  const data = definition.collect();
  // Reserve the tab during the user gesture so popup blockers allow it.
  const destination = window.open('about:blank', '_blank');
  if (destination) destination.opener = null;
  const saved = await action('reader', data);
  if (destination) {
    if (saved) destination.location.replace(data.url);
    else destination.close();
  } else if (saved) {
    document.querySelector('[data-status]').textContent = 'Reader saved. Allow popups to open the URL.';
  }
});
mount(definition);
