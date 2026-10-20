// Forms implement defaults, render(data), collect(), and validate(data).
let definition;
let envelope;
let token;
let tail = Promise.resolve();
let pending = null;
let failed = false;
let active = false;
let dirty = false;
const status = () => document.querySelector('[data-status]');
const setStatus = message => { status().textContent = message; };
function setFieldsDisabled(disabled) {
  document.querySelector('[data-fields]').disabled = disabled;
  for (const button of document.querySelectorAll('button[data-action]')) button.disabled = disabled;
}
const clone = value => JSON.parse(JSON.stringify(value));

let validationTimer;
const validationFields = new Map();
function clearValidation() {
  clearTimeout(validationTimer);
  const hadErrors = [...validationFields.values()].some(item => !item.message.hidden);
  for (const {field, frame, message} of validationFields.values()) {
    field.removeAttribute('aria-invalid');
    frame.classList.remove('field-invalid');
    message.textContent = '';
    message.hidden = true;
  }
  if (hadErrors) setStatus(dirty ? 'Unsaved changes · use a form button to save' : 'Ready · use a form button to save changes');
}
function prepareValidation() {
  for (const field of document.querySelectorAll('[data-fields] input, [data-fields] textarea, [data-fields] [role="textbox"]')) {
    const frame = document.createElement('div');
    frame.className = 'field-frame';
    const surface = field.closest('.editor-shell') || field;
    surface.before(frame);
    frame.append(surface);
    const message = document.createElement('div');
    message.id = `${field.id}-validation`;
    message.className = 'field-error';
    message.hidden = true;
    frame.append(message);
    field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), message.id].filter(Boolean).join(' '));
    validationFields.set(field.id, {field, frame, message});
  }
  // Capture before button handlers so the triggering submit can display fresh errors.
  for (const type of ['pointerdown', 'click', 'keydown', 'input', 'change']) {
    document.querySelector('main').addEventListener(type, clearValidation, true);
  }
}
function showValidation(errors) {
  clearValidation();
  for (const error of errors) {
    const item = validationFields.get(error.field);
    if (!item) throw new Error(`Unknown validation field: ${error.field}`);
    item.field.setAttribute('aria-invalid', 'true');
    item.frame.classList.add('field-invalid');
    item.message.textContent += (item.message.textContent ? ' ' : '') + error.message;
    item.message.hidden = false;
  }
  validationFields.get(errors[0].field).field.focus();
  setStatus('Please correct the highlighted fields.');
  validationTimer = setTimeout(clearValidation, 60000);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {'X-Forms-Token': token, 'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Save failed');
  return value;
}

function sessionPath() {
  const meta = envelope.meta_data;
  return `/api/sessions/${meta.form}/${meta.execution_id}`;
}

async function save(request) {
  setStatus('Saving…');
  envelope = await api(`${sessionPath()}/actions?view=current`, request);
  pending = null;
  const submitted = envelope.meta_data.execution_state === 'submitted';
  if (submitted) setFieldsDisabled(true);
  setStatus(submitted ? 'Submitted and saved.' : `Saved · revision ${envelope.meta_data.revision}`);
}

export function action(name, data = definition.collect(), outcome = 'accepted') {
  if (!active || failed) return Promise.resolve(false);
  const buttons = [...document.querySelectorAll('button[data-action]')];
  if (buttons.filter(button => button.dataset.action === name).length !== 1) {
    throw new Error('Each action must map to exactly one form button');
  }
  const snapshot = clone(data);
  setFieldsDisabled(true);
  tail = tail.then(async () => {
    if (failed) return false;
    const request = {action_id: crypto.randomUUID(), expected_revision: envelope.meta_data.revision,
      action_name: name, data: snapshot, outcome};
    pending = request;
    try {
      await save(request);
      dirty = false;
      setFieldsDisabled(envelope.meta_data.execution_state === 'submitted');
      return true;
    } catch (error) {
      failed = true;
      setFieldsDisabled(true);
      document.querySelector('[data-retry]').hidden = false;
      setStatus(`${error.message}. Your last action is pending; retry, or reload to recover saved data.`);
      return false;
    }
  });
  return tail;
}

export async function mount(formDefinition) {
  definition = formDefinition;
  prepareValidation();
  const infoButton = document.querySelector('[data-info]');
  const infoPanel = document.querySelector('[data-info-panel]');
  if (infoButton && infoPanel) {
    const showInfo = open => {
      infoPanel.hidden = !open;
      infoButton.setAttribute('aria-expanded', String(open));
    };
    infoButton.addEventListener('click', () => showInfo(infoPanel.hidden));
    document.addEventListener('click', event => {
      if (!infoButton.contains(event.target) && !infoPanel.contains(event.target)) showInfo(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !infoPanel.hidden) {
        showInfo(false);
        infoButton.focus();
      }
    });
  }
  try {
    token = (await (await fetch('/runtime/config.json')).json()).token;
    const parts = location.pathname.split('/').filter(Boolean);
    if (parts[0] === 'new') {
      // Optional initial values supplied in URL fragment, never sent in the URL request.
      const supplied = location.hash ? JSON.parse(decodeURIComponent(location.hash.slice(1))) : {};
      if (!supplied || typeof supplied !== 'object' || Array.isArray(supplied)) throw new Error('Initial data must be an object');
      const initial = {...clone(definition.defaults), ...supplied};
      definition.render(initial);
      envelope = await api('/api/sessions?view=current', {form: parts[1], raw_input: '', initial_data: definition.collect()});
      history.replaceState(null, '', `/session/${parts[1]}/${envelope.meta_data.execution_id}`);
    } else {
      envelope = await api(`/api/sessions/${parts[1]}/${parts[2]}?view=current`);
      definition.render({...clone(definition.defaults), ...clone(envelope.meta_data.current_data)});
    }
    document.querySelector('[data-session]').textContent = envelope.meta_data.execution_id;
    document.querySelector('[data-new]').href = `/new/${envelope.meta_data.form}`;
    active = true;
    setFieldsDisabled(envelope.meta_data.execution_state === 'submitted');
    setStatus(envelope.meta_data.execution_state === 'submitted' ? 'Submitted and saved.' : 'Ready · use a form button to save changes');
    const form = document.querySelector('form');
    const buttons = [...document.querySelectorAll('button[data-action]')].filter(button => button.form === form);
    const names = buttons.map(button => button.dataset.action);
    if (names.some(name => !/^[a-z][a-z0-9_]{0,63}$/.test(name)) || new Set(names).size !== names.length ||
        buttons.some(button => (button.type === 'submit') !== (button.dataset.action === 'submit'))) {
      throw new Error('Action buttons require unique valid names; the submit button must use submit');
    }
    form.addEventListener('input', () => {
      dirty = true;
      setStatus('Unsaved changes · use a form button to save');
    });
    for (const button of buttons) {
      if (button.type === 'button' && button.dataset.action === 'save_draft') {
        button.addEventListener('click', () => { void action('save_draft'); });
      }
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (failed || envelope.meta_data.execution_state === 'submitted') return;
      const button = event.submitter || buttons.find(button => button.type === 'submit');
      if (!button || button.dataset.action !== 'submit') return;
      const data = clone(definition.collect());
      const errors = definition.validate(data);
      if (errors.length) {
        showValidation(errors);
        return;
      }
      // Freeze editing while submission waits behind earlier actions.
      setFieldsDisabled(true);
      await action('submit', data);
    });
    document.querySelector('[data-retry]').addEventListener('click', async () => {
      if (!pending) return;
      try {
        await save(pending); // Same action ID: a lost acknowledgement cannot duplicate history.
        failed = false;
        dirty = false;
        definition.render(clone(envelope.meta_data.current_data));
        setFieldsDisabled(envelope.meta_data.execution_state === 'submitted');
        document.querySelector('[data-retry]').hidden = true;
      } catch (error) { setStatus(`${error.message}. Retry or reload this session.`); }
    });
    window.addEventListener('beforeunload', event => {
      if (dirty || pending || failed) { event.preventDefault(); event.returnValue = ''; }
    });
  } catch (error) { setStatus(`Unable to open form: ${error.message}`); }
}
