import {mount} from '/runtime/runtime.js';

const editor = document.getElementById('body');
const fieldset = document.querySelector('[data-fields]');
const allowed = new Set(['P', 'DIV', 'BR', 'B', 'STRONG', 'I', 'EM', 'U', 'UL', 'OL', 'LI']);

// Rebuild from an inert document: no attributes, links, images, or executable markup.
function cleanHTML(html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  const output = document.createElement('div');
  function copy(source, target) {
    for (const child of source.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) target.append(document.createTextNode(child.textContent));
      else if (child.nodeType === Node.ELEMENT_NODE) {
        if (['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'TEMPLATE', 'SVG', 'MATH'].includes(child.tagName)) continue;
        if (allowed.has(child.tagName)) {
          const element = document.createElement(child.tagName.toLowerCase());
          copy(child, element);
          target.append(element);
        } else copy(child, target);
      }
    }
  }
  copy(parsed.body, output);
  return output.innerHTML;
}

// Fieldsets do not automatically disable contenteditable descendants.
function syncDisabled() {
  editor.contentEditable = String(!fieldset.disabled);
  editor.setAttribute('aria-disabled', String(fieldset.disabled));
}
new MutationObserver(syncDisabled).observe(fieldset, {attributes: true, attributeFilter: ['disabled']});
syncDisabled();

for (const button of document.querySelectorAll('[data-command]')) {
  button.addEventListener('mousedown', event => event.preventDefault());
  button.addEventListener('click', () => {
    if (fieldset.disabled) return;
    editor.focus();
    // Native editing commands retain the browser's selection and undo history.
    document.execCommand(button.dataset.command, false);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

editor.addEventListener('paste', event => {
  event.preventDefault();
  if (fieldset.disabled) return;
  const clipboard = event.clipboardData;
  const html = clipboard.getData('text/html');
  if (html) document.execCommand('insertHTML', false, cleanHTML(html));
  else document.execCommand('insertText', false, clipboard.getData('text/plain'));
  editor.dispatchEvent(new Event('input', {bubbles: true}));
});
editor.addEventListener('drop', event => event.preventDefault());

mount({
  defaults: {to: '', subject: '', body: ''},
  collect() {
    return {to: document.getElementById('to').value,
      subject: document.getElementById('subject').value, body: cleanHTML(editor.innerHTML)};
  },
  render(data) {
    for (const name of ['to', 'subject', 'body']) {
      if (typeof data[name] !== 'string') throw new Error(`${name} must be text`);
    }
    document.getElementById('to').value = data.to;
    document.getElementById('subject').value = data.subject;
    editor.innerHTML = cleanHTML(data.body);
  },
  validate(data) {
    const errors = [];
    const recipients = data.to.split(',').map(value => value.trim());
    if (data.to.length > 2000 || recipients.some(value => !/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(value))) {
      errors.push({field: 'to', message: 'Enter valid recipient email addresses separated by commas.'});
    }
    if (!data.subject.trim() || data.subject.length > 998 || /[\r\n]/.test(data.subject)) errors.push({field: 'subject', message: 'Enter a subject of up to 998 characters.'});
    const body = new DOMParser().parseFromString(data.body, 'text/html').body;
    if (!body.textContent.replace(/[\u200B-\u200D\uFEFF]/g, '').trim()) errors.push({field: 'body', message: 'Write a message.'});
    if (data.body.length > 100000) errors.push({field: 'body', message: 'Keep the message under 100,000 HTML characters.'});
    return errors;
  }
});
