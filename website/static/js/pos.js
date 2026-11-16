/* POS terminal: client-side cart; the server re-validates stock and prices on checkout. */
(function () {
  'use strict';
  var data = JSON.parse(document.getElementById('posData').textContent);
  var meds = data.medicines, currency = data.currency, taxRate = data.taxRate;
  var byId = {};
  meds.forEach(function (m) { byId[m.medicine_id] = m; });
  var customers = {};
  data.customers.forEach(function (c) { customers[c.customer_id] = c; });

  var cart = [];          // [{id, qty}]
  var category = '';
  var focusIndex = 0;
  var visible = [];
  var method = 'Cash';
  var busy = false;

  var $ = function (id) { return document.getElementById(id); };
  var search = $('posSearch'), results = $('posResults'), cartLines = $('cartLines');
  var paidInput = $('posPaid'), discountInput = $('posDiscount'), customerSel = $('posCustomer');

  function money(v) {
    return currency + (Math.round(v * 100) / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtExp(d) { return d ? d.slice(5, 7) + '/' + d.slice(0, 4) : '—'; }
  function inCart(id) { for (var i = 0; i < cart.length; i++) if (cart[i].id === id) return cart[i]; return null; }

  // ------------------------------------------------------------ result list
  function renderResults() {
    var q = search.value.trim().toLowerCase();
    visible = meds.filter(function (m) {
      if (category && String(m.category_id) !== category) return false;
      if (!q) return true;
      return [m.medicine_name, m.generic_name, m.sku, m.batch_no].some(function (v) {
        return v && String(v).toLowerCase().indexOf(q) !== -1;
      });
    });
    if (focusIndex >= visible.length) focusIndex = Math.max(visible.length - 1, 0);
    $('matchCount').textContent = 'Showing ' + visible.length + ' match' + (visible.length === 1 ? '' : 'es');
    if (!visible.length) {
      results.innerHTML = '<div class="empty"><i class="bi bi-search"></i>No medicines match “' + esc(search.value) + '”.</div>';
      return;
    }
    results.innerHTML = visible.map(function (m, i) {
      var line = inCart(m.medicine_id);
      var left = m.stock_quantity - (line ? line.qty : 0);
      var disabled = m.expired || m.stock_quantity <= 0;
      var stockPill;
      if (m.expired) stockPill = '<span class="pill pill-danger">Expired</span>';
      else if (m.stock_quantity <= 0) stockPill = '<span class="pill pill-danger">0 Out of stock</span>';
      else if (m.stock_quantity <= m.reorder_level) stockPill = '<span class="pill pill-warning">' + m.stock_quantity + ' in stock (Low)</span>';
      else stockPill = '<span class="pill pill-success">' + m.stock_quantity + ' in stock</span>';
      var btn = disabled
        ? '<button type="button" class="btn btn-soft btn-sm" disabled><i class="bi bi-slash-circle me-1"></i>' + (m.expired ? 'Blocked' : 'Depleted') + '</button>'
        : '<button type="button" class="btn btn-brand btn-sm text-nowrap" data-add="' + m.medicine_id + '"' + (left <= 0 ? ' disabled' : '') + '><i class="bi bi-cart-plus me-1"></i>Add</button>';
      return '<div class="pos-item' + (disabled ? ' disabled' : '') + (i === focusIndex ? ' focused' : '') + '" role="option" data-index="' + i + '">' +
        '<span class="pos-thumb"><i class="bi ' + (disabled ? 'bi-slash-circle' : 'bi-capsule') + '"></i></span>' +
        '<div class="flex-grow-1 min-w-0">' +
          '<div class="d-flex flex-wrap align-items-center gap-2"><span class="pos-name">' + esc(m.medicine_name) + '</span>' +
          '<span class="id-chip gray">MED-' + String(m.medicine_id).padStart(4, '0') + '</span>' + stockPill + '</div>' +
          '<div class="cell-sub">Generic: <b>' + esc(m.generic_name || '—') + '</b> · Lot: ' + esc(m.batch_no || 'N/A') + ' · Exp: ' + fmtExp(m.expiry_date) + '</div>' +
        '</div>' +
        '<div class="text-end me-2"><div class="pos-price">' + money(m.price) + '</div><div class="tw-text-[11px] text-muted-2">' + esc(m.dosage_form || 'Unit') + '</div></div>' +
        btn + '</div>';
    }).join('');
    var focused = results.querySelector('.pos-item.focused');
    if (focused && document.activeElement === search) focused.scrollIntoView({ block: 'nearest' });
  }

  results.addEventListener('click', function (e) {
    var b = e.target.closest('[data-add]');
    if (b) add(+b.dataset.add);
  });

  document.querySelectorAll('#catChips .chip-filter').forEach(function (chip) {
    chip.addEventListener('click', function () {
      document.querySelectorAll('#catChips .chip-filter').forEach(function (c) { c.classList.remove('active'); });
      chip.classList.add('active');
      category = chip.dataset.cat;
      focusIndex = 0;
      renderResults();
    });
  });
  search.addEventListener('input', function () { focusIndex = 0; renderResults(); });
  search.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusIndex = Math.min(focusIndex + 1, visible.length - 1); renderResults(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusIndex = Math.max(focusIndex - 1, 0); renderResults(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      var m = visible[focusIndex];
      if (m) add(m.medicine_id);
    }
  });

  // ------------------------------------------------------------------- cart
  function add(id) {
    var m = byId[id];
    if (!m || m.expired || m.stock_quantity <= 0) return;
    var line = inCart(id);
    if (line) { if (line.qty < m.stock_quantity) line.qty += 1; }
    else cart.push({ id: id, qty: 1 });
    hideError();
    renderAll();
  }
  function setQty(id, qty) {
    var m = byId[id], line = inCart(id);
    if (!line) return;
    qty = Math.max(1, Math.min(parseInt(qty, 10) || 1, m.stock_quantity));
    line.qty = qty;
    renderAll();
  }
  function remove(id) { cart = cart.filter(function (l) { return l.id !== id; }); renderAll(); }

  function totals() {
    var sub = 0, items = 0;
    cart.forEach(function (l) { sub += byId[l.id].price * l.qty; items += l.qty; });
    sub = Math.round(sub * 100) / 100;
    var pct = Math.min(Math.max(parseFloat(discountInput.value) || 0, 0), 100);
    var discount = Math.round(sub * pct) / 100;
    var tax = Math.round((sub - discount) * taxRate * 100) / 100;
    return { sub: sub, items: items, discount: discount, tax: tax, total: Math.round((sub - discount + tax) * 100) / 100 };
  }

  function renderCart() {
    if (!cart.length) {
      cartLines.innerHTML = '<div class="empty py-4"><i class="bi bi-cart"></i>Cart is empty. Search and add medicines.</div>';
    } else {
      cartLines.innerHTML = cart.map(function (l) {
        var m = byId[l.id];
        return '<div class="cart-line">' +
          '<div class="d-flex justify-content-between gap-2"><div><div class="fw-bold">' + esc(m.medicine_name) + '</div>' +
          '<div class="cell-sub">' + money(m.price) + ' per unit · Max stock: ' + m.stock_quantity + '</div></div>' +
          '<button type="button" class="btn-icon danger" data-remove="' + l.id + '" aria-label="Remove ' + esc(m.medicine_name) + '"><i class="bi bi-trash3"></i></button></div>' +
          '<div class="d-flex justify-content-between align-items-center mt-2"><div class="qty-box">' +
          '<button type="button" data-dec="' + l.id + '" aria-label="Decrease">−</button>' +
          '<input type="number" min="1" max="' + m.stock_quantity + '" value="' + l.qty + '" data-qty="' + l.id + '" aria-label="Quantity">' +
          '<button type="button" data-inc="' + l.id + '" aria-label="Increase">+</button></div>' +
          '<span class="num fw-bold fs-6">' + money(m.price * l.qty) + '</span></div></div>';
      }).join('');
    }
    var count = cart.length;
    $('cartCount').textContent = count + (count === 1 ? ' item' : ' items');
  }

  cartLines.addEventListener('click', function (e) {
    var t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.remove) remove(+t.dataset.remove);
    if (t.dataset.inc) { var l = inCart(+t.dataset.inc); setQty(+t.dataset.inc, l.qty + 1); }
    if (t.dataset.dec) { var d = inCart(+t.dataset.dec); setQty(+t.dataset.dec, d.qty - 1); }
  });
  cartLines.addEventListener('change', function (e) {
    if (e.target.dataset.qty) setQty(+e.target.dataset.qty, e.target.value);
  });

  function renderSummary() {
    var t = totals();
    $('sumItems').textContent = t.items;
    $('sumSubtotal').textContent = money(t.sub);
    $('sumDiscount').textContent = '-' + money(t.discount);
    $('sumTax').textContent = money(t.tax);
    $('sumTotal').textContent = money(t.total);
    // quick tender buttons
    var opts = ['Exact'];
    [Math.ceil(t.total / 5) * 5, Math.ceil(t.total / 10) * 10, Math.ceil(t.total / 50) * 50].forEach(function (v) {
      if (v > t.total && opts.indexOf(v) === -1) opts.push(v);
    });
    $('quickPaid').innerHTML = t.total > 0 ? opts.slice(0, 4).map(function (v) {
      return '<button type="button" class="btn btn-soft btn-sm py-0 px-2 mono" data-paid="' + (v === 'Exact' ? t.total : v) + '">' +
        (v === 'Exact' ? 'Exact' : currency + v) + '</button>';
    }).join('') : '';
    var paid = paidInput.value === '' ? t.total : parseFloat(paidInput.value) || 0;
    var change = paid - t.total;
    $('posChange').textContent = money(Math.max(change, 0));
    $('completeSale').disabled = !cart.length || busy || paid + 0.0001 < t.total;
    $('completeSale').innerHTML = '<i class="bi bi-check-circle-fill me-2"></i>Complete Sale' +
      (cart.length ? ' (' + money(t.total) + ')' : '') + ' &amp; Print Invoice [F9]';
  }
  $('quickPaid').addEventListener('click', function (e) {
    var b = e.target.closest('[data-paid]');
    if (b) { paidInput.value = (+b.dataset.paid).toFixed(2); renderSummary(); }
  });
  paidInput.addEventListener('input', renderSummary);
  discountInput.addEventListener('input', renderSummary);

  document.querySelectorAll('#payMethods .pay-opt').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('#payMethods .pay-opt').forEach(function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      method = b.dataset.method;
    });
  });

  $('clearCart').addEventListener('click', function () {
    if (cart.length && !window.confirm('Remove all items from the cart?')) return;
    cart = []; paidInput.value = ''; renderAll();
  });

  // --------------------------------------------------------------- allergy
  var ALLERGY_TERMS = {
    penicillin: ['penicillin', 'amoxicillin', 'ampicillin', 'clavulanic', 'amoxil', 'augmentin'],
    aspirin: ['aspirin', 'ecosprin'],
    codeine: ['codeine', 'tramadol'],
    sulfa: ['sulfa', 'sulfamethoxazole']
  };
  function renderAllergy() {
    var box = $('allergyAlert');
    var c = customers[customerSel.value];
    if (!c || !c.allergies) { box.classList.add('d-none'); return; }
    var allergy = c.allergies.toLowerCase();
    var terms = [allergy];
    Object.keys(ALLERGY_TERMS).forEach(function (k) { if (allergy.indexOf(k) !== -1) terms = terms.concat(ALLERGY_TERMS[k]); });
    var conflicts = cart.filter(function (l) {
      var m = byId[l.id], text = ((m.medicine_name || '') + ' ' + (m.generic_name || '')).toLowerCase();
      return terms.some(function (t) { return t && text.indexOf(t) !== -1; });
    }).map(function (l) { return byId[l.id].medicine_name; });
    box.innerHTML = '<i class="bi bi-exclamation-triangle-fill me-2"></i><b>CLINICAL ALERT:</b> ' + esc(c.customer_name) +
      ' has a documented allergy to <u><b>' + esc(c.allergies) + '</b></u>.' +
      (conflicts.length ? ' <b>' + esc(conflicts.join(', ')) + '</b> in the cart may conflict. Pharmacist consultation required.' : ' Check every item before dispensing.');
    box.classList.remove('d-none');
  }
  customerSel.addEventListener('change', renderAllergy);

  // Re-entrancy guard: replacing the cart HTML blurs a focused qty input, which fires
  // another "change" while the old nodes are being removed.
  var rendering = false;
  function renderAll() {
    if (rendering) return;
    rendering = true;
    try { renderResults(); renderCart(); renderSummary(); renderAllergy(); }
    finally { rendering = false; }
  }

  // -------------------------------------------------------------- checkout
  function showError(msg) { var e = $('posError'); e.textContent = msg; e.classList.remove('d-none'); }
  function hideError() { $('posError').classList.add('d-none'); }

  function checkout() {
    if (busy || !cart.length) return;
    var t = totals();
    var paid = paidInput.value === '' ? t.total : parseFloat(paidInput.value) || 0;
    if (paid + 0.0001 < t.total) { showError('Amount paid is less than the grand total.'); return; }
    busy = true; renderSummary();
    $('completeSale').innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Committing transaction…';
    fetch(data.checkoutUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer_id: customerSel.value || null,
        items: cart.map(function (l) { return { medicine_id: l.id, quantity: l.qty }; }),
        payment_method: method,
        amount_paid: paid,
        discount_percent: parseFloat(discountInput.value) || 0,
        prescription_ref: $('posRx').value
      })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (res.ok && res.body.ok) { window.location.href = res.body.redirect; return; }
        busy = false; showError(res.body.error || 'The sale could not be completed.'); renderSummary();
      })
      .catch(function () { busy = false; showError('Network error: the sale was not saved.'); renderSummary(); });
  }
  $('completeSale').addEventListener('click', checkout);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); search.focus(); search.select(); }
    else if (e.key === 'F4') { e.preventDefault(); customerSel.focus(); }
    else if (e.key === 'F9') { e.preventDefault(); checkout(); }
  });

  // ------------------------------------------------------ quick new patient
  var quickForm = document.querySelector('form[data-quick-customer]');
  if (quickForm) {
    quickForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var err = quickForm.querySelector('[data-form-error]');
      err.classList.add('d-none');
      fetch(quickForm.action, { method: 'POST', body: new FormData(quickForm) })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res.ok) { err.textContent = res.error; err.classList.remove('d-none'); return; }
          var c = res.customer;
          customers[c.customer_id] = c;
          var opt = document.createElement('option');
          opt.value = c.customer_id;
          opt.textContent = c.customer_name + ' (CUS-' + String(c.customer_id).padStart(4, '0') + ')';
          customerSel.appendChild(opt);
          customerSel.value = c.customer_id;
          renderAllergy();
          bootstrap.Modal.getInstance(document.getElementById('customerModal')).hide();
        })
        .catch(function () { err.textContent = 'Could not save the customer.'; err.classList.remove('d-none'); });
    });
  }

  if (data.preselect && customers[data.preselect]) customerSel.value = data.preselect;
  renderAll();
  search.focus();
})();
