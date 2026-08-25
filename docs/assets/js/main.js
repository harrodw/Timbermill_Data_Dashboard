/* ==========================================================================
   main.js -- controller: load summaries, build the view toggle from
   manifest.views[], route on the URL hash, and dispatch panel renders.

   Nothing here hardcodes a count, a view id, or a species total: the view
   list, labels, statuses, and every displayed number come from
   ./data/*.json at runtime.
   ========================================================================== */

import {
  $, el, clear, setText, fmtInt, fmtDays, tryLoadJSON, showPanelError
} from './data.js';
import { renderMap, invalidateMap } from './map.js';
import {
  renderEffort, renderSpecies, fillThresholdControl, resizeCharts,
  effortRowsForView, aruRowsForView, effortStatsFromRows, normalizeSpecies
} from './charts.js';
import { renderMedia, mediaCount } from './media.js';
import { renderValidation } from './validation.js';

window.__dashboardBooted = true;

/* Which summary file backs the species panel for each available view. This is
   the one view-to-file mapping the frontend has to know; it is keyed by the
   view ids that manifest.views[] publishes. */
const SPECIES_KIND = {
  bucket_camera: 'ahdrift',
  parallel_camera: 'parallel',
  bird_frog_audio: 'birdnet'
};

const state = {
  manifest: null,
  views: [],
  activeId: null,
  sources: {},
  errors: {},
  media: null,
  mediaError: null,
  controls: { topN: '25', sort: 'count_desc', stack: 'stacked', threshold: 'all' }
};

/* ------------------------------------------------------------------- header */

function renderChrome(manifest) {
  setText('#disclaimer-text', manifest.disclaimer ||
    'PRELIMINARY DATA -- counts are provisional and unvalidated. Do not cite or redistribute.');
  document.title = `${manifest.project || 'Sensor dashboard'} \u2014 preliminary sensor summaries`;
  setText('#header-title', manifest.project || 'Sensor dashboard');
  setText('#header-subtitle', manifest.subtitle || '');
  setText('#header-investigator', manifest.investigator || '');
  setText('#header-generated', manifest.generated_utc || 'unknown');
  setText('#header-season', manifest.field_season
    ? `Field season ${manifest.field_season}` : 'Field season');
}

/* -------------------------------------------------------------- view toggle */

function buildToggle(views) {
  const bar = $('#view-toggle');
  if (!bar) return;
  clear(bar);
  for (const v of views) {
    const btn = el('button', 'view-btn');
    btn.type = 'button';
    btn.id = `tab-${v.id}`;
    btn.dataset.viewId = v.id;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', 'false');
    btn.appendChild(el('span', null, v.label || v.id));
    if (v.status === 'pending') btn.appendChild(el('span', 'badge', 'Planned'));
    btn.addEventListener('click', () => {
      if (window.location.hash.slice(1) === v.id) activate(v.id);
      else window.location.hash = v.id;
    });
    bar.appendChild(btn);
  }
}

function markActiveTab(viewId) {
  for (const btn of document.querySelectorAll('.view-btn')) {
    btn.setAttribute('aria-selected', btn.dataset.viewId === viewId ? 'true' : 'false');
  }
}

/* ------------------------------------------------------------- stat strip */

function statCard(label, value, sub) {
  const box = el('div', 'stat');
  box.appendChild(el('div', 'stat-value', value));
  box.appendChild(el('div', 'stat-label', label));
  if (sub) box.appendChild(el('div', 'stat-sub', sub));
  return box;
}

/**
 * Headline stats. Species / deployments / sensor-days come from the view entry
 * in manifest.views[] where present, and are recomputed from the detail files
 * when the manifest omits them, so the strip never shows a stale blank.
 */
function renderStats(view) {
  const strip = $('#stat-strip');
  if (!strip) return;
  clear(strip);

  const isAru = view.id === 'bird_frog_audio';
  const speciesList = normalizeSpecies(view, state.sources, null);
  const bn = state.sources.birdnet;

  // species
  let nSpecies = view.n_species;
  if (!Number.isFinite(Number(nSpecies))) {
    nSpecies = isAru
      ? (bn && bn.n_wildlife_species)
      : (speciesList ? speciesList.length : null);
  }
  strip.appendChild(statCard(
    isAru ? 'Species (acoustic)' : 'Species identified',
    fmtInt(nSpecies),
    isAru ? 'wildlife classes, unvalidated' : 'excludes coarse-group labels'));

  // deployments / plots, and sensor-days -- recomputed from the plotted rows
  const rows = isAru ? aruRowsForView(bn) : effortRowsForView(state.sources.effort, view.id);
  const derived = effortStatsFromRows(rows);
  const summary = (!isAru && state.sources.effort && state.sources.effort.summary)
    ? state.sources.effort.summary[view.id] : null;

  const nDep = Number.isFinite(Number(view.n_deployments)) ? view.n_deployments
    : (summary ? summary.n_deployments : (derived ? derived.n_deployments : null));
  strip.appendChild(statCard(
    isAru ? 'Recording plots' : 'Camera deployments',
    fmtInt(nDep),
    isAru ? 'one ARU per plot' : 'camera at one point, one date window'));

  const days = Number.isFinite(Number(view.sensor_days)) ? view.sensor_days
    : (summary ? summary.total_sensor_days : (derived ? derived.total_sensor_days : null));
  strip.appendChild(statCard(
    isAru ? 'Recording days' : 'Sensor-days',
    fmtDays(days),
    derived ? `${fmtDays(Math.round(derived.mean_days * 10) / 10)} d mean per ${isAru ? 'plot' : 'deployment'}` : null));

  // detections / sequences
  if (isAru && bn) {
    strip.appendChild(statCard('Classifier detections', fmtInt(bn.n_detections_total),
      'raw BirdNET, unvalidated'));
  } else {
    const src = view.speciesKind === 'ahdrift' ? state.sources.species_ahdrift : state.sources.species_parallel;
    if (src) {
      strip.appendChild(statCard('Identified sequences', fmtInt(src.n_identified_sequences),
        Number.isFinite(src.n_coarse_sequences)
          ? `plus ${fmtInt(src.n_coarse_sequences)} coarse or non-wildlife` : null));
    }
  }

  // media count -- from media.json when present, else the manifest's n_media
  const n = state.media ? mediaCount(state.media, view.id)
    : (Number.isFinite(Number(view.n_media)) ? Number(view.n_media) : 0);
  strip.appendChild(statCard('Example media', fmtInt(n),
    state.media ? (n ? 'published examples' : 'none published for this view')
                : 'media manifest not published yet'));
}

/* ------------------------------------------------------------------ routing */

function renderPending(view) {
  $('#data-view').hidden = true;
  $('#pending-view').hidden = false;
  setText('#pending-title', view.label || view.id);
  setText('#pending-taxa', view.taxa || 'not recorded');
  setText('#pending-sensor', view.sensor_type || 'not recorded');
  setText('#pending-status', 'Collected, not yet processed');
  setText('#pending-note', view.pending_note ||
    'No status note is published for this view yet.');
}

async function renderAvailable(view) {
  $('#pending-view').hidden = true;
  const dv = $('#data-view');
  dv.hidden = false;

  setText('#view-title', view.label || view.id);
  setText('#view-taxa', [view.taxa, view.sensor_type].filter(Boolean).join('  \u00b7  '));

  renderStats(view);

  const ctx = {
    view,
    viewId: view.id,
    sources: state.sources,
    locations: state.sources.locations,
    birdnet: state.sources.birdnet,
    effort: state.sources.effort,
    media: state.media,
    mediaError: state.mediaError,
    controls: state.controls
  };

  // validation panel: only where the data file defines one
  const vPanel = $('#panel-validation');
  const wantsValidation = view.speciesKind === 'birdnet';
  vPanel.hidden = !wantsValidation;
  if (wantsValidation) renderValidation(ctx);

  // BirdNET-only confidence control
  const thWrap = $('#species-threshold-wrap');
  if (thWrap) {
    thWrap.hidden = view.speciesKind !== 'birdnet';
    if (view.speciesKind === 'birdnet') fillThresholdControl(state.sources.birdnet);
  }

  renderMedia(ctx);
  // Render the three data panels concurrently. Sequencing them would let one
  // slow or blocked CDN library hold up the panels behind it, including the
  // map's coordinate-precision note, which must never be late.
  await Promise.all([
    renderSpecies(ctx).catch(err => showPanelError('#species-error',
      'Species chart failed to render.', String(err && err.message || err))),
    renderEffort(ctx).catch(err => showPanelError('#effort-error',
      'Effort chart failed to render.', String(err && err.message || err))),
    renderMap(ctx).catch(err => showPanelError('#map-error',
      'Map failed to render.', String(err && err.message || err)))
  ]);
}

function activate(viewId) {
  const view = state.views.find(v => v.id === viewId) || state.views[0];
  if (!view) return;
  state.activeId = view.id;
  markActiveTab(view.id);
  if (view.status === 'pending') renderPending(view);
  else {
    renderAvailable(view).catch(err => {
      showPanelError('#map-error', 'This view failed to render.',
        String(err && err.message || err));
    });
  }
}

function viewFromHash() {
  const id = window.location.hash.replace(/^#/, '');
  return state.views.some(v => v.id === id) ? id : null;
}

/* ------------------------------------------------------------------- footer */

function renderFooter(manifest) {
  const box = $('#foot-annotation');
  const ap = manifest.annotation_progress || {};
  const totals = manifest.totals || {};
  if (box) {
    clear(box);
    const rows = [
      ['Sequences human-reviewed',
        `${fmtInt(ap.n_sequences_human_reviewed)} of ${fmtInt(ap.n_sequences_total)}` +
        (Number.isFinite(Number(ap.pct_human_reviewed)) ? ` (${ap.pct_human_reviewed}%)` : '')],
      ['Images uploaded', fmtInt(ap.n_images_uploaded)],
      ['Reviewers', fmtInt(ap.n_reviewers)]
    ];
    for (const [k, v] of rows) {
      const r = el('div', 'foot-row');
      r.appendChild(el('span', 'k', k));
      r.appendChild(el('span', 'v', v));
      box.appendChild(r);
    }
  }
  setText('#foot-annotation-note', ap.note || '');

  const bits = [];
  if (Number.isFinite(Number(totals.n_sensor_points)) && Number.isFinite(Number(totals.n_plots))) {
    bits.push(`${fmtInt(totals.n_sensor_points)} sensor points across ${fmtInt(totals.n_plots)} plots`);
  }
  if (Number.isFinite(Number(totals.n_camera_deployments))) {
    bits.push(`${fmtInt(totals.n_camera_deployments)} camera deployments`);
  }
  if (Number.isFinite(Number(totals.n_birdnet_detections))) {
    bits.push(`${fmtInt(totals.n_birdnet_detections)} BirdNET detections`);
  }
  if (Number.isFinite(Number(totals.n_camera_species)) && Number.isFinite(Number(totals.n_acoustic_species))) {
    bits.push(`${fmtInt(totals.n_camera_species)} camera and ${fmtInt(totals.n_acoustic_species)} acoustic species labels`);
  }
  setText('#foot-sources',
    (bits.length ? bits.join('; ') + '. ' : '') +
    'Camera identifications come from Wildlife Insights; acoustic identifications from BirdNET; ' +
    'survey effort from the field deployment log.');

  setText('#foot-generated',
    `Summaries generated ${manifest.generated_utc || 'unknown'}` +
    (manifest.field_season ? `, field season ${manifest.field_season}.` : '.'));
}

/* --------------------------------------------------------------------- boot */

async function boot() {
  const m = await tryLoadJSON('manifest.json');
  if (!m.ok) {
    const fatal = $('#fatal');
    fatal.hidden = false;
    setText('#fatal-detail', `${m.error} Every panel on this page is driven by that file, ` +
      `so nothing can be drawn until it loads. Confirm data/manifest.json exists next to index.html ` +
      `and that the page is served over HTTP.`);
    const bar = $('#view-toggle');
    if (bar) { clear(bar); bar.appendChild(el('p', 'muted loading-inline', 'Views unavailable.')); }
    return;
  }
  state.manifest = m.value;
  renderChrome(state.manifest);
  renderFooter(state.manifest);

  state.views = (Array.isArray(state.manifest.views) ? state.manifest.views : [])
    .map(v => ({ ...v, speciesKind: SPECIES_KIND[v.id] || null }));
  if (!state.views.length) {
    const fatal = $('#fatal');
    fatal.hidden = false;
    setText('#fatal-detail', 'data/manifest.json loaded but its views[] list is empty, ' +
      'so there are no data views to show.');
    return;
  }
  buildToggle(state.views);

  // Load the detail files in parallel; each failure is reported in its panel.
  const wanted = [
    ['locations', 'locations.json'],
    ['effort', 'effort.json'],
    ['species_ahdrift', 'species_ahdrift.json'],
    ['species_parallel', 'species_parallel.json'],
    ['birdnet', 'birdnet.json']
  ];
  const results = await Promise.all(wanted.map(([, file]) => tryLoadJSON(file)));
  wanted.forEach(([key, file], i) => {
    const r = results[i];
    if (r.ok) state.sources[key] = r.value;
    else { state.sources[key] = null; state.errors[key] = r.error; }
  });

  // media.json is written by a separate step and may legitimately be absent.
  const media = await tryLoadJSON('media.json');
  if (media.ok && media.value && typeof media.value === 'object') state.media = media.value;
  else state.mediaError = media.ok ? 'file present but not a media manifest' : media.error;

  window.addEventListener('hashchange', () => activate(viewFromHash() || state.views[0].id));
  activate(viewFromHash() || state.views[0].id);

  // species controls
  const bind = (sel, key) => {
    const node = $(sel);
    if (!node) return;
    node.addEventListener('change', () => {
      state.controls[key] = node.value;
      const view = state.views.find(v => v.id === state.activeId);
      if (view && view.status !== 'pending') {
        renderSpecies({ view, viewId: view.id, sources: state.sources, controls: state.controls });
      }
    });
  };
  bind('#species-topn', 'topN');
  bind('#species-sort', 'sort');
  bind('#species-stack', 'stack');
  bind('#species-threshold', 'threshold');

  let rt;
  window.addEventListener('resize', () => {
    window.clearTimeout(rt);
    rt = window.setTimeout(() => { resizeCharts(); invalidateMap(); }, 180);
  });
}

boot().catch(err => {
  const fatal = $('#fatal');
  if (fatal) {
    fatal.hidden = false;
    setText('#fatal-detail',
      `The dashboard failed to start: ${err && err.message ? err.message : String(err)}`);
  }
  // Also surface it in the panels that would otherwise sit empty.
  showPanelError('#map-error', 'Not loaded.', 'The dashboard failed to start; see the message above.');
});
