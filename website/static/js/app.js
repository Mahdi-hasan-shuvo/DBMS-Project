/* Shared UI behaviour for every page. */
(function () {
  'use strict';

  // ---- Record modals: one form handles both "add" and "edit" -----------------
  // Trigger buttons carry data-action (form URL), data-title and optional data-record (JSON).
  document.querySelectorAll('[data-record-modal]').forEach(function (modal) {
    var form = modal.querySelector('form');
    modal.addEventListener('show.bs.modal', function (event) {
      var trigger = event.relatedTarget;
      if (!trigger || !form) return;
      var record = null;
      if (trigger.dataset.record) {
        try { record = JSON.parse(trigger.dataset.record); } catch (e) { record = null; }
      }
      form.reset();
      if (trigger.dataset.action) form.action = trigger.dataset.action;
      var title = modal.querySelector('[data-modal-title]');
      if (title && trigger.dataset.title) title.textContent = trigger.dataset.title;
      modal.querySelectorAll('[data-create-only]').forEach(function (el) { el.classList.toggle('d-none', !!record); });
      modal.querySelectorAll('[data-edit-only]').forEach(function (el) { el.classList.toggle('d-none', !record); });
      if (record) {
        Object.keys(record).forEach(function (key) {
          var field = form.elements.namedItem(key);
          var value = record[key] === null || record[key] === undefined ? '' : record[key];
          if (field && field.type !== 'hidden') field.value = String(value).slice(0, field.type === 'date' ? 10 : undefined);
          modal.querySelectorAll('[data-field-text="' + key + '"]').forEach(function (el) { el.textContent = value; });
        });
      }
      var preset = trigger.dataset.preset;
      if (preset) {
        try {
          var values = JSON.parse(preset);
          Object.keys(values).forEach(function (k) { var f = form.elements.namedItem(k); if (f) f.value = values[k]; });
        } catch (e) { /* ignore */ }
      }
    });
    modal.addEventListener('shown.bs.modal', function () {
      var first = form && form.querySelector('input:not([type=hidden]):not([disabled]), select, textarea');
      if (first) first.focus();
    });
  });

  // Open a modal automatically with ?open=<modalId>
  var params = new URLSearchParams(window.location.search);
  var auto = params.get('open');
  if (auto && document.getElementById(auto) && window.bootstrap) {
    var opener = document.querySelector('[data-bs-target="#' + auto + '"]');
    var m = bootstrap.Modal.getOrCreateInstance(document.getElementById(auto));
    m.show(opener || undefined);
  }

  // ---- Confirm destructive forms ---------------------------------------------
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form.dataset && form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });

  // ---- Selects that navigate (rows per page, quick filters) ------------------
  document.querySelectorAll('[data-nav-select]').forEach(function (sel) {
    sel.addEventListener('change', function () { window.location.href = sel.value; });
  });
  // Filter forms that submit as soon as a select changes
  document.querySelectorAll('form[data-autosubmit] select').forEach(function (sel) {
    sel.addEventListener('change', function () { sel.form.submit(); });
  });

  // ---- SQL syntax highlighting -----------------------------------------------
  var KW = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'INNER', 'ON', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'AS', 'GROUP',
    'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'TABLE',
    'VIEW', 'INDEX', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'CONSTRAINT', 'UNIQUE', 'CHECK', 'DEFAULT', 'CASE', 'WHEN',
    'THEN', 'ELSE', 'END', 'DESC', 'ASC', 'DISTINCT', 'START', 'TRANSACTION', 'COMMIT', 'ROLLBACK', 'FOR', 'CASCADE',
    'RESTRICT', 'DROP', 'IF', 'EXISTS', 'ENGINE', 'INT', 'VARCHAR', 'DECIMAL', 'DATE', 'DATETIME', 'AUTO_INCREMENT',
    'BETWEEN', 'LIKE', 'ESCAPE', 'CHARSET'];
  var FN = ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COALESCE', 'SUBSTR', 'CURRENT_TIMESTAMP', 'LAST_INSERT_ID', 'CURDATE'];
  function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function highlight(sql) {
    var tokens = sql.split(/('(?:[^']|'')*'|--[^\n]*|\b[A-Za-z_]+\b|\?|:[a-z_]+)/g);
    return tokens.map(function (t) {
      if (!t) return '';
      var up = t.toUpperCase();
      if (t.indexOf('--') === 0) return '<span class="cmt">' + escapeHtml(t) + '</span>';
      if (t[0] === "'") return '<span class="str">' + escapeHtml(t) + '</span>';
      if (t === '?' || /^:[a-z_]+$/.test(t)) return '<span class="ph">' + escapeHtml(t) + '</span>';
      if (KW.indexOf(up) !== -1 && t === up) return '<span class="kw">' + t + '</span>';
      if (FN.indexOf(up) !== -1) return '<span class="fn">' + t + '</span>';
      return escapeHtml(t);
    }).join('');
  }
  document.querySelectorAll('pre[data-highlight]').forEach(function (pre) {
    pre.innerHTML = highlight(pre.textContent);
  });

  // ---- Copy buttons ------------------------------------------------------------
  document.querySelectorAll('[data-copy-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = btn.dataset.copyTarget === 'next'
        ? btn.parentElement.nextElementSibling
        : document.querySelector(btn.dataset.copyTarget);
      if (!target) return;
      var text = target.textContent;
      var done = function () {
        var old = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2 me-1"></i>Copied';
        setTimeout(function () { btn.innerHTML = old; }, 1400);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done); else done();
    });
  });

  // ---- Keyboard: "/" focuses global search -----------------------------------
  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    if (e.key === '/' && tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
      var s = document.getElementById('globalSearch');
      if (s) { e.preventDefault(); s.focus(); }
    }
  });

  // ---- Print buttons -----------------------------------------------------------
  document.querySelectorAll('[data-print]').forEach(function (b) {
    b.addEventListener('click', function () { window.print(); });
  });

  // Auto-hide success flashes
  setTimeout(function () {
    document.querySelectorAll('.flash-stack .alert-success').forEach(function (el) {
      if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(el).close();
    });
  }, 6000);
})();
