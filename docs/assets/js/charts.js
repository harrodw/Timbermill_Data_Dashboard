/* ==========================================================================
   charts.js -- effort, species, activity and detection-rate charts (Plotly).

   Effort:    camera views -> effort.json .deployments[] filtered by view.
              bucket_camera is one bar per AHDriFT array (the plot-days
              actually reviewed); parallel_camera is one bar per deployment;
              bird_frog_audio -> birdnet.json .plots[] recording days.
   Species:   species_ahdrift.json / species_parallel.json .species[], or
              birdnet.json .species[] filtered to one validation group.
   Activity:  per-species half-hour histograms, smoothed into densities, one
              curve per plot type, effort-corrected for the ARUs.
   Rate:      naive occupancy against detection rate, back to back.

   Every panel carries its own taxonomic-class filter.
   ========================================================================== */

import {
  $, el, clear, fmtInt, fmtNum, fmtDays, isNum, plotColor, orderPlotTypes,
  plotTypeRank, classLabel, classRank, fillClassControl, activityCurve,
  sumBins, fmtClock, showPanelError, hidePanelError, showChartMessage,
  waitForGlobal
} from './data.js?v=a5de6b6827';

const PLOTLY_CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d', 'toggleSpikelines'],
  toImageButtonOptions: { format: 'png', scale: 2, filename: 'timbermill_preliminary' }
};

const FONT = {
  family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  size: 12,
  color: '#1c2127'
};

const AXIS = {
  gridcolor: '#ecEEF1',
  zerolinecolor: '#dfe3e7',
  linecolor: '#dfe3e7',
  tickfont: { size: 11, color: '#6b7681' },
  titlefont: { size: 12, color: '#444d57' }
};

const OCC_COLOR = '#2E6F95';
const RATE_COLOR = '#C25E1A';

function baseLayout(extra) {
  return Object.assign({
    font: FONT,
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    margin: { l: 70, r: 24, t: 12, b: 52 },
    hoverlabel: { bgcolor: '#ffffff', bordercolor: '#dfe3e7', font: { size: 12, color: '#1c2127' } },
    showlegend: true,
    legend: { orientation: 'h', y: 1.06, x: 0, font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' }
  }, extra || {});
}

function round1(x) { return Number.isFinite(x) ? Math.round(x * 10) / 10 : x; }

/** rgba() form of a hex colour, for confidence bands. */
function fade(hex, alpha) {
  const h = String(hex).replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/* ================================================= SPECIES (pure selectors) */

/**
 * Normalize the species schemas into one shape.
 *
 * Camera files:  {common_name, latin_name, n_sequences|n_detections, ...}
 * BirdNET file:  {species, group, threshold, n_detections_raw, n_detections,
 *                 validation:{...}, ...}
 *
 * `opts.group` selects one BirdNET validation group. There is no "all groups"
 * option on purpose: a cutoff-filtered count and an unvalidated raw count are
 * different quantities, and stacking them in one bar chart would present a
 * total that means nothing.
 */
export function normalizeSpecies(view, sources, opts) {
  const o = opts || {};
  const kind = view && view.speciesKind;
  if (kind === 'birdnet') {
    const bn = sources.birdnet;
    if (!bn || !Array.isArray(bn.species)) return null;
    const group = o.group || 'validated';
    return bn.species
      .filter(s => s.group === group)
      .map(s => ({
        name: s.species,
        latin: s.latin_name,
        klass: s.class,
        order: s.order,
        count: Number(s.n_detections),
        count_raw: Number(s.n_detections_raw),
        pct_retained: s.pct_retained,
        threshold: s.threshold,
        group: s.group,
        validation: s.validation || {},
        n_plots: s.n_plots,
        by_plot_type: s.by_plot_type || {},
        by_site: s.by_plot || {},
        activity: s.activity || {},
        occupancy: null,
        rate: null
      }))
      .filter(s => Number.isFinite(s.count) && s.count > 0);
  }
  const src = kind === 'ahdrift' ? sources.species_ahdrift : sources.species_parallel;
  if (!src || !Array.isArray(src.species)) return null;
  return src.species.map(s => ({
    name: s.common_name,
    latin: s.latin_name,
    klass: s.class,
    order: s.order,
    count: Number(s.n_detections ?? s.n_sequences),
    count_raw: Number(s.n_detections ?? s.n_sequences),
    n_plots: s.n_plots,
    by_plot_type: s.by_plot_type || {},
    by_site: s.by_point || s.by_plot || {},
    activity: s.activity || {},
    occupancy: s.naive_occupancy_pct,
    n_sites_detected: s.n_sites_detected,
    rate: s.detection_rate_per_100
  })).filter(s => Number.isFinite(s.count) && s.count > 0);
}

/** The summary file backing a view, for notes and units. */
export function speciesSource(view, sources) {
  if (!view) return null;
  if (view.speciesKind === 'birdnet') return sources.birdnet;
  if (view.speciesKind === 'ahdrift') return sources.species_ahdrift;
  return sources.species_parallel;
}

export function filterByClass(list, klass) {
  if (!klass || klass === 'all') return list;
  return (list || []).filter(s => s.klass === klass);
}

export function sortSpecies(list, mode) {
  const arr = (list || []).slice();
  if (mode === 'count_asc') arr.sort((a, b) => a.count - b.count || a.name.localeCompare(b.name));
  else if (mode === 'name_asc') arr.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  else if (mode === 'plots_desc') arr.sort((a, b) => (b.n_plots || 0) - (a.n_plots || 0) || b.count - a.count);
  else if (mode === 'occ_desc') {
    arr.sort((a, b) => (b.occupancy || 0) - (a.occupancy || 0) || b.count - a.count);
  } else if (mode === 'rate_desc') {
    arr.sort((a, b) => (b.rate || 0) - (a.rate || 0) || b.count - a.count);
  } else arr.sort((a, b) => b.count - a.count || String(a.name).localeCompare(String(b.name)));
  return arr;
}

/**
 * Top-N selection. The cut is always made on the ranking that the chart's own
 * sort implies, so "top 25" never silently means "top 25 by something else":
 * the rate-vs-occupancy chart ranks by occupancy, the species chart by count.
 */
export function selectSpecies(list, topN, sortMode) {
  const ranked = sortSpecies(list, sortMode === 'name_asc' ? 'count_desc' : sortMode);
  const kept = (topN === 'all' || !Number.isFinite(Number(topN)))
    ? ranked
    : ranked.slice(0, Number(topN));
  return sortSpecies(kept, sortMode);
}

/* ======================================================== EFFORT (pure part) */

export function effortRowsForView(effort, viewId) {
  const rows = (effort && Array.isArray(effort.deployments)) ? effort.deployments : [];
  return rows
    .filter(r => r.view === viewId)
    .map(r => ({
      key: r.deployment_id,
      plot: r.plot,
      point: r.point || r.plot,
      plot_type: r.plot_type,
      days: Number(r.days),
      hut_days: Number.isFinite(Number(r.hut_days)) ? Number(r.hut_days) : null,
      start: r.start,
      end: r.end,
      functioning: r.functioning
    }))
    .sort((a, b) =>
      plotTypeRank(a.plot_type) - plotTypeRank(b.plot_type) ||
      b.days - a.days ||
      String(a.key).localeCompare(String(b.key)));
}

/** ARU recording days per plot, same canonical sort. */
export function aruRowsForView(birdnet) {
  const rows = (birdnet && Array.isArray(birdnet.plots)) ? birdnet.plots : [];
  return rows
    .map(p => ({
      key: p.plot,
      plot: p.plot,
      plot_type: p.plot_type,
      days: Number(p.n_recording_days),
      hut_days: null,
      start: p.first_date,
      end: p.last_date,
      functioning: null
    }))
    .sort((a, b) =>
      plotTypeRank(a.plot_type) - plotTypeRank(b.plot_type) ||
      b.days - a.days ||
      String(a.key).localeCompare(String(b.key)));
}

export function effortStatsFromRows(rows) {
  const days = rows.map(r => r.days).filter(Number.isFinite).sort((a, b) => a - b);
  if (!days.length) return null;
  const sum = days.reduce((a, b) => a + b, 0);
  const mid = Math.floor(days.length / 2);
  return {
    n_deployments: rows.length,
    total_sensor_days: sum,
    mean_days: sum / days.length,
    median_days: days.length % 2 ? days[mid] : (days[mid - 1] + days[mid]) / 2,
    min_days: days[0],
    max_days: days[days.length - 1]
  };
}

/* --------------------------------------------------------------- effort DOM */

function renderEffortStats(summary, derived, rows, viewId) {
  const box = $('#effort-stats');
  if (!box) return;
  clear(box);
  const s = summary || derived;
  if (!s) return;
  const isAru = viewId === 'bird_frog_audio';
  const isBucket = viewId === 'bucket_camera';
  const unitName = isAru ? 'Recording plots' : (isBucket ? 'AHDriFT arrays' : 'Deployments');
  const dayName = isAru ? 'Total recording days'
    : (isBucket ? 'Total array-days' : 'Total camera-days');
  const pairs = [
    [unitName, fmtInt(s.n_deployments)],
    [dayName, fmtInt(s.total_sensor_days)],
    ['Mean', `${fmtDays(round1(s.mean_days))} d`],
    ['Median', `${fmtDays(s.median_days)} d`],
    ['Range', `${fmtDays(s.min_days)}\u2013${fmtDays(s.max_days)} d`]
  ];
  if (isBucket && summary && Number.isFinite(Number(summary.total_hut_days))) {
    pairs.splice(2, 0, ['Hut-days', fmtInt(summary.total_hut_days)]);
  }
  for (const [k, v] of pairs) {
    const item = el('span');
    item.appendChild(el('span', 'k', `${k}: `));
    item.appendChild(el('span', 'v', v));
    box.appendChild(item);
  }
  if (summary && summary.functioning && Object.keys(summary.functioning).length
      && !(Object.keys(summary.functioning).length === 1 && summary.functioning.Unknown)) {
    const parts = Object.entries(summary.functioning)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}: ${fmtInt(v)}`);
    const item = el('span');
    item.appendChild(el('span', 'k', 'Camera status \u2014 '));
    item.appendChild(el('span', null, parts.join(', ')));
    box.appendChild(item);
  }
}

export async function renderEffort(ctx) {
  const container = $('#effort-chart');
  if (!container) return;
  const { effort, birdnet, viewId } = ctx;
  hidePanelError('#effort-error');

  const isAru = viewId === 'bird_frog_audio';
  const isBucket = viewId === 'bucket_camera';
  const source = isAru ? birdnet : effort;
  const sourceName = isAru ? 'data/birdnet.json' : 'data/effort.json';

  if (!source) {
    clear(container);
    showPanelError('#effort-error', 'Effort chart unavailable.',
      `${sourceName} could not be loaded, so survey effort cannot be shown.`);
    clear($('#effort-stats'));
    return;
  }

  const rows = isAru ? aruRowsForView(birdnet) : effortRowsForView(effort, viewId);
  const derived = effortStatsFromRows(rows);
  const summary = (!isAru && effort.summary && effort.summary[viewId]) ? effort.summary[viewId] : null;
  renderEffortStats(summary, derived, rows, viewId);

  const perBar = isAru ? 'ARU plot' : (isBucket ? 'AHDriFT array' : 'camera deployment');
  const sub = $('#effort-sub');
  if (sub) {
    sub.textContent = isAru
      ? 'Recording days per bird and frog ARU plot, one bar per plot, grouped by plot type and ordered by duration.'
      : (isBucket
        ? 'One bar per AHDriFT array: the plot-days actually reviewed in the cleaned detection table, which is also the denominator behind the detection rates.'
        : 'One bar per camera deployment (a camera at one station over one date window), grouped by plot type and ordered by duration.');
  }

  const noteEl = $('#effort-note');
  if (noteEl) {
    const parts = [];
    if (!isAru && effort.note) parts.push(effort.note);
    if (isAru) parts.push('Recording days are counted from dated recording files, not from a deployment log.');
    noteEl.textContent = parts.join(' ');
  }

  if (!rows.length) {
    showChartMessage(container, 'No effort records for this view.',
      `${sourceName} contained no rows for "${viewId}".`);
    return;
  }

  let Plotly;
  try {
    Plotly = await waitForGlobal('Plotly');
  } catch (err) {
    clear(container);
    showPanelError('#effort-error', 'Chart library unavailable.', err.message);
    return;
  }

  const showLabels = isAru || isBucket;
  const types = orderPlotTypes(rows.map(r => r.plot_type));
  const positions = new Map(rows.map((r, i) => [r.key, i]));
  const traces = types.map(pt => {
    const sub2 = rows.filter(r => r.plot_type === pt);
    return {
      type: 'bar',
      name: pt,
      x: sub2.map(r => positions.get(r.key)),
      y: sub2.map(r => r.days),
      marker: { color: plotColor(pt), line: { width: 0 } },
      customdata: sub2.map(r => [r.key, r.plot, pt, r.start || '\u2014', r.end || '\u2014',
        r.functioning || '\u2014', r.hut_days === null ? '\u2014' : fmtInt(r.hut_days)]),
      hovertemplate:
        '<b>%{customdata[0]}</b><br>Plot %{customdata[1]} \u2014 %{customdata[2]}<br>' +
        '%{y} days<br>%{customdata[3]} to %{customdata[4]}' +
        (isBucket ? '<br>%{customdata[6]} hut-days' : '') +
        (isAru || isBucket ? '' : '<br>Status: %{customdata[5]}') +
        '<extra></extra>'
    };
  });

  const layout = baseLayout({
    barmode: 'relative',
    bargap: rows.length > 120 ? 0.05 : 0.2,
    height: 420,
    xaxis: Object.assign({}, AXIS, {
      title: { text: `${perBar} (ordered by plot type, then duration)` },
      showticklabels: showLabels,
      tickmode: showLabels ? 'array' : undefined,
      tickvals: showLabels ? rows.map(r => positions.get(r.key)) : undefined,
      ticktext: showLabels ? rows.map(r => r.plot) : undefined,
      tickangle: showLabels ? -60 : 0,
      showgrid: false,
      range: [-1, rows.length]
    }),
    yaxis: Object.assign({}, AXIS, {
      title: { text: isAru ? 'Recording days' : (isBucket ? 'Array-days reviewed' : 'Days deployed') },
      rangemode: 'tozero'
    })
  });

  clear(container);
  await Plotly.newPlot(container, traces, layout, PLOTLY_CONFIG);
}

/* -------------------------------------------------------------- species DOM */

export async function renderSpecies(ctx) {
  const container = $('#species-chart');
  if (!container) return;
  const { view, sources, controls } = ctx;
  hidePanelError('#species-error');

  const isBirdnet = view.speciesKind === 'birdnet';
  const src = speciesSource(view, sources);
  const fileName = isBirdnet ? 'data/birdnet.json'
    : (view.speciesKind === 'ahdrift' ? 'data/species_ahdrift.json' : 'data/species_parallel.json');

  const all = normalizeSpecies(view, sources, { group: controls.bnGroup });
  if (!all) {
    clear(container);
    clear($('#species-note'));
    showPanelError('#species-error', 'Species chart unavailable.',
      `${fileName} could not be loaded, so the species tally cannot be shown.`);
    return;
  }

  controls.speciesClass = fillClassControl($('#species-class'), all, controls.speciesClass);
  const list = filterByClass(all, controls.speciesClass);

  const group = isBirdnet
    ? (src.groups || []).find(g => g.id === (controls.bnGroup || 'validated'))
    : null;
  const unitLabel = isBirdnet
    ? (group && group.filtered ? 'Detections above cutoff' : 'Detections (unfiltered)')
    : (view.speciesKind === 'ahdrift' ? 'Detection events' : 'Sequences');

  const sub = $('#species-sub');
  if (sub) sub.textContent = (src && src.note) || '';

  const note = $('#species-note');
  if (note) {
    clear(note);
    const parts = [];
    if (isBirdnet && group) {
      parts.push(`${group.label}: ${fmtInt(group.n_species)} species, ` +
        (group.filtered
          ? `${fmtInt(group.n_detections)} detections kept of ${fmtInt(group.n_detections_raw)} raw ` +
            `(${fmtNum(100 * group.n_detections / Math.max(group.n_detections_raw, 1), 1)}%).`
          : `${fmtInt(group.n_detections_raw)} raw detections, no filter applied.`));
      parts.push(group.note);
    } else if (src) {
      if (src.coarse_note) parts.push(src.coarse_note);
      if (Number.isFinite(src.n_coarse_sequences) && src.n_coarse_sequences > 0) {
        parts.push(`${fmtInt(src.n_coarse_sequences)} coarse or non-wildlife sequences are excluded; ` +
          `${fmtInt(src.n_identified_sequences)} across ${fmtInt(src.n_species)} taxa are charted.`);
      }
    }
    if (controls.speciesClass && controls.speciesClass !== 'all') {
      parts.push(`Filtered to ${classLabel(controls.speciesClass)}: ` +
        `${fmtInt(list.length)} of ${fmtInt(all.length)} taxa.`);
    }
    note.textContent = parts.filter(Boolean).join(' ');
  }

  if (!list.length) {
    showChartMessage(container, 'No species to show.',
      controls.speciesClass && controls.speciesClass !== 'all'
        ? `No ${classLabel(controls.speciesClass)} in this group.`
        : `${fileName} contained no species rows with detections above zero.`);
    return;
  }

  const shown = selectSpecies(list, controls.topN, controls.sort);

  let Plotly;
  try {
    Plotly = await waitForGlobal('Plotly');
  } catch (err) {
    clear(container);
    showPanelError('#species-error', 'Chart library unavailable.', err.message);
    return;
  }

  // Plotly draws the first y entry at the bottom, so reverse to put the top
  // of the chosen sort order at the top of the chart.
  const rows = shown.slice().reverse();
  const labels = rows.map(s => s.name);

  let traces;
  if (controls.stack === 'stacked') {
    const types = orderPlotTypes(rows.flatMap(s => Object.keys(s.by_plot_type || {})));
    traces = types.map(pt => ({
      type: 'bar',
      orientation: 'h',
      name: pt,
      y: labels,
      x: rows.map(s => Number(s.by_plot_type && s.by_plot_type[pt]) || 0),
      marker: { color: plotColor(pt), line: { width: 0 } },
      customdata: rows.map(s => [s.latin || 'no Latin name recorded', classLabel(s.klass),
        s.n_plots ?? '\u2014', s.count]),
      hovertemplate:
        `<b>%{y}</b><br><i>%{customdata[0]}</i> \u00b7 %{customdata[1]}<br>${pt}: %{x:,}<br>` +
        `Total %{customdata[3]:,} across %{customdata[2]} plots<extra></extra>`
    }));
  } else {
    traces = [{
      type: 'bar',
      orientation: 'h',
      name: unitLabel,
      y: labels,
      x: rows.map(s => s.count),
      marker: { color: '#2f4a58', line: { width: 0 } },
      customdata: rows.map(s => [s.latin || 'no Latin name recorded', classLabel(s.klass),
        s.n_plots ?? '\u2014']),
      hovertemplate:
        `<b>%{y}</b><br><i>%{customdata[0]}</i> \u00b7 %{customdata[1]}<br>` +
        `%{x:,} across %{customdata[2]} plots<extra></extra>`
    }];
  }

  const height = Math.max(360, rows.length * 19 + 110);
  const layout = baseLayout({
    barmode: 'stack',
    height,
    margin: { l: 200, r: 28, t: 12, b: 56 },
    showlegend: controls.stack === 'stacked',
    xaxis: Object.assign({}, AXIS, { title: { text: unitLabel }, rangemode: 'tozero' }),
    yaxis: Object.assign({}, AXIS, {
      automargin: true,
      tickfont: { size: rows.length > 55 ? 9 : 11, color: '#444d57' },
      title: { text: '' }
    })
  });

  clear(container);
  await Plotly.newPlot(container, traces, layout, PLOTLY_CONFIG);

  const caption = $('#species-controls');
  if (caption) {
    caption.setAttribute('data-shown', `${shown.length} of ${list.length} taxa shown`);
  }
}

/* ======================================================= ACTIVITY (curves) */

/** The activity block of whichever summary file backs this view. */
export function activityMeta(view, sources) {
  const src = speciesSource(view, sources);
  return (src && src.activity) ? src.activity : null;
}

/**
 * Build one curve per plot type for a selection of species.
 *
 * @param {Array} list    normalized species rows (already class/group filtered)
 * @param {object} meta   the file's .activity block
 * @param {string} speciesName  one species name, or 'all'
 */
export function activityTraces(list, meta, speciesName) {
  if (!meta || !Number.isFinite(Number(meta.bins))) return [];
  const nBins = Number(meta.bins);
  const chosen = (speciesName && speciesName !== 'all')
    ? list.filter(s => s.name === speciesName)
    : list;
  if (!chosen.length) return [];

  const effortHours = (meta.effort_mode === 'per_bin_hours' && meta.effort_hours)
    ? meta.effort_hours : null;

  const types = orderPlotTypes(chosen.flatMap(s => Object.keys(s.activity || {})));
  const out = [];
  for (const pt of types) {
    const counts = sumBins(chosen.map(s => (s.activity || {})[pt]), nBins);
    const curve = activityCurve(counts, effortHours ? effortHours[pt] : null);
    if (!curve.ok) continue;
    out.push({
      plot_type: pt,
      curve,
      counts,
      effort: effortHours ? effortHours[pt] : null,
      n: curve.n,
      n_species: chosen.filter(s => (s.activity || {})[pt]).length
    });
  }
  return out;
}

/** Species with enough binned detections to carry their own curve. */
export function activitySpeciesOptions(list, minN) {
  const floor = Number.isFinite(Number(minN)) ? Number(minN) : 1;
  return (list || [])
    .map(s => ({
      name: s.name,
      n: Object.values(s.activity || {})
        .reduce((a, arr) => a + (arr || []).reduce((x, y) => x + (Number(y) || 0), 0), 0)
    }))
    .filter(s => s.n >= floor)
    .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
}

function fillActivitySpeciesControl(sel, options, current) {
  if (!sel) return current;
  const prev = current !== undefined ? current : sel.value;
  clear(sel);
  const all = el('option', null, 'All species in selection');
  all.value = 'all';
  sel.appendChild(all);
  for (const o of options) {
    const opt = el('option', null, `${o.name} (${fmtInt(o.n)})`);
    opt.value = o.name;
    sel.appendChild(opt);
  }
  sel.value = Array.from(sel.options).some(o => o.value === prev) ? prev : 'all';
  return sel.value;
}

export async function renderActivity(ctx) {
  const container = $('#activity-chart');
  if (!container) return;
  const { view, sources, controls } = ctx;
  hidePanelError('#activity-error');

  const meta = activityMeta(view, sources);
  const all = normalizeSpecies(view, sources, { group: controls.bnGroup });
  if (!meta || !all) {
    clear(container);
    showPanelError('#activity-error', 'Activity curves unavailable.',
      'The summary file for this view carries no activity histograms.');
    return;
  }

  controls.activityClass = fillClassControl($('#activity-class'), all, controls.activityClass);
  const list = filterByClass(all, controls.activityClass);
  // Species offered individually: 20 binned detections is the floor at which
  // a smoothed curve says anything at all. Below it the interval is wider
  // than the curve and the shape is noise.
  const options = activitySpeciesOptions(list, 20);
  controls.activitySpecies =
    fillActivitySpeciesControl($('#activity-species'), options, controls.activitySpecies);

  const traces = activityTraces(list, meta, controls.activitySpecies);

  const sub = $('#activity-sub');
  if (sub) {
    const what = view.speciesKind === 'birdnet' ? 'vocalizations' : 'detections';
    sub.textContent =
      `Time of day of ${what}, one curve per plot type. ` +
      (meta.effort_mode === 'per_bin_hours'
        ? 'Plotted as detections per recording-hour, because recording effort is far from even across the day.'
        : 'Cameras ran continuously, so no effort correction is needed.') +
      ' Each curve integrates to 1 over the 24-hour cycle, so the curves are comparable in shape, not in height.';
  }

  const noteEl = $('#activity-note');
  if (noteEl) {
    clear(noteEl);
    if (meta.note) noteEl.appendChild(el('span', null, meta.note));
    if (meta.duration_note) noteEl.appendChild(el('p', 'panel-note', meta.duration_note));
    if (meta.timestamp_note) noteEl.appendChild(el('p', 'panel-note', meta.timestamp_note));
    noteEl.appendChild(el('p', 'panel-note',
      'Shaded bands are 95% intervals from propagating Poisson counts through the ' +
      'same kernel; a band wider than the curve means the shape is carried by too ' +
      'few detections to read. Curves are wrapped at midnight, so a peak either ' +
      'side of 00:00 is one peak, not two.'));
  }

  if (!traces.length) {
    showChartMessage(container, 'No activity curves for this selection.',
      controls.activityClass !== 'all'
        ? `No ${classLabel(controls.activityClass)} detections carry a timestamp in this group.`
        : 'No detections in this selection carry a usable timestamp.');
    return;
  }

  let Plotly;
  try {
    Plotly = await waitForGlobal('Plotly');
  } catch (err) {
    clear(container);
    showPanelError('#activity-error', 'Chart library unavailable.', err.message);
    return;
  }

  const data = [];
  for (const t of traces) {
    const color = plotColor(t.plot_type);
    // Band first so the line draws over it.
    data.push({
      type: 'scatter', mode: 'lines', showlegend: false, hoverinfo: 'skip',
      x: t.curve.x.concat(t.curve.x.slice().reverse()),
      y: t.curve.hi.concat(t.curve.lo.slice().reverse()),
      fill: 'toself', fillcolor: fade(color, 0.16),
      line: { width: 0 }, name: `${t.plot_type} 95% interval`
    });
    data.push({
      type: 'scatter', mode: 'lines',
      name: `${t.plot_type} (n = ${fmtInt(t.n)})`,
      x: t.curve.x, y: t.curve.y,
      line: { color, width: 2.4, shape: 'spline', smoothing: 0.5 },
      customdata: t.curve.x.map((h, i) => [fmtClock(h), t.curve.lo[i], t.curve.hi[i]]),
      hovertemplate:
        `<b>${t.plot_type}</b><br>%{customdata[0]}<br>density %{y:.4f} ` +
        `(%{customdata[1]:.4f}\u2013%{customdata[2]:.4f})<extra></extra>`
    });
  }

  const layout = baseLayout({
    height: 430,
    margin: { l: 72, r: 24, t: 14, b: 58 },
    hovermode: 'x unified',
    xaxis: Object.assign({}, AXIS, {
      title: { text: 'Time of day (h)' },
      range: [0, 24],
      tickmode: 'array',
      tickvals: [0, 4, 8, 12, 16, 20, 24],
      ticktext: ['0', '4', '8', '12', '16', '20', '24'],
      showgrid: true, gridcolor: '#f1f3f5'
    }),
    yaxis: Object.assign({}, AXIS, {
      title: {
        text: meta.effort_mode === 'per_bin_hours'
          ? 'Activity density (per recording-hour, scaled)'
          : 'Activity density (scaled)'
      },
      rangemode: 'tozero'
    }),
    shapes: [4, 8, 12, 16, 20].map(h => ({
      type: 'line', x0: h, x1: h, y0: 0, y1: 1, yref: 'paper',
      line: { color: '#e4e7ea', width: 1, dash: 'dash' }, layer: 'below'
    }))
  });

  clear(container);
  await Plotly.newPlot(container, data, layout, PLOTLY_CONFIG);

  const stats = $('#activity-stats');
  if (stats) {
    clear(stats);
    const label = controls.activitySpecies === 'all'
      ? (controls.activityClass === 'all' ? 'All taxa in view' : classLabel(controls.activityClass))
      : controls.activitySpecies;
    const item = el('span');
    item.appendChild(el('span', 'k', 'Showing: '));
    item.appendChild(el('span', 'v', label));
    stats.appendChild(item);
    for (const t of traces) {
      const peak = t.curve.y.indexOf(Math.max(...t.curve.y));
      const s = el('span');
      s.appendChild(el('span', 'k', `${t.plot_type}: `));
      s.appendChild(el('span', null,
        `${fmtInt(t.n)} detections, peak ${fmtClock(t.curve.x[peak])}`));
      stats.appendChild(s);
    }
  }
}

/* ============================================ DETECTION RATE vs OCCUPANCY */

/**
 * Back-to-back bars: naive occupancy on a reversed left axis, detection rate
 * on a right axis, sharing the species rows.
 *
 * The two quantities answer different questions and are deliberately not
 * combined into one index. Occupancy is how widespread a taxon is -- the
 * share of stations that recorded it at least once. Rate is how often it was
 * recorded per unit of survey effort. A taxon can be everywhere but rarely
 * (wide left bar, short right bar) or concentrated but prolific (the
 * reverse), and keeping them side by side is the point of the figure.
 */
export async function renderTree(ctx) {
  const panel = $('#panel-tree');
  const container = $('#tree-chart');
  if (!panel || !container) return;
  const { view, sources, controls } = ctx;
  hidePanelError('#tree-error');

  const src = speciesSource(view, sources);
  const rateMeta = (src && src.rate) ? src.rate : null;
  const all = normalizeSpecies(view, sources, { group: controls.bnGroup });
  if (!all || !rateMeta) {
    clear(container);
    showPanelError('#tree-error', 'Detection-rate chart unavailable.',
      'This view publishes no survey-effort denominator, so neither a rate nor ' +
      'a naive occupancy can be computed.');
    return;
  }

  controls.treeClass = fillClassControl($('#tree-class'), all, controls.treeClass);
  // isNum, not Number.isFinite(Number(...)): BirdNET rows carry occupancy and
  // rate as null by construction, and Number(null) is a finite 0 that would
  // put every acoustic species on the chart at the origin.
  const list = filterByClass(all, controls.treeClass)
    .filter(s => isNum(s.occupancy) && isNum(s.rate));

  const sub = $('#tree-sub');
  if (sub) {
    sub.textContent =
      `Naive occupancy (left, share of the ${fmtInt(rateMeta.n_sites)} ` +
      `${rateMeta.site_unit}s where the taxon was recorded) against detection rate ` +
      `(right, ${rateMeta.unit}). Ranked by occupancy.`;
  }
  const noteEl = $('#tree-note');
  if (noteEl) noteEl.textContent = rateMeta.note || '';

  if (!list.length) {
    showChartMessage(container, 'No taxa to show.',
      `No ${controls.treeClass === 'all' ? 'taxa' : classLabel(controls.treeClass)} ` +
      `in this view carry both an occupancy and a rate.`);
    return;
  }

  const shown = selectSpecies(list, controls.treeTopN, 'occ_desc');

  let Plotly;
  try {
    Plotly = await waitForGlobal('Plotly');
  } catch (err) {
    clear(container);
    showPanelError('#tree-error', 'Chart library unavailable.', err.message);
    return;
  }

  const rows = shown.slice().reverse();
  const labels = rows.map(s => s.name);
  const occ = rows.map(s => Number(s.occupancy));
  const rate = rows.map(s => Number(s.rate));
  const meta = rows.map(s => [s.latin || 'no Latin name recorded', classLabel(s.klass),
    s.count, s.n_sites_detected ?? '\u2014', rateMeta.n_sites]);

  const data = [{
    type: 'bar', orientation: 'h', name: 'Naive occupancy',
    xaxis: 'x', yaxis: 'y',
    y: labels, x: occ,
    marker: { color: OCC_COLOR, line: { width: 0 } },
    text: occ.map(v => `${fmtNum(v, v < 10 ? 1 : 0)}%`),
    textposition: 'outside', outsidetextfont: { size: 10, color: OCC_COLOR },
    cliponaxis: false,
    customdata: meta,
    hovertemplate:
      '<b>%{y}</b><br><i>%{customdata[0]}</i> \u00b7 %{customdata[1]}<br>' +
      `Recorded at %{customdata[3]} of %{customdata[4]} ${rateMeta.site_unit}s ` +
      '(%{x}%)<extra></extra>'
  }, {
    type: 'bar', orientation: 'h', name: `Detection rate (${rateMeta.unit})`,
    xaxis: 'x2', yaxis: 'y2',
    y: labels, x: rate,
    marker: { color: RATE_COLOR, line: { width: 0 } },
    text: rate.map(v => fmtNum(v, v >= 10 ? 1 : 2)),
    textposition: 'outside', outsidetextfont: { size: 10, color: RATE_COLOR },
    cliponaxis: false,
    customdata: meta,
    hovertemplate:
      '<b>%{y}</b><br><i>%{customdata[0]}</i> \u00b7 %{customdata[1]}<br>' +
      `%{x} ${rateMeta.unit}<br>%{customdata[2]:,} records total<extra></extra>`
  }];

  const maxOcc = Math.max(...occ, 1);
  const maxRate = Math.max(...rate, 0.001);
  const height = Math.max(340, rows.length * 22 + 130);
  // Taxon names go in the left margin, not between the two bar fields. A
  // central label channel has to be sized for the longest name ("Peromyscus
  // or Ochrotomys Species"), and anything narrower silently runs the label
  // underneath the detection-rate bar beside it.
  const layout = baseLayout({
    height,
    margin: { l: 210, r: 54, t: 46, b: 56 },
    showlegend: false,
    bargap: 0.28,
    xaxis: Object.assign({}, AXIS, {
      domain: [0, 0.49], anchor: 'y', autorange: 'reversed',
      // Headroom for the value label on the longest bar: without it the
      // leading taxon's "96%" is pushed off the axis and lands on its name.
      range: [maxOcc * 1.24, 0],
      title: { text: `\u2190 Naive occupancy (% of ${rateMeta.site_unit}s)`,
        font: { size: 12, color: OCC_COLOR } },
      zeroline: false, showgrid: true
    }),
    xaxis2: Object.assign({}, AXIS, {
      domain: [0.51, 1], anchor: 'y2',
      range: [0, maxRate * 1.14],
      title: { text: `${rateMeta.unit} \u2192`,
        font: { size: 12, color: RATE_COLOR } },
      zeroline: false, showgrid: true
    }),
    yaxis: Object.assign({}, AXIS, {
      domain: [0, 1], anchor: 'x', side: 'left',
      type: 'category', categoryorder: 'array', categoryarray: labels,
      tickfont: { size: rows.length > 40 ? 9 : 11, color: '#1c2127' },
      automargin: true,
      showgrid: false, zeroline: false, ticks: '', showline: false
    }),
    yaxis2: Object.assign({}, AXIS, {
      domain: [0, 1], anchor: 'x2',
      type: 'category', categoryorder: 'array', categoryarray: labels,
      showticklabels: false, showgrid: false, zeroline: false, ticks: '',
      showline: false
    }),
    shapes: [{
      type: 'line', x0: 0.5, x1: 0.5, y0: 0, y1: 1,
      xref: 'paper', yref: 'paper',
      line: { color: '#b9c0c7', width: 1 }
    }]
  });

  clear(container);
  await Plotly.newPlot(container, data, layout, PLOTLY_CONFIG);

  const stats = $('#tree-stats');
  if (stats) {
    clear(stats);
    const pairs = [
      ['Taxa shown', `${shown.length} of ${list.length}`],
      [`${rateMeta.site_unit[0].toUpperCase()}${rateMeta.site_unit.slice(1)}s`,
        fmtInt(rateMeta.n_sites)],
      ['Survey effort',
        `${fmtInt(rateMeta.denominator)} ${rateMeta.denominator_unit || 'sensor-days'}`]
    ];
    for (const [k, v] of pairs) {
      const item = el('span');
      item.appendChild(el('span', 'k', `${k}: `));
      item.appendChild(el('span', 'v', v));
      stats.appendChild(item);
    }
  }
}

/** Populate the BirdNET validation-group control from the data file. */
export function fillGroupControl(birdnet, current) {
  const sel = $('#species-group');
  if (!sel) return current;
  const prev = current !== undefined ? current : sel.value;
  clear(sel);
  const groups = (birdnet && Array.isArray(birdnet.groups)) ? birdnet.groups : [];
  for (const g of groups) {
    if (!g.n_species) continue;
    const o = el('option', null, `${g.label} \u2014 ${g.n_species} species`);
    o.value = g.id;
    sel.appendChild(o);
  }
  sel.value = Array.from(sel.options).some(o => o.value === prev)
    ? prev : (sel.options[0] ? sel.options[0].value : 'validated');
  return sel.value;
}

export function resizeCharts() {
  if (!window.Plotly) return;
  for (const id of ['#effort-chart', '#species-chart', '#activity-chart', '#tree-chart']) {
    const node = $(id);
    if (node && node.classList.contains('js-plotly-plot')) {
      try { window.Plotly.Plots.resize(node); } catch (e) { /* container hidden */ }
    }
  }
}
