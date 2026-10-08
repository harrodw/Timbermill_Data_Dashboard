/* ==========================================================================
   validation.js -- two panels.

   1. BirdNET validation (bird_frog_audio only), from birdnet.json .validation,
      .groups[] and .species[].validation. The design is: listen to 150 clips
      per species, record the confidence at which 95% of detections are true
      positives, then keep only detections at or above that species' own
      cutoff. Four states exist and the table reports which one each species
      is in -- a cutoff, no attainable cutoff, or not reviewed yet.

   2. Identification and validation effort, from manifest.identification_progress,
      shown on every view.

   One labelling rule runs through both. The share of listened clips that were
   true positives is a property of the clips that were listened to -- they were
   chosen to locate each cutoff, not drawn at random -- so it is never titled
   "precision" and never presented as a property of the published counts.
   ========================================================================== */

import {
  $, el, clear, fmtInt, fmtNum, fmtPct, isNum, classLabel, classRank,
  showPanelError, hidePanelError
} from './data.js?v=17f780a779';

const GROUP_BADGE = {
  validated: 'ok',
  no_cutoff: 'warn',
  frogs: 'pending',
  pending: 'pending',
  other: 'muted'
};

const COLUMNS = [
  { key: 'name', label: 'Species', text: true },
  { key: 'klass', label: 'Class', text: true },
  { key: 'state', label: 'Validation state', text: true },
  { key: 'threshold', label: 'Cutoff' },
  { key: 'n_listened', label: 'Clips heard' },
  { key: 'n_positive', label: 'True positives' },
  { key: 'sample_rate', label: 'Of clips heard' },
  { key: 'n_raw', label: 'Raw detections' },
  { key: 'n_kept', label: 'Kept' },
  { key: 'pct_retained', label: '% kept' }
];

let sortKey = 'n_raw';
let sortDir = -1;
let boundHead = false;
let currentRows = [];

/** One table row per species label, whatever validation state it is in. */
export function validationRows(birdnet) {
  const species = (birdnet && Array.isArray(birdnet.species)) ? birdnet.species : [];
  const groups = new Map(((birdnet && birdnet.groups) || []).map(g => [g.id, g]));
  return species.map(s => {
    const v = s.validation || {};
    const g = groups.get(s.group);
    return {
      name: s.species,
      latin: s.latin_name,
      klass: s.class,
      group: s.group,
      state: g ? g.status : '\u2014',
      group_label: g ? g.label : s.group,
      threshold: (s.threshold === null || s.threshold === undefined)
        ? null : Number(s.threshold),
      n_listened: num(v.n_listened),
      n_positive: num(v.n_positive),
      n_negative: num(v.n_negative),
      n_skipped: num(v.n_skipped),
      sample_rate: (v.sample_positive_rate === null || v.sample_positive_rate === undefined)
        ? null : Number(v.sample_positive_rate),
      n_raw: num(s.n_detections_raw),
      n_kept: num(s.n_detections),
      pct_retained: (s.pct_retained === null || s.pct_retained === undefined)
        ? null : Number(s.pct_retained),
      filtered: !!s.filtered,
      reviewer_note: v.note || null
    };
  });
}

function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }

export function sortRows(rows, key, dir) {
  const col = COLUMNS.find(c => c.key === key) || COLUMNS[7];
  return rows.slice().sort((a, b) => {
    const av = a[col.key];
    const bv = b[col.key];
    if (col.key === 'klass') {
      return dir * (classRank(av) - classRank(bv)) ||
        String(a.name).localeCompare(String(b.name));
    }
    if (col.text) return dir * String(av ?? '').localeCompare(String(bv ?? ''));
    const an = (av === null || av === undefined) ? -Infinity : Number(av);
    const bn = (bv === null || bv === undefined) ? -Infinity : Number(bv);
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
    if (r.reviewer_note) {
      const flag = el('span', 'note-flag', ' \u2709');
      flag.title = `Reviewer note: ${r.reviewer_note}`;
      nameTd.appendChild(flag);
    }
    tr.appendChild(nameTd);
    tr.appendChild(el('td', 'txt', classLabel(r.klass)));

    const stateTd = el('td', 'txt');
    const badge = el('span', `state-badge ${GROUP_BADGE[r.group] || 'muted'}`, r.state);
    badge.title = r.group_label;
    stateTd.appendChild(badge);
    tr.appendChild(stateTd);

    // A cutoff exists only where listening found one. The two ways it can be
    // absent are different facts and are shown as different words.
    if (r.threshold !== null) {
      tr.appendChild(el('td', null, fmtNum(r.threshold, 2)));
    } else if (r.group === 'no_cutoff') {
      const td = el('td', 'nil', 'none found');
      td.title = 'Listening found no confidence at which 95% of detections ' +
        'were true positives.';
      tr.appendChild(td);
    } else {
      tr.appendChild(el('td', 'nil', 'not reviewed'));
    }

    tr.appendChild(el('td', r.n_listened ? null : 'nil', fmtInt(r.n_listened)));
    tr.appendChild(el('td', r.n_listened ? null : 'nil',
      r.n_listened ? fmtInt(r.n_positive) : '\u2014'));
    tr.appendChild(el('td', r.sample_rate === null ? 'nil' : null,
      r.sample_rate === null ? '\u2014' : fmtPct(100 * r.sample_rate, 0)));
    tr.appendChild(el('td', null, fmtInt(r.n_raw)));

    if (r.filtered) {
      tr.appendChild(el('td', null, fmtInt(r.n_kept)));
      tr.appendChild(el('td', null, fmtPct(r.pct_retained, 0)));
    } else {
      const a = el('td', 'nil', fmtInt(r.n_kept));
      a.title = 'No cutoff applied: raw count.';
      tr.appendChild(a);
      tr.appendChild(el('td', 'nil', 'unfiltered'));
    }
    body.appendChild(tr);
  }
}

function bindHead() {
  const head = $('#validation-head');
  if (!head || boundHead) return;
  boundHead = true;
  const act = (target) => {
    const th = target.closest ? target.closest('th') : null;
    if (!th || !th.dataset.key) return;
    if (sortKey === th.dataset.key) sortDir = -sortDir;
    else {
      sortKey = th.dataset.key;
      sortDir = COLUMNS.find(c => c.key === sortKey).text ? 1 : -1;
    }
    renderHead();
    renderBody(currentRows);
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

/* ------------------------------------------------- BirdNET validation panel */

export function renderValidation(ctx) {
  const panel = $('#panel-validation');
  if (!panel) return;
  const { birdnet } = ctx;
  hidePanelError('#validation-error');

  const overall = $('#validation-overall');
  clear(overall);

  if (!birdnet) {
    showPanelError('#validation-error', 'Validation progress unavailable.',
      'data/birdnet.json could not be loaded, so validation state cannot be shown.');
    clear($('#validation-body'));
    return;
  }

  const v = birdnet.validation || {};
  const groups = Array.isArray(birdnet.groups) ? birdnet.groups : [];

  const sub = $('#validation-sub');
  if (sub) {
    sub.textContent =
      `${fmtInt(v.n_listened_per_species)} detections were reviewed by ear per species, ` +
      `and the confidence at which ${fmtPct(100 * Number(v.target_p), 0)} of them were ` +
      `true positives was recorded as that species' cutoff. Each species is then ` +
      `filtered to its own cutoff. Species without one are shown raw and are labelled ` +
      `as such everywhere on this page.`;
  }

  overall.appendChild(stat('Clips reviewed', fmtInt(v.n_clips_listened),
    `${fmtInt(v.n_clips_positive)} true, ${fmtInt(v.n_clips_negative)} false, ` +
    `${fmtInt(v.n_clips_skipped)} skipped`));

  // Listening effort, reported separately from cutoff yield. More species were
  // reviewed than produced a usable cutoff, and the cutoff count alone reads
  // as though the rest had not been listened to.
  if (isNum(v.n_species_reviewed)) {
    overall.appendChild(stat('Species reviewed', fmtInt(v.n_species_reviewed),
      isNum(v.n_species_full_quota)
        ? `${fmtInt(v.n_species_full_quota)} at the full ` +
          `${fmtInt(v.n_listened_per_species)} clips`
        : null));
  }
  // isNum: cutoff_median is null until at least one species is validated, and
  // Number(null) is a finite 0 that would print "median 0.00".
  overall.appendChild(stat('Cutoffs established', fmtInt(v.n_species_validated),
    isNum(v.cutoff_median)
      ? `median ${fmtNum(v.cutoff_median, 2)}, range ${fmtNum(v.cutoff_min, 2)}\u2013${fmtNum(v.cutoff_max, 2)}`
      : null));
  overall.appendChild(stat('Detections kept', fmtInt(v.n_detections_validated_retained),
    `${fmtPct(v.pct_retained_validated, 0)} of the ` +
    `${fmtInt(v.n_detections_validated_raw)} raw detections of those species`));
  overall.appendChild(stat('Still unreviewed',
    fmtInt(Number(v.n_species_frogs) + Number(v.n_species_pending)),
    `${fmtInt(v.n_species_frogs)} anurans and ${fmtInt(v.n_species_pending)} birds ` +
    `in the queue`));
  if (Number(v.n_species_no_cutoff) > 0) {
    overall.appendChild(stat('No cutoff reachable', fmtInt(v.n_species_no_cutoff),
      'never reached the target at any confidence'));
  }

  // Group bars: how the detection pool divides across validation states.
  const groupBox = $('#validation-groups');
  if (groupBox) {
    clear(groupBox);
    const total = groups.reduce((a, g) => a + Number(g.n_detections_raw || 0), 0);
    for (const g of groups) {
      if (!g.n_species) continue;
      const row = el('div', 'vgroup');
      const head = el('div', 'vgroup-head');
      head.appendChild(el('span', 'vgroup-label', g.label));
      head.appendChild(el('span', `state-badge ${GROUP_BADGE[g.id] || 'muted'}`, g.status));
      head.appendChild(el('span', 'vgroup-count',
        `${fmtInt(g.n_species)} species \u00b7 ${fmtInt(g.n_detections_raw)} raw detections` +
        (g.filtered ? ` \u00b7 ${fmtInt(g.n_detections)} kept` : '')));
      row.appendChild(head);
      const track = el('div', 'vgroup-track');
      const raw = el('div', 'vgroup-raw');
      raw.style.width = `${total ? (100 * g.n_detections_raw / total).toFixed(2) : 0}%`;
      const kept = el('div', 'vgroup-kept');
      kept.style.width = `${total ? (100 * g.n_detections / total).toFixed(2) : 0}%`;
      raw.appendChild(kept);
      track.appendChild(raw);
      row.appendChild(track);
      row.appendChild(el('p', 'vgroup-note', g.note));
      groupBox.appendChild(row);
    }
  }

  const note = $('#validation-note');
  if (note) {
    clear(note);
    if (v.note) note.appendChild(el('span', null, v.note));
    if (v.sampling_note) note.appendChild(el('p', 'panel-note', v.sampling_note));
  }

  currentRows = validationRows(birdnet);
  const caption = $('#validation-caption');
  if (caption) {
    caption.textContent =
      `All ${fmtInt(currentRows.length)} BirdNET labels in the dataset and the validation ` +
      `state of each. Click any column heading to sort. "Of clips heard" is the share of ` +
      `reviewed clips that were genuinely the species: it describes the clips that were ` +
      `listened to, which were chosen to locate the cutoff, and is not the precision of ` +
      `the published counts.`;
  }
  renderHead();
  renderBody(currentRows);
  bindHead();

  const foot = $('#validation-foot');
  if (foot) {
    foot.textContent =
      `Cutoffs are read from data/Bird_Frog_Audio_Summaries/BirdNet_Thresholds.csv by ` +
      `build/build_summaries.py, which carries ${fmtInt(v.n_species_in_log)} labels. ` +
      `Adding a cutoff there and rebuilding updates every count on this view.`;
  }
}

/* ------------------------------------------- identification effort (all views) */

/**
 * The identification and validation work behind the numbers, per sensor
 * stream. Driven entirely by manifest.identification_progress, so adding a
 * stream to the pipeline adds a block here with no page edit.
 */
export function renderIdentification(ctx) {
  const box = $('#ident-body');
  if (!box) return;
  const ip = (ctx.manifest && ctx.manifest.identification_progress) || null;
  clear(box);
  hidePanelError('#ident-error');
  if (!ip || !Object.keys(ip).length) {
    showPanelError('#ident-error', 'Identification summary unavailable.',
      'manifest.json carries no identification_progress block.');
    return;
  }

  const activeKey = { bucket_camera: 'ahdrift', parallel_camera: 'parallel',
    bird_frog_audio: 'birdnet' }[ctx.viewId];

  for (const [key, block] of Object.entries(ip)) {
    const card = el('section', 'ident-card' + (key === activeKey ? ' current' : ''));
    const head = el('div', 'ident-head');
    head.appendChild(el('h4', null, block.label));
    if (key === activeKey) head.appendChild(el('span', 'badge', 'This view'));
    card.appendChild(head);

    const grid = el('div', 'ident-stats');
    for (const row of (block.stats || [])) {
      const [label, value, note] = row;
      const cell = el('div', 'ident-stat');
      cell.appendChild(el('div', 'stat-value',
        Number.isFinite(Number(value)) ? fmtInt(value) : String(value ?? '\u2014')));
      cell.appendChild(el('div', 'stat-label', label));
      if (note) cell.appendChild(el('div', 'stat-sub', note));
      grid.appendChild(cell);
    }
    card.appendChild(grid);
    if (block.note) card.appendChild(el('p', 'panel-note', block.note));
    box.appendChild(card);
  }
}
