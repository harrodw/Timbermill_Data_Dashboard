/* ==========================================================================
   validation.js -- BirdNET validation progress (bird_frog_audio only).

   Source: data/birdnet.json .validation (overall) and .species[] per-species
   fields. The design is a stratified sample of n per species across confidence
   bins, with a logistic fit of P(true positive) on confidence giving the
   cutoff at which P reaches the target; detections at or above it are the
   positives carried into the occupancy model.

   Two labelling rules matter here. (1) The validated sample is stratified, not
   random, so the pooled true-positive rate over validated clips is a property
   of the sample and must never be titled "precision" -- per-stratum rates and
   the fitted curve are the interpretable quantities. (2) A species with no
   identifiable cutoff shows why, not a blank or an invented number.
   ========================================================================== */

import { $, el, clear, fmtInt, fmtNum, fmtPct, showPanelError, hidePanelError } from './data.js';

const COLUMNS = [
  { key: 'name',             label: 'Species',        text: true },
  { key: 'klass',            label: 'Class',          text: true },
  { key: 'n_detections',     label: 'Detections' },
  { key: 'validation_target',label: 'Target' },
  { key: 'n_validated',      label: 'Validated' },
  { key: 'pct_of_target',    label: '% of target' },
  { key: 'cutoff',           label: 'Fitted cutoff' },
  { key: 'n_retained',       label: 'Positives retained' }
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
      pool_size: num(s.pool_size),
      validation_target: num(s.validation_target),
      n_validated: num(s.n_validated),
      n_true_positive: num(s.n_true_positive),
      pct_of_target: num(s.pct_of_target),
      cutoff: (s.cutoff === null || s.cutoff === undefined) ? null : Number(s.cutoff),
      n_retained: (s.n_retained_positives === null || s.n_retained_positives === undefined)
        ? null : Number(s.n_retained_positives),
      pct_retained: (s.pct_retained === null || s.pct_retained === undefined)
        ? null : Number(s.pct_retained),
      // Why a cutoff is absent, when the fit ran but could not identify one.
      fit_reason: (s.fit && s.fit.reason) ? String(s.fit.reason) : null,
      strata: Array.isArray(s.strata) ? s.strata : []
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
    tr.appendChild(el('td', r.pct_of_target ? null : 'nil', fmtPct(r.pct_of_target)));

    // A cutoff exists only once the fit identifies one. Until then say which
    // state we are in -- not started, or fitted-but-unidentifiable and why.
    if (r.cutoff !== null) {
      tr.appendChild(el('td', null, fmtNum(r.cutoff, 3)));
    } else if (r.fit_reason) {
      const td = el('td', 'nil', 'not identifiable');
      td.title = r.fit_reason;
      tr.appendChild(td);
    } else {
      tr.appendChild(el('td', 'nil', r.n_validated ? 'not yet fitted' : 'not started'));
    }

    if (r.n_retained !== null) {
      const td = el('td', null, fmtInt(r.n_retained));
      if (r.pct_retained !== null) {
        td.appendChild(document.createTextNode(' '));
        td.appendChild(el('span', 'latin', `(${fmtPct(r.pct_retained)})`));
      }
      tr.appendChild(td);
    } else {
      tr.appendChild(el('td', 'nil', '\u2014'));
    }
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
    const nPer = Number(v.n_per_species);
    const tp = Number(v.target_p);
    sub.textContent =
      (Number.isFinite(nPer)
        ? `${fmtInt(nPer)} detections are validated per species, spread across confidence strata. `
        : 'Manual verification of BirdNET detections. ') +
      (Number.isFinite(tp)
        ? `A logistic regression of true-positive outcome on BirdNET confidence gives the cutoff ` +
          `where P(true positive) reaches ${fmtNum(tp, 2)}; detections at or above it become the ` +
          `positives for the occupancy model. `
        : '') +
      `Every count in the species chart is unvalidated until this table fills in.`;
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

  const nSp = Number(v.n_species_target);
  const nFit = Number(v.n_species_fitted);

  overall.appendChild(stat('Detection pool', fmtInt(v.pool_size),
    v.pool_threshold !== undefined ? `at confidence \u2265 ${v.pool_threshold}` : null));
  overall.appendChild(stat('Validation target', fmtInt(v.n_target),
    (Number.isFinite(Number(v.n_per_species)) && Number.isFinite(nSp))
      ? `${fmtInt(v.n_per_species)} per species \u00d7 ${fmtInt(nSp)} species` : null));
  overall.appendChild(stat('Validated', fmtInt(v.n_validated),
    notStarted ? 'none reviewed' : null));

  // Cutoffs fitted, not a pooled precision: the sample is stratified, so a
  // pooled ratio would not be the dataset's precision.
  overall.appendChild(stat('Cutoffs fitted',
    Number.isFinite(nFit) && Number.isFinite(nSp)
      ? `${fmtInt(nFit)} of ${fmtInt(nSp)}` : '\u2014',
    Number.isFinite(nFit) && nFit > 0
      ? `median ${fmtNum(Number(v.cutoff_median), 3)} ` +
        `(range ${fmtNum(Number(v.cutoff_min), 3)}\u2013${fmtNum(Number(v.cutoff_max), 3)})`
      : 'needs validated detections in \u2265 2 strata'));

  if (Number.isFinite(Number(v.n_retained_positives)) && v.n_retained_positives !== null) {
    overall.appendChild(stat('Positives retained', fmtInt(v.n_retained_positives),
      'at or above the fitted cutoffs, for the occupancy model'));
  }

  const note = $('#validation-note');
  if (note) {
    clear(note);
    if (v.note) note.appendChild(el('span', null, v.note));
    // The stratification caveat is a correctness point, not a footnote: it is
    // why no "overall precision" figure is shown anywhere on this panel.
    if (v.sampling_note) {
      note.appendChild(el('p', 'panel-note', v.sampling_note));
    }
  }

  const rows = validationRows(birdnet);
  const caption = $('#validation-caption');
  if (caption) {
    caption.textContent =
      `${fmtInt(rows.length)} wildlife species with a validation target. ` +
      `Click any column heading to sort. "Fitted cutoff" is the confidence at which the ` +
      `logistic fit reaches P(true positive) = ` +
      `${Number.isFinite(Number(v.target_p)) ? fmtNum(Number(v.target_p), 2) : '0.95'}; ` +
      `"positives retained" is how many detections sit at or above it. Both stay empty until ` +
      `a species has validations in at least two confidence strata.`;
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
