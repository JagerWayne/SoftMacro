/* Client-side event editor for the New/Edit macro page.
 *
 * State lives in a single `events` array of {ts, kind, payload} objects.
 * The form's `#events-json` textarea is kept in sync on every change.
 * Quick Add posts the command to /parse, then appends the returned events.
 *
 * Two safety nets ensure edits are never lost on save:
 *   1. live `change` event delegation on the table body, and
 *   2. a form `submit` handler that rebuilds `events` from the live table
 *      DOM right before the POST, so even a missed change event can't
 *      leave the textarea stale.
 */

(function () {
  'use strict';

  // ----------------------------------------------------------- state

  let events = [];            // [{ts, kind, payload}]
  let nextDelay = 50;         // ms between successive added events

  const KINDS = [
    'key_down', 'key_up',
    'mouse_down', 'mouse_up',
    'mouse_move',
    'scroll',
    'delay',
  ];

  // ----------------------------------------------------------- DOM

  const $tbody      = document.querySelector('#events-table tbody');
  const $hidden     = document.getElementById('events-json');
  const $delay      = document.getElementById('delay-input');
  const $toast      = document.getElementById('quick-add-toast');
  const $quickAdd   = document.getElementById('quick-add');
  const $form       = document.getElementById('macro-form');
  const scriptTag   = document.currentScript || document.querySelector('script[data-parse-url]');
  const ds          = scriptTag ? scriptTag.dataset : {};
  const PARSE_URL   = ds.parseUrl || '/parse';

  if ($delay) {
    nextDelay = parseInt($delay.value, 10) || 50;
    $delay.addEventListener('change', () => {
      nextDelay = parseInt($delay.value, 10) || 0;
    });
  }

  // Pre-fill from server-provided initial events_json (if any).
  if ($hidden && $hidden.value.trim()) {
    try {
      const parsed = JSON.parse($hidden.value);
      events = parsed.map(([ts, [kind, payload]]) => ({ ts, kind, payload }));
    } catch (e) {
      console.warn('initial events JSON invalid:', e);
    }
  }
  render();

  // --------------------------------------------------- live table edits

  // Delegated handler: any change in the table updates state immediately.
  $tbody.addEventListener('change', (e) => {
    const cell = e.target;
    const tr = cell.closest('tr[data-i]');
    if (!tr) return;
    const i = parseInt(tr.dataset.i, 10);
    if (!events[i]) return;

    if (cell.classList.contains('ts')) {
      events[i].ts = parseInt(cell.value, 10) || 0;
    } else if (cell.classList.contains('kind')) {
      events[i].kind = cell.value;
    } else if (cell.classList.contains('payload')) {
      events[i].payload = parsePayload(cell.value);
    }
    syncHidden();
  });

  // Bulletproof: rebuild state from the live DOM right before submit.
  if ($form) {
    $form.addEventListener('submit', () => {
      syncFromDom();
    });
  }

  function syncFromDom() {
    const rebuilt = [];
    $tbody.querySelectorAll('tr[data-i]').forEach(tr => {
      const tsInput     = tr.querySelector('.ts');
      const kindSel     = tr.querySelector('.kind');
      const payloadInput= tr.querySelector('.payload');
      if (!tsInput || !kindSel || !payloadInput) return;
      rebuilt.push({
        ts: parseInt(tsInput.value, 10) || 0,
        kind: kindSel.value,
        payload: parsePayload(payloadInput.value),
      });
    });
    events = rebuilt;
    syncHidden();
  }

  // ----------------------------------------------------------- quick add

  async function quickAdd() {
    const cmd = ($quickAdd.value || '').trim();
    if (!cmd) return;
    setToast('Parsing…', 'info');

    let data;
    try {
      const r = await fetch(PARSE_URL, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'cmd=' + encodeURIComponent(cmd),
      });
      data = await r.json();
    } catch (e) {
      setToast('Network error: ' + e, 'error');
      return;
    }

    if (data.error) {
      setToast(data.error, 'error');
      return;
    }
    if (!data.events || !data.events.length) {
      setToast('No events produced.', 'error');
      return;
    }

    // Append with auto-incrementing timestamps.
    let ts = events.length ? events[events.length - 1].ts : 0;
    for (const [kind, payload] of data.events) {
      ts += nextDelay;
      events.push({ ts, kind, payload });
    }
    $quickAdd.value = '';
    render();
    setToast(`Added ${data.events.length} event${data.events.length === 1 ? '' : 's'}.`, 'success');
  }
  window.quickAdd = quickAdd;

  // ------------------------------------------------------ command builder

  function fieldValue(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }

  function commandFor(kind) {
    switch (kind) {
      case 'key': {
        const combo = ($quickAdd.value || '').trim();
        return combo ? {cmd: combo} : {error: 'Click some keys first.'};
      }
      case 'type': {
        const text = fieldValue('cmd-type-text');
        if (!text) return {error: 'Enter the text to type.'};
        return {cmd: 'Type "' + text.replace(/"/g, '') + '"'};
      }
      case 'wait': {
        const ms = parseInt(fieldValue('cmd-wait-ms'), 10);
        if (!Number.isFinite(ms) || ms < 0) return {error: 'Enter a wait time in ms.'};
        return {cmd: 'Wait ' + ms};
      }
      case 'click': {
        const button = fieldValue('cmd-click-button') || 'left';
        const x = fieldValue('cmd-click-x');
        const y = fieldValue('cmd-click-y');
        if ((x === '') !== (y === '')) {
          return {error: 'Enter both X and Y, or leave both empty.'};
        }
        const coords = x !== '' ? ' ' + parseInt(x, 10) + ' ' + parseInt(y, 10) : '';
        const name = button === 'left'
          ? 'Click'
          : button.charAt(0).toUpperCase() + button.slice(1) + ' click';
        return {cmd: name + coords};
      }
      case 'move': {
        const x = fieldValue('cmd-move-x');
        const y = fieldValue('cmd-move-y');
        if (x === '' || y === '') return {error: 'Enter both X and Y.'};
        return {cmd: 'Move ' + parseInt(x, 10) + ' ' + parseInt(y, 10)};
      }
      case 'scroll': {
        const dir = fieldValue('cmd-scroll-dir') || 'down';
        const count = parseInt(fieldValue('cmd-scroll-count'), 10) || 1;
        return {cmd: 'Scroll ' + dir + (count > 1 ? ' ' + count : '')};
      }
      case 'hold': {
        const action = fieldValue('cmd-hold-action') || 'Hold';
        const key = fieldValue('cmd-hold-key');
        if (!key) return {error: 'Enter the key to hold or release.'};
        return {cmd: action + ' ' + key};
      }
      default:
        return {error: 'Unknown command type.'};
    }
  }

  async function addCommand(kind) {
    const built = commandFor(kind);
    if (built.error) {
      setToast(built.error, 'error');
      return;
    }
    $quickAdd.value = built.cmd;
    await quickAdd();
    if (kind === 'type') {
      const el = document.getElementById('cmd-type-text');
      if (el) el.value = '';
    }
    if (kind === 'hold') {
      const el = document.getElementById('cmd-hold-key');
      if (el) el.value = '';
    }
  }

  document.querySelectorAll('[data-cmd-add]').forEach((btn) => {
    btn.addEventListener('click', () => addCommand(btn.dataset.cmdAdd));
  });

  function setToast(msg, kind) {
    if (!$toast) return;
    $toast.textContent = msg;
    $toast.className = 'toast ' + (kind || 'info');
    clearTimeout(setToast._t);
    setToast._t = setTimeout(() => {
      $toast.className = 'toast';
      $toast.textContent = '';
    }, 4000);
  }

  // ----------------------------------------------------------- render

  function render() {
    if (!events.length) {
      $tbody.innerHTML = '<tr class="empty-row"><td colspan="5">No events yet. Use Quick Add above or paste JSON below.</td></tr>';
    } else {
      const rows = events.map((ev, i) => rowHtml(ev, i)).join('');
      $tbody.innerHTML = rows;
    }
    syncHidden();
  }

  function rowHtml(ev, i) {
    const kindOptions = KINDS.map(k =>
      `<option value="${k}"${ev.kind === k ? ' selected' : ''}>${k}</option>`
    ).join('');
    const payloadStr = JSON.stringify(ev.payload);
    return `
      <tr data-i="${i}">
        <td class="num">${i + 1}</td>
        <td><input type="number" class="cell-input ts"
                   value="${ev.ts}" min="0" step="1"
                   onchange="eventsEditor.update(${i}, 'ts', parseInt(this.value, 10) || 0)"></td>
        <td><select class="cell-input kind"
                    onchange="eventsEditor.update(${i}, 'kind', this.value)">${kindOptions}</select></td>
        <td><input type="text" class="cell-input payload"
                   value="${escapeAttr(payloadStr)}"
                   onchange="eventsEditor.update(${i}, 'payload', parsePayload(this.value))"></td>
        <td><button type="button" class="btn small danger"
                    onclick="eventsEditor.remove(${i})" aria-label="Delete event">×</button></td>
      </tr>`;
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function parsePayload(text) {
    // Try JSON first (handles objects, arrays, numbers, booleans, quoted strings).
    try { return JSON.parse(text); } catch (e) { /* fall through */ }
    // Bare bareword -> string.
    return text;
  }

  function syncHidden() {
    if (!$hidden) return;
    $hidden.value = JSON.stringify(events.map(e => [e.ts, [e.kind, e.payload]]));
  }

  // Public API for inline event handlers.
  window.eventsEditor = {
    update(i, field, value) {
      if (!events[i]) return;
      events[i][field] = value;
      syncHidden();
    },
    remove(i) {
      events.splice(i, 1);
      render();
    },
    add(ts, kind, payload) {
      events.push({ ts, kind, payload });
      render();
    },
    reset() {
      events = [];
      render();
    },
  };
})();
