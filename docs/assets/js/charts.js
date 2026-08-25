/* ==========================================================================
   charts.js -- effort and species charts (Plotly).

   Effort:  camera views -> effort.json .deployments[] filtered by view,
            one bar per deployment, sorted plot type (canonical) then duration.
            bird_frog_audio -> birdnet.json .plots[] n_recording_days, one bar
            per ARU plot.
   Species: species_ahdrift.json / species_parallel.json .species[] (sequences)
            or birdnet.json .species[] (unvalidated classifier detections).
   ========================================================================== */

import {
  $, el, clear, fmtInt, fmtDays, plotColor, orderPlotTypes, plotTypeRank,
  showPanelError, hidePanelError, showChartMessage, waitForGlobal
} from './data.js';

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

/* ======================================================== EFFORT (pure part) */

/**
 * Deployments belonging to a view, sorted by canonical plot type then by
 * descending duration so each plot-type block reads as a smooth ramp.
 */
export function effortRowsForView(effort, viewId) {
  const rows = (effort && Array.isArray(effort.deployments)) ? effort.deployments : [];
  return rows
    .filter(r => r.view === viewId)
    .map(r => ({
      key: r.deployment_id,
      plot: r.plot,
      plot_type: r.plot_type,
      days: Number(r.days),
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
      start: p.first_date,
      end: p.last_date,
      functioning: null
    }))
    .sort((a, b) =>
      plotTypeRank(a.plot_type) - plotTypeRank(b.plot_type) ||
      b.days - a.days ||
      String(a.key).localeCompare(String(b.key)));
}

/** Mean / median / min / max computed from the rows actually plotted. */
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
  const unit = viewId === 'bird_frog_audio' ? 'plots' : 'deployments';
  const pairs = [
    [unit === 'plots' ? 'Recording plots' : 'Deployments', fmtInt(s.n_deployments)],
    ['Total sensor-days', fmtInt(s.total_sensor_days)],
    ['Mean', `${fmtDays(round1(s.mean_days))} d`],
    ['Median', `${fmtDays(s.median_days)} d`],
    ['Range', `${fmtDays(s.min_days)}\u2013${fmtDays(s.max_days)} d`]
  ];
  for (const [k, v] of pairs) {
    const item = el('span');
    item.appendChild(el('span', 'k', `${k}: `));
    item.appendChild(el('span', 'v', v));
    box.appendChild(item);
  }
  // functioning breakdown, when the summary carries one
  if (summary && summary.functioning && Object.keys(summary.functioning).length) {
    const parts = Object.entries(summary.functioning)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}: ${fmtInt(v)}`);
    const item = el('span');
    item.appendChild(el('span', 'k', 'Camera status \u2014 '));
    item.appendChild(el('span', null, parts.join(', ')));
    box.appendChild(item);
  }
}

function round1(x) { return Number.isFinite(x) ? Math.round(x * 10) / 10 : x; }

export async function renderEffort(ctx) {
  const container = $('#effort-chart');
  if (!container) return;
  const { effort, birdnet, viewId } = ctx;
  hidePanelError('#effort-error');

  const isAru = viewId === 'bird_frog_audio';
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

  const sub = $('#effort-sub');
  if (sub) {
    sub.textContent = isAru
      ? 'Recording days per bird and frog ARU plot, one bar per plot, grouped by plot type and ordered by duration.'
      : 'One bar per camera deployment (a camera at one point over one date window), grouped by plot type and ordered by duration.';
  }

  const noteEl = $('#effort-note');
  if (noteEl) {
    const parts = [];
    if (!isAru && effort.note) parts.push(effort.note);
    if (!isAru && summary && derived &&
        Math.abs(summary.total_sensor_days - derived.total_sensor_days) > 0.5) {
      parts.push(`Note: the published summary reports ${fmtInt(summary.total_sensor_days)} sensor-days ` +
        `for this view while the ${fmtInt(rows.length)} plotted deployment rows total ` +
        `${fmtInt(derived.total_sensor_days)}.`);
    }
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

  // One trace per plot type -> real legend, canonical colors, single bar each.
  const types = orderPlotTypes(rows.map(r => r.plot_type));
  const positions = new Map(rows.map((r, i) => [r.key, i]));
  const traces = types.map(pt => {
    const sub = rows.filter(r => r.plot_type === pt);
    return {
      type: 'bar',
      name: pt,
      x: sub.map(r => positions.get(r.key)),
      y: sub.map(r => r.days),
      marker: { color: plotColor(pt), line: { width: 0 } },
      customdata: sub.map(r => [r.key, r.plot, pt, r.start || '\u2014', r.end || '\u2014',
        r.functioning || '\u2014']),
      hovertemplate:
        '<b>%{customdata[0]}</b><br>Plot %{customdata[1]} \u2014 %{customdata[2]}<br>' +
        '%{y} days<br>%{customdata[3]} to %{customdata[4]}' +
        (isAru ? '' : '<br>Status: %{customdata[5]}') +
        '<extra></extra>'
    };
  });

  const layout = baseLayout({
    barmode: 'relative',
    bargap: rows.length > 120 ? 0.05 : 0.2,
    height: 420,
    xaxis: Object.assign({}, AXIS, {
      title: { text: isAru ? 'ARU plot (ordered by plot type, then duration)'
                           : 'Camera deployment (ordered by plot type, then duration)' },
      showticklabels: isAru,
      tickmode: isAru ? 'array' : undefined,
      tickvals: isAru ? rows.map(r => positions.get(r.key)) : undefined,
      ticktext: isAru ? rows.map(r => r.plot) : undefined,
      tickangle: isAru ? -60 : 0,
      showgrid: false,
      range: [-1, rows.length]
    }),
    yaxis: Object.assign({}, AXIS, {
      title: { text: isAru ? 'Recording days' : 'Days deployed' },
      rangemode: 'tozero'
    })
  });

  clear(container);
  await Plotly.newPlot(container, traces, layout, PLOTLY_CONFIG);
}

/* ======================================================= SPECIES (pure part) */

/**
 * Normalize the two species schemas into one shape.
 * Camera: {common_name, latin_name, n_sequences, n_plots, by_plot_type}
 * BirdNET: {species, latin_name, n_detections, n_by_threshold, n_plots, by_plot_type}
 * `threshold` selects n_by_threshold[t] for BirdNET; null = all detections.
 */
export function normalizeSpecies(view, sources, threshold) {
  const kind = view && view.speciesKind;
  if (kind === 'birdnet') {
    const bn = sources.birdnet;
    if (!bn || !Array.isArray(bn.species)) return null;
    // Anthropogenic labels and "nocall" are not wildlife -- keep them out of a
    // species chart. birdnet.n_wildlife_species is the matching published count.
    return bn.species
      .filter(s => s.class && s.class !== 'Anthropogenic')
      .map(s => ({
        name: s.species,
        latin: s.latin_name,
        klass: s.class,
        order: s.order,
        count: pickCount(s, threshold),
        n_plots: s.n_plots,
        by_plot_type: s.by_plot_type || {}
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
    count: Number(s.n_sequences),
    n_plots: s.n_plots,
    by_plot_type: s.by_plot_type || {}
  })).filter(s => Number.isFinite(s.count) && s.count > 0);
}

function pickCount(s, threshold) {
  if (threshold === null || threshold === undefined || threshold === 'all') {
    return Number(s.n_detections);
  }
  const t = s.n_by_threshold || {};
  const v = t[String(threshold)];
  return Number.isFinite(Number(v)) ? Number(v) : 0;
}

export function sortSpecies(list, mode) {
  const arr = list.slice();
  if (mode === 'count_asc') arr.sort((a, b) => a.count - b.count || a.name.localeCompare(b.name));
  else if (mode === 'name_asc') arr.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  else if (mode === 'plots_desc') arr.sort((a, b) => (b.n_plots || 0) - (a.n_plots || 0) || b.count - a.count);
  else arr.sort((a, b) => b.count - a.count || String(a.name).localeCompare(String(b.name)));
  return arr;
}

/**
 * Top-N selection: always by count (so "top 25" means the 25 largest), then
 * re-sorted for display by the chosen sort mode.
 */
export function selectSpecies(list, topN, sortMode) {
  const byCount = sortSpecies(list, 'count_desc');
  const kept = (topN === 'all' || !Number.isFinite(Number(topN)))
    ? byCount
    : byCount.slice(0, Number(topN));
  return sortSpecies(kept, sortMode);
}

/* -------------------------------------------------------------- species DOM */

export async function renderSpecies(ctx) {
  const container = $('#species-chart');
  if (!container) return;
  const { view, sources, controls } = ctx;
  hidePanelError('#species-error');

  const isBirdnet = view.speciesKind === 'birdnet';
  const unit = isBirdnet ? 'unvalidated classifier detections' : 'sequences';
  const fileName = isBirdnet ? 'data/birdnet.json'
    : (view.speciesKind === 'ahdrift' ? 'data/species_ahdrift.json' : 'data/species_parallel.json');

  const list = normalizeSpecies(view, sources, isBirdnet ? controls.threshold : null);
  if (!list) {
    clear(container);
    clear($('#species-note'));
    showPanelError('#species-error', 'Species chart unavailable.',
      `${fileName} could not be loaded, so the species tally cannot be shown.`);
    return;
  }

  const src = isBirdnet ? sources.birdnet
    : (view.speciesKind === 'ahdrift' ? sources.species_ahdrift : sources.species_parallel);

  const sub = $('#species-sub');
  if (sub) {
    sub.textContent = isBirdnet
      ? `Raw BirdNET detections per species. Counts are ${unit} in 3-second windows, ` +
        `not verified occurrences, and are uncorrected for false positives or recording effort.`
      : `Wildlife Insights ${unit} per species. A sequence is one identification unit, ` +
        `not a count of individual animals, and is uncorrected for survey effort.`;
  }

  const note = $('#species-note');
  if (note) {
    const parts = [];
    if (isBirdnet) {
      if (src.note) parts.push(src.note);
      const shownThreshold = controls.threshold && controls.threshold !== 'all'
        ? `Showing detections at confidence \u2265 ${controls.threshold}.`
        : `Showing all detections at or above the ${src.confidence_floor ?? 'reported'} confidence floor.`;
      parts.push(shownThreshold);
      parts.push(`Anthropogenic and no-call labels are excluded from this chart; ` +
        `${fmtInt(src.n_wildlife_species)} wildlife species are reported in total.`);
    } else {
      if (src.coarse_note) parts.push(src.coarse_note);
      if (Number.isFinite(src.n_coarse_sequences)) {
        parts.push(`${fmtInt(src.n_coarse_sequences)} coarse or non-wildlife sequences are excluded; ` +
          `${fmtInt(src.n_identified_sequences)} identified sequences across ` +
          `${fmtInt(src.n_species)} species are charted.`);
      }
    }
    note.textContent = parts.join(' ');
  }

  if (!list.length) {
    showChartMessage(container, 'No species records for this view.',
      `${fileName} contained no species rows with detections above zero.`);
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

  // Horizontal bars. Plotly draws the first y entry at the bottom, so reverse
  // to put the top of the chosen sort order at the top of the chart.
  const rows = shown.slice().reverse();
  const labels = rows.map(s => s.name);
  const unitLabel = isBirdnet ? 'Detections' : 'Sequences';

  let traces;
  if (controls.stack === 'stacked') {
    const types = orderPlotTypes(
      rows.flatMap(s => Object.keys(s.by_plot_type || {}))
    );
    traces = types.map(pt => ({
      type: 'bar',
      orientation: 'h',
      name: pt,
      y: labels,
      x: rows.map(s => Number(s.by_plot_type && s.by_plot_type[pt]) || 0),
      marker: { color: plotColor(pt), line: { width: 0 } },
      customdata: rows.map(s => [s.latin || 'no Latin name recorded', s.klass || '\u2014',
        s.n_plots ?? '\u2014', s.count]),
      hovertemplate:
        `<b>%{y}</b><br><i>%{customdata[0]}</i><br>${pt}: %{x:,} ` +
        `${unitLabel.toLowerCase()}<br>Total: %{customdata[3]:,} across %{customdata[2]} plots<extra></extra>`
    }));
  } else {
    traces = [{
      type: 'bar',
      orientation: 'h',
      name: unitLabel,
      y: labels,
      x: rows.map(s => s.count),
      marker: { color: '#2f4a58', line: { width: 0 } },
      customdata: rows.map(s => [s.latin || 'no Latin name recorded', s.klass || '\u2014',
        s.n_plots ?? '\u2014']),
      hovertemplate:
        `<b>%{y}</b><br><i>%{customdata[0]}</i><br>%{customdata[1]}<br>` +
        `%{x:,} ${unitLabel.toLowerCase()} across %{customdata[2]} plots<extra></extra>`
    }];
  }

  const height = Math.max(360, rows.length * 19 + 110);
  const layout = baseLayout({
    barmode: 'stack',
    height,
    margin: { l: 190, r: 28, t: 12, b: 56 },
    showlegend: controls.stack === 'stacked',
    xaxis: Object.assign({}, AXIS, {
      title: { text: isBirdnet ? 'Unvalidated classifier detections' : 'Wildlife Insights sequences' },
      rangemode: 'tozero'
    }),
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
    caption.setAttribute('data-shown',
      `${shown.length} of ${list.length} species shown`);
  }
}

/** Populate the BirdNET confidence-threshold control from the data file. */
export function fillThresholdControl(birdnet) {
  const sel = $('#species-threshold');
  if (!sel) return;
  const current = sel.value;
  clear(sel);
  const all = el('option', null, 'All detections');
  all.value = 'all';
  sel.appendChild(all);
  const ths = (birdnet && Array.isArray(birdnet.thresholds)) ? birdnet.thresholds : [];
  for (const t of ths) {
    const o = el('option', null, `\u2265 ${t}`);
    o.value = String(t);
    sel.appendChild(o);
  }
  if (current && Array.from(sel.options).some(o => o.value === current)) sel.value = current;
}

export function resizeCharts() {
  if (!window.Plotly) return;
  for (const id of ['#effort-chart', '#species-chart']) {
    const node = $(id);
    if (node && node.classList.contains('js-plotly-plot')) {
      try { window.Plotly.Plots.resize(node); } catch (e) { /* container hidden */ }
    }
  }
}
