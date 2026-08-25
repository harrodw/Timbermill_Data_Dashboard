/* ==========================================================================
   validation.js -- BirdNET validation progress (bird_frog_audio only).

   Source: data/birdnet.json .validation (overall) and .species[] per-species
   fields (n_detections, validation_target, n_validated, n_true_positive,
   precision, pct_of_target). Progress is currently 0%; the empty state has to
   read as "not started", not as an error or a missing panel.
   ========================================================================== */

import { $, el, clear, fmtInt, fmtNum, fmtPct, showPanelError, hidePanelError } from './data.js';

const COLUMNS = [
  { key: 'name',             label: 'Species',        text: true },
  { key: 'klass',            label: 'Class',          text: true },
  { key: 'n_detections',     label: 'Detections' },
  { key: 'validation_target',label: 'Target' },
  { key: 'n_validated',      label: 'Validated' },
  { key: 'n_true_positive',  label: 'True positive' },
  { key: 'precision',        label: 'Precision' },
  { key: 'pct_of_target',    label: '% of target' }
];

let sortKey = 'n_detections';
let sortDir = -1;
let boundHead = false;

/** Rows for the table: wildlife species that carry a validation target. */
export function validationRows(birdnet) {
  const species = (birdnet && Array.isArray(birdnet.species)) ? birdnet.species : [];
  return species
    .filter(s => s.class && s.class !== 'Anthropogenic')
    .map(s => ({
      name: s.species,
      latin: s.latin_name,
      klass: s.class,
      n_detections: num(s.n_detections),
      validation_target: num(s.validation_target),
      n_validated: num(s.n_validated),
      n_true_positive: num(s.n_true_positive),
      precision: s.precision === null || s.precision === undefined ? null : Number(s.precision),
      pct_of_target: num(s.pct_of_target)
    }));
}

function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }

export function sortRows(rows, key, dir) {
  const col = COLUMNS.find(c => c.key === key) || COLUMNS[2];
  return rows.slice().sort((a, b) => {
    const av = a[col.key], bv = b[col.key];
    if (col.text) return dir * String(av ?? '').localeCompare(String(bv ?? ''));
    const an = av === null ? -Infinity : Number(av);
    const bn = bv === null ? -Infinity : Number(bv);
    return dir * (an - bn) || String(a.name).localeCompare(String(b.name));
  });
}

function renderHead() {
  const head = $('#validation-head');
  if (!head) return;
  clear(head);
  for (const col of COLUMNS) {
    const th = el('th', col.text ? 'txt' : null);
    th.scope = 'col';
    th.dataset.key = col.key;
    th.setAttribute('role', 'button');
    th.tabIndex = 0;
    th.setAttribute('aria-sort',
      sortKey === col.key ? (sortDir === -1 ? 'descending' : 'ascending') : 'none');
    th.appendChild(el('span', null, col.label));
    if (sortKey === col.key) {
      th.appendChild(el('span', 'arrow', sortDir === -1 ? ' \u25be' : ' \u25b4'));
    }
    head.appendChild(th);
  }
}

function renderBody(rows) {
  const body = $('#validation-body');
  if (!body) return;
  clear(body);
  if (!rows.length) {
    const tr = el('tr');
    const td = el('td', 'txt', 'No species rows in birdnet.json .species[].');
    td.colSpan = COLUMNS.length;
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const r of sortRows(rows, sortKey, sortDir)) {
    const tr = el('tr');
    const nameTd = el('td', 'txt');
    nameTd.appendChild(el('span', null, r.name));
    if (r.latin) {
      nameTd.appendChild(document.createTextNode(' '));
      nameTd.appendChild(el('span', 'latin', r.latin));
    }
    tr.appendChild(nameTd);
    tr.appendChild(el('td', 'txt', r.klass || '\u2014'));
    tr.appendChild(el('td', null, fmtInt(r.n_detections)));
    tr.appendChild(el('td', null, fmtInt(r.validation_target)));
    tr.appendChild(el('td', r.n_validated ? null : 'nil', fmtInt(r.n_validated)));
    tr.appendChild(el('td', r.n_true_positive ? null : 'nil', fmtInt(r.n_true_positive)));
    tr.appendChild(el('td', r.precision === null ? 'nil' : null,
      r.precision === null ? 'not yet validated' : fmtNum(r.precision, 3)));
    tr.appendChild(el('td', r.pct_of_target ? null : 'nil', fmtPct(r.pct_of_target)));
    body.appendChild(tr);
  }
}

function bindHead(rows) {
  const head = $('#validation-head');
  if (!head || boundHead) return;
  boundHead = true;
  const act = (target) => {
    const th = target.closest ? target.closest('th') : null;
    if (!th || !th.dataset.key) return;
    if (sortKey === th.dataset.key) sortDir = -sortDir;
    else { sortKey = th.dataset.key; sortDir = COLUMNS.find(c => c.key === sortKey).text ? 1 : -1; }
    renderHead();
    renderBody(rows);
  };
  head.addEventListener('click', (ev) => act(ev.target));
  head.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); act(ev.target); }
  });
}

function stat(label, value, sub) {
  const box = el('div', 'stat');
  box.appendChild(el('div', 'stat-value', value));
  box.appendChild(el('div', 'stat-label', label));
  if (sub) box.appendChild(el('div', 'stat-sub', sub));
  return box;
}

export function renderValidation(ctx) {
  const panel = $('#panel-validation');
  if (!panel) return;
  const { birdnet } = ctx;
  hidePanelError('#validation-error');

  const overall = $('#validation-overall');
  clear(overall);

  if (!birdnet) {
    showPanelError('#validation-error', 'Validation progress unavailable.',
      'data/birdnet.json could not be loaded, so validation progress cannot be shown.');
    clear($('#validation-body'));
    return;
  }

  const v = birdnet.validation || {};
  const pct = Number(v.pct_complete);
  const pctSafe = Number.isFinite(pct) ? pct : 0;
  const notStarted = !Number.isFinite(pct) || pct <= 0;

  const sub = $('#validation-sub');
  if (sub) {
    sub.textContent =
      `Manual verification of BirdNET detections. Every count in the species chart is unvalidated ` +
      `until this table fills in.`;
  }

  // progress bar
  const wrap = el('div', 'progress-wrap');
  const lab = el('div', 'progress-label');
  lab.appendChild(el('span', null, 'Detections validated against target'));
  const state = el('span', notStarted ? 'state notstarted' : 'state',
    notStarted
      ? `Not started \u2014 0 of ${fmtInt(v.n_target)} (0.0%)`
      : `${fmtInt(v.n_validated)} of ${fmtInt(v.n_target)} (${fmtPct(pctSafe)})`);
  lab.appendChild(state);
  wrap.appendChild(lab);
  const track = el('div', 'progress-track');
  const fill = el('div', 'progress-fill');
  fill.style.width = `${Math.max(0, Math.min(100, pctSafe))}%`;
  track.appendChild(fill);
  wrap.appendChild(track);
  if (notStarted) {
    wrap.appendChild(el('p', 'progress-empty-note',
      'No detections have been reviewed yet. The bar and the per-species columns below fill in ' +
      'as rows are added to build/validation_log.csv and the summaries are rebuilt.'));
  }
  overall.appendChild(wrap);

  overall.appendChild(stat('Detection pool', fmtInt(v.pool_size),
    v.pool_threshold !== undefined ? `at confidence \u2265 ${v.pool_threshold}` : null));
  overall.appendChild(stat('Validation target', fmtInt(v.n_target),
    Number.isFinite(Number(v.target_fraction))
      ? `${fmtNum(Number(v.target_fraction) * 100, 0)}% of the pool` : null));
  overall.appendChild(stat('Validated', fmtInt(v.n_validated),
    notStarted ? 'none reviewed' : null));
  overall.appendChild(stat('Overall precision',
    v.overall_precision === null || v.overall_precision === undefined
      ? 'not yet estimable' : fmtNum(Number(v.overall_precision), 3),
    v.overall_precision === null || v.overall_precision === undefined
      ? 'needs validated detections' : null));

  const note = $('#validation-note');
  if (note) note.textContent = v.note || '';

  const rows = validationRows(birdnet);
  const caption = $('#validation-caption');
  if (caption) {
    caption.textContent =
      `${fmtInt(rows.length)} wildlife species with a validation target. ` +
      `Click any column heading to sort. Precision is true positives divided by validated ` +
      `detections and stays blank until a species has reviewed detections.`;
  }
  renderHead();
  renderBody(rows);
  bindHead(rows);

  const foot = $('#validation-foot');
  if (foot) {
    foot.textContent =
      `Progress is read from build/validation_log.csv by build/build_summaries.py; ` +
      `the log file is ${v.log_present ? 'present' : 'missing'} in the build directory. ` +
      `Adding reviewed detections to that file and rerunning the pipeline updates this panel.`;
  }
}
