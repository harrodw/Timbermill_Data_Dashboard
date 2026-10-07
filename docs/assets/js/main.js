/* ==========================================================================
   main.js -- controller: load summaries, build the view toggle from
   manifest.views[], route on the URL hash, and dispatch panel renders.

   Nothing here hardcodes a count, a view id, or a species total: the view
   list, labels, statuses, and every displayed number come from
   ./data/*.json at runtime.
   ========================================================================== */

import {
  $, el, clear, setText, fmtInt, fmtDays, tryLoadJSON, showPanelError
} from './data.js?v=5344add485';
import { renderMap, invalidateMap } from './map.js?v=5344add485';
import {
  renderEffort, renderSpecies, renderActivity, renderTree, fillGroupControl,
  resizeCharts, effortRowsForView, aruRowsForView, effortStatsFromRows,
  normalizeSpecies, speciesSource
} from './charts.js?v=5344add485';
import { renderMedia, mediaCount } from './media.js?v=5344add485';
import { renderValidation, renderIdentification } from './validation.js?v=5344add485';

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
  /* Each chart carries its own class filter: the species chart, the activity
     curves and the rate-vs-occupancy chart answer different questions, and
     wanting mammals in one does not mean wanting mammals in all three. The
     BirdNET validation group is shared, because it selects which detections
     exist at all for this view, not how they are displayed. */
  controls: {
    topN: '25', sort: 'count_desc', stack: 'stacked',
    bnGroup: 'validated',
    speciesClass: 'all', speciesScale: 'raw',
    activityClass: 'all', activitySpecies: 'all',
    activityCombined: 'separate',
    treeClass: 'all', treeTopN: '25'
  }
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
  const isBucket = view.id === 'bucket_camera';
  const speciesList = normalizeSpecies(view, state.sources,
    { group: state.controls.bnGroup });
  const bn = state.sources.birdnet;

  // species
  let nSpecies = view.n_species;
  if (!Number.isFinite(Number(nSpecies))) {
    nSpecies = isAru
      ? (bn && bn.n_wildlife_species)
      : (speciesList ? speciesList.length : null);
  }
  strip.appendChild(statCard(
    isAru ? 'Species (acoustic)' : 'Taxa identified',
    fmtInt(nSpecies),
    isAru ? 'wildlife labels across all validation states'
      : (isBucket ? 'the researcher\u2019s final species list'
        : 'excludes coarse-group labels')));

  // deployments / plots, and sensor-days -- recomputed from the plotted rows
  const rows = isAru ? aruRowsForView(bn) : effortRowsForView(state.sources.effort, view.id);
  const derived = effortStatsFromRows(rows);
  const summary = (!isAru && state.sources.effort && state.sources.effort.summary)
    ? state.sources.effort.summary[view.id] : null;

  const nDep = Number.isFinite(Number(view.n_deployments)) ? view.n_deployments
    : (summary ? summary.n_deployments : (derived ? derived.n_deployments : null));
  strip.appendChild(statCard(
    isAru ? 'Recording plots' : (isBucket ? 'AHDriFT arrays' : 'Camera deployments'),
    fmtInt(nDep),
    isAru ? 'one ARU per plot'
      : (isBucket ? 'one array per plot, one or two huts each'
        : 'camera at one station, one date window')));

  const days = Number.isFinite(Number(view.sensor_days)) ? view.sensor_days
    : (summary ? summary.total_sensor_days : (derived ? derived.total_sensor_days : null));
  const rate = speciesSource(view, state.sources);
  strip.appendChild(statCard(
    isAru ? 'Recording days' : (isBucket ? 'Array-days reviewed' : 'Camera-days'),
    fmtDays(days),
    (isBucket && rate && rate.rate)
      ? `${fmtInt(rate.rate.total_hut_days)} hut-days, the rate denominator`
      : (derived ? `${fmtDays(Math.round(derived.mean_days * 10) / 10)} d mean per ${isAru ? 'plot' : 'deployment'}` : null)));

  // detections / sequences
  if (isAru && bn) {
    const v = bn.validation || {};
    strip.appendChild(statCard('Classifier detections', fmtInt(bn.n_detections_total),
      Number.isFinite(Number(v.n_detections_validated_retained))
        ? `${fmtInt(v.n_detections_validated_retained)} kept after per-species cutoffs`
        : 'raw BirdNET'));
  } else {
    const src = speciesSource(view, state.sources);
    if (src) {
      strip.appendChild(statCard(
        isBucket ? 'Detection events' : 'Identified sequences',
        fmtInt(src.n_identified_sequences),
        Number(src.n_coarse_sequences) > 0
          ? `plus ${fmtInt(src.n_coarse_sequences)} coarse or non-wildlife`
          : (isBucket
            ? `${fmtInt(src.n_blank_plot_days)} plot-days recorded nothing`
            : null)));
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

  const isBirdnet = view.speciesKind === 'birdnet';

  // BirdNET-only validation-group control. Filled before any panel renders,
  // because the group decides which detections the other panels even see.
  const grpWrap = $('#species-group-wrap');
  if (grpWrap) {
    grpWrap.hidden = !isBirdnet;
    if (isBirdnet) {
      state.controls.bnGroup =
        fillGroupControl(state.sources.birdnet, state.controls.bnGroup);
    }
  }

  const ctx = {
    view,
    viewId: view.id,
    manifest: state.manifest,
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
  vPanel.hidden = !isBirdnet;
  if (isBirdnet) renderValidation(ctx);

  // rate vs occupancy needs a published survey-effort denominator, which the
  // ARU view does not have: recording hours are not comparable to trap-days
  // and a plot-level acoustic "occupancy" of an unvalidated classifier hit
  // would not mean what the chart implies.
  const treeSrc = speciesSource(view, state.sources);
  const wantsTree = !!(treeSrc && treeSrc.rate);
  const tPanel = $('#panel-tree');
  if (tPanel) {
    tPanel.hidden = !wantsTree;
    // Emptied as well as hidden: a hidden panel that keeps the previous
    // view's caption is a trap for anyone reading the DOM, and the caption
    // names a different site unit and a different denominator.
    if (!wantsTree) {
      for (const sel of ['#tree-stats', '#tree-chart']) clear($(sel));
      setText('#tree-sub', '');
      setText('#tree-note', '');
    }
  }

  renderMedia(ctx);
  renderIdentification(ctx);
  // Render the data panels concurrently. Sequencing them would let one slow
  // library load hold up the panels behind it, including the map's
  // coordinate-precision note, which must never be late.
  await Promise.all([
    renderSpecies(ctx).catch(err => showPanelError('#species-error',
      'Species chart failed to render.', String(err && err.message || err))),
    renderActivity(ctx).catch(err => showPanelError('#activity-error',
      'Activity curves failed to render.', String(err && err.message || err))),
    wantsTree
      ? renderTree(ctx).catch(err => showPanelError('#tree-error',
        'Detection-rate chart failed to render.', String(err && err.message || err)))
      : Promise.resolve(),
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

  // Known gaps are published rather than quietly dropped: a plot that
  // produced data but has no coordinate, a station with no location row, a
  // taxon with no photograph. All are worth seeing while work is in progress.
  const gapBox = $('#foot-gaps');
  const gaps = Array.isArray(manifest.data_gaps) ? manifest.data_gaps : [];
  if (gapBox) {
    clear(gapBox);
    if (!gaps.length) {
      gapBox.appendChild(el('p', 'foot-text',
        'No unresolved inconsistencies between the sensor tables, the location ' +
        'table and the media album.'));
    } else {
      const ul = el('ul', 'gap-list');
      for (const g of gaps) {
        const li = el('li');
        li.appendChild(el('span', 'gap-id', g.id || g.kind));
        li.appendChild(el('span', null, ` ${g.detail || ''}`));
        ul.appendChild(li);
      }
      gapBox.appendChild(ul);
    }
  }

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

  /* Control wiring. Each control names the panels it invalidates, so changing
     the species top-N does not redraw the map, and changing the BirdNET
     validation group — which changes which detections exist — redraws
     everything that counts them. */
  const panelCtx = () => {
    const view = state.views.find(v => v.id === state.activeId);
    if (!view || view.status === 'pending') return null;
    return {
      view,
      viewId: view.id,
      manifest: state.manifest,
      sources: state.sources,
      locations: state.sources.locations,
      birdnet: state.sources.birdnet,
      effort: state.sources.effort,
      media: state.media,
      mediaError: state.mediaError,
      controls: state.controls
    };
  };

  const REDRAW = {
    species: ctx => renderSpecies(ctx).catch(err => showPanelError('#species-error',
      'Species chart failed to render.', String(err && err.message || err))),
    activity: ctx => renderActivity(ctx).catch(err => showPanelError('#activity-error',
      'Activity curves failed to render.', String(err && err.message || err))),
    tree: ctx => {
      const panel = $('#panel-tree');
      if (panel && panel.hidden) return Promise.resolve();
      return renderTree(ctx).catch(err => showPanelError('#tree-error',
        'Detection-rate chart failed to render.', String(err && err.message || err)));
    },
    validation: ctx => { renderValidation(ctx); return Promise.resolve(); },
    stats: ctx => { renderStats(ctx.view); return Promise.resolve(); }
  };

  const bind = (sel, key, panels, resets) => {
    const node = $(sel);
    if (!node) return;
    node.addEventListener('change', () => {
      state.controls[key] = node.value;
      for (const r of (resets || [])) state.controls[r] = 'all';
      const ctx = panelCtx();
      if (!ctx) return;
      for (const p of panels) REDRAW[p](ctx);
    });
  };

  bind('#species-topn', 'topN', ['species']);
  bind('#species-sort', 'sort', ['species']);
  bind('#species-stack', 'stack', ['species']);
  bind('#species-class', 'speciesClass', ['species']);
  bind('#species-scale', 'speciesScale', ['species']);
  // A new validation group is a different set of species, so the activity
  // species picker must not keep pointing at one that is no longer there.
  bind('#species-group', 'bnGroup',
    ['species', 'activity', 'tree', 'stats'], ['activitySpecies']);
  bind('#activity-class', 'activityClass', ['activity'], ['activitySpecies']);
  bind('#activity-species', 'activitySpecies', ['activity']);
  bind('#activity-combined', 'activityCombined', ['activity']);
  bind('#tree-class', 'treeClass', ['tree']);
  bind('#tree-topn', 'treeTopN', ['tree']);

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
