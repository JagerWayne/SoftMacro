/* Shared key picker used by the Settings hotkey fields and the macro
 * command builder.
 *
 * Chips insert into the input named by the reference's `data-target`
 * selector, or into the .hotkey-field that was focused last when no
 * target is set. Single keys append with '+' (ctrl, shift, r ->
 * ctrl+shift+r); full-combo chips replace the value. The search box
 * filters keys and opens the full list.
 */
(function () {
  'use strict';

  let lastHotkeyField = null;

  document.querySelectorAll('.hotkey-field').forEach(function (input) {
    input.addEventListener('focus', function () {
      lastHotkeyField = input;
    });
  });

  function targetFor(ref) {
    const selector = ref.dataset.target;
    if (selector) return document.querySelector(selector);
    return lastHotkeyField || document.querySelector('.hotkey-field');
  }

  function filterChips(ref, query) {
    const q = (query || '').trim().toLowerCase();
    ref.querySelectorAll('.key-group, .combo-row').forEach(function (row) {
      let visible = 0;
      row.querySelectorAll('.key-chip').forEach(function (chip) {
        const match = !q || (chip.dataset.insert || '').toLowerCase().includes(q);
        chip.hidden = !match;
        if (match) visible += 1;
      });
      row.hidden = q !== '' && visible === 0;
    });
  }

  document.querySelectorAll('.key-reference').forEach(function (ref) {
    const search = ref.querySelector('.key-search');
    const groups = ref.querySelector('.key-groups-wrap');

    if (search) {
      search.addEventListener('input', function () {
        if (search.value && groups) groups.open = true;
        filterChips(ref, search.value);
      });
    }

    const clear = ref.querySelector('.key-clear');
    if (clear) {
      clear.addEventListener('click', function () {
        const field = targetFor(ref);
        if (!field) return;
        field.value = '';
        field.focus();
      });
    }

    ref.querySelectorAll('.key-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        const field = targetFor(ref);
        if (!field) return;
        const key = chip.dataset.insert || '';
        if (chip.classList.contains('combo')) {
          field.value = key;
        } else {
          const current = field.value.trim();
          field.value = current ? current + '+' + key : key;
        }
        field.focus();
        if (field.classList.contains('hotkey-field')) lastHotkeyField = field;
      });
    });
  });
})();
