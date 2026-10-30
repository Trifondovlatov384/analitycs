(() => {
  const PUBLIC_TABS = [
    ["tab_deals", "Дашборд"],
    ["tab_pace", "Темп продаж"],
    ["tab_price", "Цена м²"],
    ["tab_mortgage", "Ипотека"],
    ["tab_complexes", "Комплексы"],
    ["tab_compare", "Сравнение"],
    ["tab_euler", "Пересечение аудиторий"],
    ["tab_heatmap", "Теплокарта"],
  ];
  const HIDDEN_TABS = {
    tab_egrz: "ЕГРЗ",
    tab_lot_growth: "Рост лота",
    tab_project_growth: "Рост проектов",
  };
  const ADMIN_TABS = new Set(["tab_lot_growth", "tab_project_growth"]);
  const MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const MONTHS_RU_FULL = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];

  const DEFAULT_FILTERS = {
    source: "all",
    agglomeration: "all",
    year: null,
    date_from: "",
    date_to: "",
    months: [],
    city: [],
    developer: [],
    project: [],
    type_lot: [],
    mortgage_mode: "all",
    budget_min: "",
    budget_max: "",
    object: "",
    district: [],
    selected: [],
    top_n: 40,
    line_shape: "linear",
    data_quality: ["exclude_wholesale", "known_budget_only"],
    target_budget: 8000000,
    delta_budget: 3000000,
    type_lot_single: "",
    projects: [],
    search: "",
    region: [],
    work_type: [],
    access: "",
    pace_window: 3,
    gran: "month",
  };

  const state = {
    tab: "tab_deals",
    meta: null,
    dims: null,
    filters: structuredClone(DEFAULT_FILTERS),
    charts: {},
    controllers: [],
    msOptions: {},
    tableSort: {},
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* ───────────────────────── Formatting ───────────────────────── */

  const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

  function fmt(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number") return Number.isFinite(v) ? nf0.format(v) : "—";
    return String(v);
  }

  /** 1 234 567 890 → { num: "1,23", unit: "млрд" } */
  function compact(v) {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return { num: "—", unit: "" };
    const n = Number(v);
    const a = Math.abs(n);
    if (a >= 1e9) return { num: nf2.format(n / 1e9), unit: "млрд" };
    if (a >= 1e6) return { num: nf1.format(n / 1e6), unit: "млн" };
    if (a >= 1e4) return { num: nf0.format(n / 1e3), unit: "тыс" };
    return { num: nf0.format(n), unit: "" };
  }
  const compactStr = (v) => {
    const c = compact(v);
    return c.unit ? `${c.num} ${c.unit}` : c.num;
  };

  function monthLabel(key) {
    // "2026-03" → "мар 26", "2026-Q1" → "1 кв 26"
    const q = /^(\d{4})-Q(\d)$/.exec(String(key || ""));
    if (q) return `${q[2]} кв ${q[1].slice(2)}`;
    const m = /^(\d{4})-(\d{2})/.exec(String(key || ""));
    if (!m) return String(key ?? "");
    return `${MONTHS_RU[Number(m[2]) - 1]} ${m[1].slice(2)}`;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function palette() {
    return {
      ink: cssVar("--ink") || "#16181d",
      muted: cssVar("--muted") || "#6f747c",
      faint: cssVar("--faint") || "#a3a7ad",
      line: cssVar("--line") || "#e7e5df",
      sea: cssVar("--sea") || "#0e7490",
      sand: cssVar("--sand") || "#c98a2b",
      surface: cssVar("--surface") || "#fff",
    };
  }

  function toast(msg) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (el.hidden = true), 3500);
  }

  /* ───────────────────────── URL state ───────────────────────── */

  const SCALAR_KEYS = [
    "source", "agglomeration", "year", "date_from", "date_to", "mortgage_mode", "budget_min", "budget_max",
    "object", "line_shape", "search", "type_lot_single", "top_n", "target_budget", "delta_budget",
    "pace_window", "gran",
  ];
  const LIST_KEYS = ["months", "city", "developer", "project", "type_lot", "district", "selected", "projects", "region", "work_type", "data_quality"];

  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.tab = p.get("tab") || "tab_deals";
    state.filters.access = p.get("access") || "";
    for (const k of SCALAR_KEYS) if (p.has(k)) state.filters[k] = p.get(k);
    for (const k of LIST_KEYS) if (p.has(k)) state.filters[k] = p.get(k).split(",").filter(Boolean);
    for (const k of ["year", "top_n", "target_budget", "delta_budget", "pace_window"]) {
      if (state.filters[k] !== null && state.filters[k] !== "") {
        const n = Number(state.filters[k]);
        state.filters[k] = Number.isFinite(n) ? n : DEFAULT_FILTERS[k];
      }
    }
  }

  function writeUrl() {
    const p = new URLSearchParams();
    const f = state.filters;
    if (state.tab !== "tab_deals") p.set("tab", state.tab);
    if (f.access) p.set("access", f.access);
    const putScalar = (k, skip = []) => {
      const v = f[k];
      if (v === null || v === undefined || v === "" || skip.includes(v)) return;
      p.set(k, String(v));
    };
    putScalar("source", ["all"]);
    putScalar("agglomeration", ["all"]);
    putScalar("year");
    putScalar("date_from");
    putScalar("date_to");
    putScalar("mortgage_mode", ["all"]);
    putScalar("budget_min");
    putScalar("budget_max");
    putScalar("object");
    putScalar("line_shape", ["linear"]);
    if (state.tab === "tab_egrz") putScalar("search");
    if (state.tab === "tab_euler") {
      putScalar("type_lot_single");
      putScalar("target_budget", [8000000]);
      putScalar("delta_budget", [3000000]);
    }
    if (state.tab === "tab_heatmap") putScalar("top_n", [40]);
    if (state.tab === "tab_pace") putScalar("pace_window", [3]);
    if (state.tab === "tab_price") putScalar("gran", ["month"]);
    for (const k of ["months", "city", "developer", "project", "type_lot", "district", "selected", "projects", "region", "work_type"]) {
      if (f[k] && f[k].length) p.set(k, f[k].join(","));
    }
    const dq = f.data_quality || [];
    if (state.tab === "tab_heatmap" && !(dq.length === 2 && dq.includes("exclude_wholesale") && dq.includes("known_budget_only"))) {
      p.set("data_quality", dq.join(",") || "none");
    }
    const next = p.toString();
    history.replaceState(null, "", next ? `?${next}` : location.pathname);
  }

  function filterQuery(extra = {}) {
    const f = { ...state.filters, ...extra };
    const p = new URLSearchParams();
    const keys = [
      "source", "agglomeration", "year", "date_from", "date_to", "months", "city", "developer", "project", "type_lot",
      "mortgage_mode", "budget_min", "budget_max", "object", "month", "district", "selected", "top_n", "line_shape",
      "data_quality", "target_budget", "delta_budget", "type_lot_single", "projects", "search", "region", "work_type", "access",
      "pace_window", "gran",
    ];
    for (const k of keys) {
      const v = f[k];
      if (v === null || v === undefined || v === "") continue;
      if (Array.isArray(v)) {
        if (v.length) p.set(k, v.join(","));
        continue;
      }
      p.set(k, String(v));
    }
    return p.toString();
  }

  /* ───────────────────────── Fetching ───────────────────────── */

  function abortAll() {
    for (const c of state.controllers) c.abort();
    state.controllers = [];
  }

  async function api(path, { signal, extra } = {}) {
    const q = filterQuery(extra);
    const res = await fetch(q ? `${path}?${q}` : path, { credentials: "same-origin", signal });
    if (res.status === 401) {
      location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `Ошибка ${res.status}`);
    }
    return res.json();
  }

  /** Runs a loader; on failure shows the error inside `el` instead of an endless skeleton. */
  function track(fn, els = []) {
    const c = new AbortController();
    state.controllers.push(c);
    return fn(c.signal)
      .catch((err) => {
        if (err.name === "AbortError" || err.message === "unauthorized") return;
        console.error(err);
        for (const el of [els].flat().filter(Boolean)) {
          clearSkeleton(el);
          el.innerHTML = `<div class="error-box">Не удалось загрузить: ${escapeHtml(err.message)}</div>`;
        }
      })
      .finally(() => {
        state.controllers = state.controllers.filter((x) => x !== c);
      });
  }

  function clearSkeleton(el) {
    el?.classList.remove("skeleton");
  }
  function setLoading(el) {
    if (!el) return;
    el.classList.add("skeleton");
  }

  /* ───────────────────────── Charts ───────────────────────── */

  let chartReady = null;
  function ensureChartJs() {
    if (window.Chart) return Promise.resolve();
    if (chartReady) return chartReady;
    chartReady = new Promise((resolve) => {
      // jsDelivr sometimes is slow/blocked — fall back to unpkg.
      const s = document.createElement("script");
      s.src = "https://unpkg.com/chart.js@4.4.7/dist/chart.umd.min.js";
      s.onload = () => resolve();
      s.onerror = () => resolve();
      document.head.appendChild(s);
    });
    return chartReady;
  }

  function applyChartDefaults() {
    if (!window.Chart || applyChartDefaults.done) return;
    applyChartDefaults.done = true;
    const c = palette();
    const d = Chart.defaults;
    d.font.family = cssVar("--font") || "Inter, system-ui, sans-serif";
    d.font.size = 12;
    d.color = c.muted;
    d.borderColor = c.line;
    d.animation.duration = 350;
    d.plugins.legend.labels.usePointStyle = true;
    d.plugins.legend.labels.pointStyle = "circle";
    d.plugins.legend.labels.boxWidth = 7;
    d.plugins.legend.labels.boxHeight = 7;
    d.plugins.legend.labels.padding = 14;
    d.plugins.tooltip.backgroundColor = c.ink;
    d.plugins.tooltip.titleColor = c.surface;
    d.plugins.tooltip.bodyColor = c.surface;
    d.plugins.tooltip.padding = 10;
    d.plugins.tooltip.cornerRadius = 8;
    d.plugins.tooltip.boxPadding = 4;
    d.plugins.tooltip.usePointStyle = true;
    d.plugins.tooltip.titleFont = { weight: "600" };
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function ensureCanvas(container) {
    clearSkeleton(container);
    container.innerHTML = "";
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);
    return canvas;
  }

  function emptyState(container, title, sub = "") {
    clearSkeleton(container);
    container.innerHTML = `<div class="empty"><strong>${escapeHtml(title)}</strong>${escapeHtml(sub)}</div>`;
  }

  function gradient(ctx, color) {
    const { chart } = ctx;
    const area = chart.chartArea;
    if (!area) return "transparent";
    const g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, color + "33");
    g.addColorStop(1, color + "00");
    return g;
  }

  function lineChart(key, container, labels, datasets, { tension = 0, money = false, y1 = false } = {}) {
    destroyChart(key);
    if (!window.Chart) return emptyState(container, "Графики не загрузились", "Проверьте соединение и обновите страницу");
    if (!labels.length) return emptyState(container, "Нет данных", "Попробуйте ослабить фильтры");
    const canvas = ensureCanvas(container);
    const c = palette();
    const tick = (v) => (money ? compactStr(v) : nf0.format(v));
    const scales = {
      x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 14, callback: (_v, i) => monthLabel(labels[i]) } },
      y: { beginAtZero: !money, grid: { color: c.line }, border: { display: false }, ticks: { callback: tick, maxTicksLimit: 6 } },
    };
    if (y1) {
      scales.y1 = { position: "right", beginAtZero: true, grid: { display: false }, border: { display: false }, ticks: { maxTicksLimit: 6 } };
    }
    state.charts[key] = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: datasets.length > 1, position: "top", align: "end" },
          tooltip: {
            callbacks: {
              title: (items) => monthLabel(labels[items[0].dataIndex]),
              label: (ctx) => {
                const v = ctx.parsed.y;
                const isMoney = money && ctx.dataset.yAxisID !== "y1";
                return ` ${ctx.dataset.label}: ${isMoney ? compactStr(v) + " ₽" : nf0.format(v)}`;
              },
            },
          },
        },
        elements: {
          line: { tension, borderWidth: 2 },
          point: { radius: 0, hoverRadius: 4, hitRadius: 8 },
        },
        scales,
      },
    });
  }

  function barChart(key, container, labels, values, { horizontal = true, color, monthAxis = false, tooltipSuffix = "" } = {}) {
    destroyChart(key);
    if (!window.Chart) return emptyState(container, "Графики не загрузились");
    if (!labels.length) return emptyState(container, "Нет данных", "Попробуйте ослабить фильтры");
    const canvas = ensureCanvas(container);
    const c = palette();
    const catTicks = monthAxis ? { callback: (_v, i) => monthLabel(labels[i]), maxRotation: 0, autoSkipPadding: 10 } : {};
    state.charts[key] = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: color || c.sea, borderRadius: 5, borderSkipped: false, maxBarThickness: horizontal ? 16 : 42 }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => (monthAxis ? monthLabel(labels[items[0].dataIndex]) : labels[items[0].dataIndex]),
              label: (ctx) => ` ${nf0.format(horizontal ? ctx.parsed.x : ctx.parsed.y)}${tooltipSuffix}`,
            },
          },
        },
        scales: horizontal
          ? {
              x: { beginAtZero: true, grid: { color: c.line }, border: { display: false } },
              y: { grid: { display: false }, border: { display: false }, ticks: { autoSkip: false, color: c.ink } },
            }
          : {
              x: { grid: { display: false }, ticks: catTicks },
              y: { beginAtZero: true, grid: { color: c.line }, border: { display: false } },
            },
      },
    });
  }

  function scatterChart(key, container, points, onClick) {
    destroyChart(key);
    if (!window.Chart) return emptyState(container, "Графики не загрузились");
    if (!points.length) return emptyState(container, "Нет данных", "Попробуйте ослабить фильтры");
    const canvas = ensureCanvas(container);
    const c = palette();
    const maxDeals = Math.max(...points.map((p) => p.deals || 1), 1);
    const r = (d) => 3 + Math.sqrt((d || 1) / maxDeals) * 16;
    const selected = points.filter((p) => p.selected);
    const rest = points.filter((p) => !p.selected);
    const toPt = (p) => ({ x: p.x, y: p.y, name: p.name, deals: p.deals, r: r(p.deals) });
    state.charts[key] = new Chart(canvas, {
      type: "bubble",
      data: {
        datasets: [
          { label: "Комплексы", data: rest.map(toPt), backgroundColor: c.sea + "40", borderColor: c.sea + "99", borderWidth: 1 },
          { label: "Выбранные", data: selected.map(toPt), backgroundColor: c.sand + "cc", borderColor: c.ink, borderWidth: 1.5 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "top", align: "end" },
          tooltip: {
            callbacks: {
              title: (items) => items[0].raw.name || "",
              label: (ctx) => [
                ` Цена м²: ${nf0.format(ctx.raw.x)} ₽`,
                ` Средний чек: ${compactStr(ctx.raw.y)} ₽`,
                ` Сделок: ${nf0.format(ctx.raw.deals || 0)}`,
              ],
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Цена м², ₽" }, grid: { color: c.line }, border: { display: false }, ticks: { callback: compactStr } },
          y: { title: { display: true, text: "Средний чек, ₽" }, grid: { color: c.line }, border: { display: false }, ticks: { callback: compactStr } },
        },
        onHover(e, els) {
          e.native.target.style.cursor = els.length ? "pointer" : "default";
        },
        onClick(_e, elements) {
          if (!elements.length || !onClick) return;
          const el = elements[0];
          const raw = state.charts[key].data.datasets[el.datasetIndex].data[el.index];
          if (raw?.name) onClick(raw.name);
        },
      },
    });
  }

  /* ───────────────────────── Lists & tables ───────────────────────── */

  function renderBarList(container, items, { variant = "", suffix = "" } = {}) {
    clearSkeleton(container);
    if (!items.length) return emptyState(container, "Нет данных");
    const vals = items.map((i) => Number(i.deals ?? i.value ?? 0));
    const max = Math.max(...vals.map(Math.abs), 1);
    container.innerHTML = `<div class="bar-list">${items
      .map((i, idx) => {
        const v = vals[idx];
        const pct = Math.max(2, Math.round((Math.abs(v) / max) * 100));
        const cls = v < 0 ? "bar-fill--neg" : variant;
        const shown = suffix ? `${nf1.format(v)}${suffix}` : nf0.format(v);
        return `<div class="bar-row"><span class="bar-rank">${idx + 1}</span><span class="bar-name" title="${escapeHtml(i.name)}">${escapeHtml(i.name)}</span><span class="bar-val">${shown}</span><div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div></div>`;
      })
      .join("")}</div>`;
  }

  /**
   * columns: [{ key, label, num?, money?, wrap?, render? }]
   * Sorting is done client-side by clicking a header.
   */
  function renderTable(container, rows, columns, { rowKey = "object", selected = [], clickable = false, id } = {}) {
    clearSkeleton(container);
    if (!rows.length) return emptyState(container, "Нет данных", "Попробуйте ослабить фильтры");
    const sortKey = id || container.id;
    const sort = state.tableSort[sortKey];
    let data = rows;
    if (sort) {
      const dir = sort.dir === "asc" ? 1 : -1;
      data = [...rows].sort((a, b) => {
        const x = a[sort.key];
        const y = b[sort.key];
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
        return String(x).localeCompare(String(y), "ru") * dir;
      });
    }
    const sel = new Set(selected);
    const head = columns
      .map((c) => {
        const active = sort?.key === c.key;
        const arrow = active ? `<span class="sort">${sort.dir === "asc" ? "▲" : "▼"}</span>` : "";
        return `<th class="${c.num ? "num" : ""} ${active ? "is-sorted" : ""}" data-sort="${c.key}">${escapeHtml(c.label)}${arrow}</th>`;
      })
      .join("");
    const body = data
      .map((r) => {
        const key = r[rowKey];
        const cells = columns
          .map((c) => {
            const raw = r[c.key];
            const val = c.render ? c.render(raw, r) : c.money ? (raw == null ? "—" : nf0.format(raw)) : fmt(raw);
            return `<td class="${c.num || c.money ? "num" : ""} ${c.wrap ? "wrap" : ""}">${c.render ? val : escapeHtml(val)}</td>`;
          })
          .join("");
        return `<tr class="${sel.has(key) ? "is-selected" : ""}" data-key="${escapeHtml(String(key ?? ""))}">${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<table class="data-table ${clickable ? "is-clickable" : ""}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    $("thead", container).onclick = (e) => {
      const th = e.target.closest("th[data-sort]");
      if (!th) return;
      const k = th.dataset.sort;
      const cur = state.tableSort[sortKey];
      state.tableSort[sortKey] = { key: k, dir: cur?.key === k && cur.dir === "desc" ? "asc" : "desc" };
      renderTable(container, rows, columns, { rowKey, selected, clickable, id });
    };
  }

  /* ───────────────────────── Heatmap ───────────────────────── */

  const HEAT_PALETTES = {
    // Classic: red (few deals) → yellow → green (many deals)
    rg: [
      [0, [215, 48, 39]],
      [0.5, [254, 224, 139]],
      [1, [26, 152, 80]],
    ],
    // Sequential blue: light → deep, friendlier for colour-blind viewers
    sea: [
      [0, [230, 243, 246]],
      [0.35, [124, 196, 214]],
      [0.7, [14, 116, 144]],
      [1, [8, 61, 77]],
    ],
  };

  function getHeatPalette() {
    try {
      const v = localStorage.getItem("hmPalette");
      if (v && HEAT_PALETTES[v]) return v;
    } catch (_) {
      /* storage unavailable */
    }
    return "rg";
  }

  function setHeatPalette(name) {
    try {
      localStorage.setItem("hmPalette", name);
    } catch (_) {
      /* storage unavailable */
    }
  }

  function syncPaletteUi() {
    const cur = getHeatPalette();
    $$("#hm-palette .seg").forEach((b) => b.classList.toggle("is-active", b.dataset.palette === cur));
    $(".hm-legend")?.classList.toggle("is-rg", cur === "rg");
  }

  function heatColor(t) {
    const stops = HEAT_PALETTES[getHeatPalette()];
    const x = Math.max(0, Math.min(1, t));
    let i = 0;
    while (i < stops.length - 2 && x > stops[i + 1][0]) i += 1;
    const [aT, aC] = stops[i];
    const [bT, bC] = stops[i + 1];
    const u = (x - aT) / (bT - aT || 1);
    const rgb = aC.map((v, k) => Math.round(v + (bC[k] - v) * u));
    const lum = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
    return { bg: `rgb(${rgb.join(",")})`, fg: lum < 0.5 ? "#fff" : "#16181d" };
  }

  function renderHeatmap(container, data) {
    state.lastHeatmap = data;
    syncPaletteUi();
    clearSkeleton(container);
    const { objects = [], display = [], months = [], month_keys = [], z = [] } = data;
    if (!months.length || !display.length) return emptyState(container, "Нет данных", "Попробуйте ослабить фильтры");
    const nonzero = z.flat().filter((v) => v > 0).sort((a, b) => a - b);
    const q = (p) => nonzero[Math.min(nonzero.length - 1, Math.max(0, Math.floor((nonzero.length - 1) * p)))] ?? 1;
    let zmin = q(0.05);
    let zmax = q(0.95);
    if (zmax <= zmin) {
      zmin = nonzero[0] || 0;
      zmax = nonzero[nonzero.length - 1] || 1;
    }
    const span = zmax - zmin || 1;
    const head = `<tr><th class="row-label">Комплекс</th>${months.map((m) => `<th>${escapeHtml(m)}</th>`).join("")}</tr>`;
    const body = display
      .map((name, i) => {
        const obj = objects[i] || String(name).replace(/\s\(\d+\)$/, "");
        const total = (z[i] || []).reduce((s, v) => s + (Number(v) || 0), 0);
        const cells = (z[i] || [])
          .map((v, j) => {
            const vv = Number(v) || 0;
            const attrs = `data-object="${escapeHtml(obj)}" data-month="${escapeHtml(month_keys[j] || months[j])}" title="${escapeHtml(obj)} · ${escapeHtml(months[j])}: ${vv}"`;
            if (vv <= 0) return `<td class="hm-zero" ${attrs}></td>`;
            const { bg, fg } = heatColor((vv - zmin) / span);
            return `<td style="background:${bg};color:${fg}" ${attrs}>${vv}</td>`;
          })
          .join("");
        return `<tr><th class="row-label" title="${escapeHtml(obj)}">${escapeHtml(obj)}<span class="tot">${nf0.format(total)}</span></th>${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  /* ───────────────────────── Filters UI ───────────────────────── */

  function optionHtml(options, selected, { emptyLabel = null } = {}) {
    let html = emptyLabel != null ? `<option value="">${escapeHtml(emptyLabel)}</option>` : "";
    for (const o of options || []) {
      const isSel = String(selected ?? "") === String(o.value);
      html += `<option value="${escapeHtml(o.value)}" ${isSel ? "selected" : ""}>${escapeHtml(o.label)}</option>`;
    }
    return html;
  }

  function isSet(name, value) {
    const def = DEFAULT_FILTERS[name];
    if (Array.isArray(value)) return value.length > 0;
    if (name === "year") return false;
    if (name === "source" && state.meta?.sources?.default) return value !== state.meta.sources.default;
    return value !== "" && value !== null && value !== undefined && String(value) !== String(def ?? "");
  }

  function filterSelect(name, label, options, value, { emptyLabel = null } = {}) {
    return `<div class="filter ${isSet(name, value) ? "is-set" : ""}"><label for="f-${name}">${escapeHtml(label)}</label><select id="f-${name}" data-filter="${name}">${optionHtml(options, value, { emptyLabel })}</select></div>`;
  }

  function filterInput(name, label, type, value, attrs = "") {
    return `<div class="filter ${isSet(name, value) ? "is-set" : ""}"><label for="f-${name}">${escapeHtml(label)}</label><input id="f-${name}" type="${type}" data-filter="${name}" value="${escapeHtml(value ?? "")}" ${attrs}></div>`;
  }

  function filterMulti(name, label, options, value, { max = null, wide = false } = {}) {
    state.msOptions[name] = { options: options || [], max };
    const selected = value || [];
    const labelOf = (v) => (options || []).find((o) => String(o.value) === String(v))?.label ?? v;
    const text = selected.length
      ? selected.length === 1
        ? labelOf(selected[0])
        : `${labelOf(selected[0])} и ещё ${selected.length - 1}`
      : "Все";
    return `<div class="filter ms ${wide ? "filter--wide" : ""} ${selected.length ? "is-set" : ""}" data-ms="${name}">
      <span class="filter-label">${escapeHtml(label)}</span>
      <button type="button" class="ms-trigger" aria-haspopup="listbox" aria-expanded="false">
        <span class="ms-trigger-text ${selected.length ? "" : "is-placeholder"}">${escapeHtml(text)}</span>
        ${selected.length > 1 ? `<span class="ms-count">${selected.length}</span>` : ""}
        <span class="ms-caret">▾</span>
      </button>
    </div>`;
  }

  /* Multi-select popover: search, checkboxes, apply on close. */
  let openMs = null;

  function closeMs({ apply = true } = {}) {
    if (!openMs) return;
    const { name, draft, initial, root } = openMs;
    root.querySelector(".ms-pop")?.remove();
    root.querySelector(".ms-trigger")?.setAttribute("aria-expanded", "false");
    openMs = null;
    const changed = draft.length !== initial.length || draft.some((v) => !initial.includes(v));
    if (apply && changed) {
      state.filters[name] = draft;
      onFilterValueChanged(name);
    }
  }

  function openMultiSelect(root) {
    const name = root.dataset.ms;
    if (openMs?.name === name) return closeMs();
    closeMs();
    const { options, max } = state.msOptions[name] || { options: [] };
    const initial = [...(state.filters[name] || [])];
    openMs = { name, draft: [...initial], initial, root };
    const pop = document.createElement("div");
    pop.className = "ms-pop";
    pop.innerHTML = `
      ${options.length > 8 ? '<input type="search" class="ms-search" placeholder="Поиск…" autocomplete="off">' : ""}
      <div class="ms-list" role="listbox" aria-multiselectable="true"></div>
      <div class="ms-actions">
        <button type="button" class="btn" data-ms-act="clear">Очистить</button>
        <button type="button" class="btn btn--primary" data-ms-act="apply">Готово</button>
      </div>`;
    root.appendChild(pop);
    root.querySelector(".ms-trigger").setAttribute("aria-expanded", "true");
    const list = pop.querySelector(".ms-list");

    const draw = (query = "") => {
      const qn = query.trim().toLowerCase().replaceAll("ё", "е");
      const sel = new Set(openMs.draft.map(String));
      // selected first, then the rest
      const filtered = options.filter((o) => !qn || String(o.label).toLowerCase().replaceAll("ё", "е").includes(qn));
      const ordered = [...filtered.filter((o) => sel.has(String(o.value))), ...filtered.filter((o) => !sel.has(String(o.value)))];
      if (!ordered.length) {
        list.innerHTML = '<div class="ms-empty">Ничего не найдено</div>';
        return;
      }
      list.innerHTML = ordered
        .slice(0, 400)
        .map(
          (o) =>
            `<label class="ms-item"><input type="checkbox" value="${escapeHtml(o.value)}" ${sel.has(String(o.value)) ? "checked" : ""}><span title="${escapeHtml(o.label)}">${escapeHtml(o.label)}</span></label>`
        )
        .join("");
    };
    draw();

    pop.addEventListener("input", (e) => {
      if (e.target.classList.contains("ms-search")) draw(e.target.value);
    });
    pop.addEventListener("change", (e) => {
      const cb = e.target.closest('input[type="checkbox"]');
      if (!cb) return;
      const v = cb.value;
      if (cb.checked) {
        if (max && openMs.draft.length >= max) {
          cb.checked = false;
          toast(`Можно выбрать не больше ${max}`);
          return;
        }
        openMs.draft.push(v);
      } else {
        openMs.draft = openMs.draft.filter((x) => String(x) !== v);
      }
    });
    pop.addEventListener("click", (e) => {
      const act = e.target.closest("[data-ms-act]")?.dataset.msAct;
      if (act === "clear") {
        openMs.draft = [];
        draw(pop.querySelector(".ms-search")?.value || "");
      } else if (act === "apply") {
        closeMs();
      }
    });
    pop.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMs({ apply: false });
      if (e.key === "Enter" && e.target.classList.contains("ms-search")) closeMs();
    });
    (pop.querySelector(".ms-search") || pop.querySelector("input"))?.focus();
  }

  function commonFilterBlocks() {
    const meta = state.meta || {};
    const dims = state.dims || {};
    const f = state.filters;
    const years = (meta.years || []).map((y) => ({ label: String(y), value: y }));
    const sources = meta.sources?.options || [];
    const blocks = [];
    if (meta.sources?.show !== false && sources.length > 1) blocks.push(filterSelect("source", "Источник", sources, f.source));
    blocks.push(
      filterSelect(
        "agglomeration",
        "Агломерация",
        [
          { label: "Все", value: "all" },
          { label: "Анапа", value: "Анапа" },
          { label: "Сочи", value: "Сочи" },
          { label: "Крым", value: "Крым" },
          { label: "Без групп", value: "без групп" },
        ],
        f.agglomeration
      )
    );
    blocks.push(filterSelect("year", "Год", years, f.year, { emptyLabel: "Все годы" }));
    blocks.push(filterMulti("months", "Месяцы", (dims.months || []).map((o) => ({ ...o, label: monthLabelFull(o.value) })), f.months));
    blocks.push(filterInput("date_from", "С даты", "date", f.date_from, minMaxAttrs()));
    blocks.push(filterInput("date_to", "По дату", "date", f.date_to, minMaxAttrs()));
    blocks.push(filterInput("budget_min", "Бюджет от, млн ₽", "number", f.budget_min, 'min="0" step="0.5" placeholder="0"'));
    blocks.push(filterInput("budget_max", "Бюджет до, млн ₽", "number", f.budget_max, 'min="0" step="0.5" placeholder="∞"'));
    blocks.push(filterMulti("city", "Город", dims.city || [], f.city));
    blocks.push(
      filterSelect(
        "mortgage_mode",
        "Оплата",
        [
          { label: "Все сделки", value: "all" },
          { label: "Ипотека", value: "mortgage" },
          { label: "Без ипотеки", value: "non_mortgage" },
        ],
        f.mortgage_mode
      )
    );
    return blocks;
  }

  function monthLabelFull(key) {
    const q = /^(\d{4})-Q(\d)$/.exec(String(key || ""));
    if (q) return `${q[2]} квартал ${q[1]}`;
    const m = /^(\d{4})-(\d{2})/.exec(String(key || ""));
    return m ? `${MONTHS_RU_FULL[Number(m[2]) - 1]} ${m[1]}` : String(key);
  }

  function minMaxAttrs() {
    const b = state.meta?.date_bounds || {};
    return `${b.min ? `min="${b.min}"` : ""} ${b.max ? `max="${b.max}"` : ""}`;
  }

  function renderFilters() {
    const dims = state.dims || {};
    const f = state.filters;
    const card = $("#filters-card");
    const top = $("#filters");
    const side = $("#heatmap-filters");
    state.msOptions = {};

    if (state.tab === "tab_heatmap") {
      card.hidden = true;
      top.innerHTML = "";
      const blocks = commonFilterBlocks();
      blocks.push(filterMulti("district", "Район", dims.district || [], f.district));
      blocks.push(filterMulti("type_lot", "Тип объекта", dims.type_lot || [], f.type_lot));
      const dq = new Set(f.data_quality || []);
      blocks.push(`<div class="filter"><span class="filter-label">Качество данных</span>
        <label class="check"><input type="checkbox" data-quality="exclude_wholesale" ${dq.has("exclude_wholesale") ? "checked" : ""}> Без оптовых сделок</label>
        <label class="check"><input type="checkbox" data-quality="known_budget_only" ${dq.has("known_budget_only") ? "checked" : ""}> Только с известным бюджетом</label>
      </div>`);
      blocks.push(filterInput("top_n", "Сколько комплексов показать", "number", f.top_n, 'min="5" max="200" step="5"'));
      side.innerHTML = `<header class="widget-head"><div><h2 class="widget-title">Фильтры</h2></div><button type="button" class="btn btn--link" data-reset>Сбросить</button></header><div class="filters-stack">${blocks.join("")}</div>`;
      return;
    }

    card.hidden = false;
    let blocks = commonFilterBlocks();
    if (state.tab === "tab_deals") {
      blocks.push(filterMulti("developer", "Застройщик", dims.developer || [], f.developer));
      blocks.push(filterMulti("project", "Проект", dims.project || [], f.project));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    } else if (state.tab === "tab_pace" || state.tab === "tab_mortgage") {
      blocks.push(filterMulti("developer", "Застройщик", dims.developer || [], f.developer));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    } else if (state.tab === "tab_price") {
      blocks.push(filterMulti("developer", "Застройщик", dims.developer || [], f.developer));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
      blocks.push(filterMulti("selected", "Комплексы на графике (до 6)", dims.project || [], f.selected, { max: 6, wide: true }));
    } else if (state.tab === "tab_complexes") {
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
      blocks.push(filterSelect("object", "Комплекс", dims.object || [], f.object, { emptyLabel: "Выберите комплекс" }));
    } else if (state.tab === "tab_compare") {
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    } else if (state.tab === "tab_euler") {
      blocks.push(filterSelect("type_lot_single", "Тип", dims.type_lot || [], f.type_lot_single, { emptyLabel: "Все типы" }));
      blocks.push(filterMulti("projects", "Проекты (2–3)", dims.project || [], f.projects, { max: 3, wide: true }));
      blocks.push(filterInput("target_budget", "Целевой бюджет, ₽", "number", f.target_budget, 'step="500000" min="0"'));
      blocks.push(filterInput("delta_budget", "Коридор ±, ₽", "number", f.delta_budget, 'step="500000" min="0"'));
    } else if (state.tab === "tab_egrz") {
      blocks = [
        `<div class="filter filter--wide"><label for="f-search">Поиск</label><input id="f-search" type="search" data-filter="search" value="${escapeHtml(f.search || "")}" placeholder="Объект, застройщик, номер заключения…"></div>`,
        filterMulti("region", "Регион", state.egrzMeta?.regions || [], f.region),
        filterMulti("work_type", "Вид работ", state.egrzMeta?.work_types || [], f.work_type),
      ];
    } else if (ADMIN_TABS.has(state.tab)) {
      blocks.push(filterMulti("district", "Район", dims.district || [], f.district));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    }
    top.innerHTML = blocks.join("");
    renderFiltersFoot();
  }

  function activeFilterCount() {
    const f = state.filters;
    let n = 0;
    for (const k of ["agglomeration", "date_from", "date_to", "mortgage_mode", "budget_min", "budget_max", "object", "type_lot_single"]) {
      if (isSet(k, f[k])) n += 1;
    }
    for (const k of ["months", "city", "developer", "project", "type_lot", "district"]) if ((f[k] || []).length) n += 1;
    if (isSet("source", f.source)) n += 1;
    return n;
  }

  function periodText() {
    const f = state.filters;
    if (state.tab === "tab_pace") {
      return `Окно: последние ${f.pace_window} мес.${f.date_to ? ` до ${f.date_to}` : " данных"} — год и «С даты» здесь не используются`;
    }
    if (f.date_from || f.date_to) return `Период: ${f.date_from || "…"} — ${f.date_to || "…"}`;
    if (f.year) return `Период: ${f.year} год${f.months?.length ? `, месяцев: ${f.months.length}` : ""}`;
    return "Период: все годы";
  }

  function renderFiltersFoot() {
    const foot = $("#filters-foot");
    if (!foot) return;
    if (state.tab === "tab_egrz") {
      foot.innerHTML = "";
      return;
    }
    const n = activeFilterCount();
    const collapsed = $("#filters-card").classList.contains("is-collapsed");
    foot.innerHTML = `<button type="button" class="btn btn--link filters-toggle" data-toggle-filters>${collapsed ? "Показать фильтры" : "Скрыть фильтры"}${n ? ` (${n})` : ""}</button><span>${escapeHtml(periodText())}</span><span class="spacer"></span>${
      n ? `<span class="filters-count">Активных фильтров: ${n}</span><button type="button" class="btn btn--link" data-reset>Сбросить</button>` : ""
    }`;
  }

  function resetFilters() {
    const keep = { access: state.filters.access, line_shape: state.filters.line_shape };
    state.filters = { ...structuredClone(DEFAULT_FILTERS), ...keep };
    state.filters.year = state.meta?.default_year ?? null;
    if (state.meta?.sources?.default) state.filters.source = state.meta.sources.default;
    loadActiveTab({ refreshDims: true });
  }

  /* ───────────────────────── Tabs ───────────────────────── */

  function renderTabs() {
    const items = [...PUBLIC_TABS];
    if (HIDDEN_TABS[state.tab] && !items.find((x) => x[0] === state.tab)) items.push([state.tab, HIDDEN_TABS[state.tab]]);
    $("#tabs").innerHTML = items
      .map(
        ([id, label]) =>
          `<button type="button" role="tab" aria-selected="${state.tab === id}" class="tab ${state.tab === id ? "is-active" : ""}" data-tab="${id}">${escapeHtml(label)}</button>`
      )
      .join("");
  }

  function showPanel() {
    $$(".panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === state.tab));
  }

  function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return "";
    return `${Number(m[3])} ${["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"][Number(m[2]) - 1]} ${m[1]}`;
  }

  function renderDataBadge() {
    const el = $("#data-badge");
    const max = state.meta?.date_bounds?.max;
    if (!el || !max) return;
    const per = state.meta?.source_bounds || [];
    const lagging = per.filter((x) => x.max && (new Date(max) - new Date(x.max)) / 864e5 > 20 && new Date(x.max).getFullYear() >= new Date(max).getFullYear());
    el.textContent = `Данные по ${shortDate(max)}${lagging.map((x) => ` · ${x.label} по ${shortDate(x.max)}`).join("")}`;
    if (per.length > 1) el.title = per.map((x) => `${x.label}: ${shortDate(x.min)} — ${shortDate(x.max)}`).join("\n");
    el.hidden = false;
  }

  /* ───────────────────────── Loaders ───────────────────────── */

  async function loadMeta() {
    state.meta = await api("/api/meta");
    if (state.filters.year == null && state.meta.default_year != null) state.filters.year = state.meta.default_year;
    if ((!state.filters.source || state.filters.source === "all") && state.meta.sources?.default) {
      state.filters.source = state.meta.sources.default;
    }
    renderDataBadge();
  }

  async function loadDimensions() {
    state.dims = await api("/api/dimensions");
  }

  function deltaHtml(delta, { pp = false, invert = false } = {}) {
    if (delta === null || delta === undefined) return "";
    const v = Number(delta);
    const good = invert ? v < 0 : v > 0;
    const cls = Math.abs(v) < 0.5 ? "delta--flat" : good ? "delta--up" : "delta--down";
    const arrow = Math.abs(v) < 0.5 ? "→" : v > 0 ? "↑" : "↓";
    return `<span class="delta ${cls}">${arrow} ${nf1.format(Math.abs(v))}${pp ? " п.п." : "%"}</span>`;
  }

  function renderKpi(d) {
    const set = (key, valueHtml, prevText, deltaOpts) => {
      const card = $(`.kpi[data-kpi="${key}"]`);
      if (!card) return;
      const val = $(".kpi-value", card);
      val.classList.remove("skeleton");
      val.innerHTML = valueHtml;
      const delta = deltaHtml(d[`${key}_delta`], deltaOpts);
      $(".kpi-foot", card).innerHTML = d.has_prev && delta ? `${delta}<span>к прошлому году · ${escapeHtml(prevText)}</span>` : "";
    };
    const money = (v) => {
      const c = compact(v);
      return `${c.num}<small>${c.unit ? c.unit + " " : ""}₽</small>`;
    };
    set("total_deals", nf0.format(d.total_deals_raw ?? 0), nf0.format(d.total_deals_prev ?? 0));
    set("sum_budget", money(d.sum_budget_raw), compactStr(d.sum_budget_prev));
    set("avg_budget", d.avg_budget_raw ? money(d.avg_budget_raw) : "—", compactStr(d.avg_budget_prev));
    set("median_budget", d.median_budget_raw ? money(d.median_budget_raw) : "—", compactStr(d.median_budget_prev));
    set("avg_sqm", d.avg_sqm_raw ? money(d.avg_sqm_raw) : "—", compactStr(d.avg_sqm_prev));
    set(
      "mortgage_share",
      d.mortgage_share_raw != null ? `${nf1.format(d.mortgage_share_raw)}<small>%</small>` : "—",
      d.mortgage_share_prev != null ? `${nf1.format(d.mortgage_share_prev)}%` : "—",
      { pp: true }
    );
  }

  async function loadDealsTab() {
    const tension = state.filters.line_shape === "spline" ? 0.35 : 0;
    $$("#line-style-toolbar .seg").forEach((b) => b.classList.toggle("is-active", b.dataset.shape === state.filters.line_shape));
    const c = palette();
    const kpiCards = $$(".kpi-value");
    kpiCards.forEach((el) => el.classList.add("skeleton"));

    const jobs = [
      track((signal) => api("/api/deals/kpi", { signal }).then(renderKpi), []),
      track(
        (signal) =>
          api("/api/deals/monthly-counts", { signal }).then((d) =>
            lineChart(
              "monthly-counts",
              $("#chart-monthly-counts"),
              d.labels,
              [
                { label: "Всего", data: d.total, borderColor: c.ink, backgroundColor: (ctx) => gradient(ctx, toHex(c.ink)), fill: true, borderWidth: 2.5 },
                { label: "Ипотека", data: d.mortgage, borderColor: c.sea, backgroundColor: "transparent" },
                { label: "Без ипотеки", data: d.non_mortgage, borderColor: c.sand, backgroundColor: "transparent", borderDash: [5, 4] },
              ],
              { tension }
            )
          ),
        $("#chart-monthly-counts")
      ),
      track(
        (signal) =>
          api("/api/deals/monthly-avg", { signal }).then((d) =>
            lineChart(
              "monthly-avg",
              $("#chart-monthly-avg"),
              d.labels,
              [{ label: "Средний чек", data: d.avg, borderColor: c.sea, backgroundColor: (ctx) => gradient(ctx, toHex(c.sea)), fill: true }],
              { tension, money: true }
            )
          ),
        $("#chart-monthly-avg")
      ),
      track(
        (signal) =>
          api("/api/deals/monthly-sqm", { signal }).then((d) =>
            lineChart(
              "monthly-sqm",
              $("#chart-monthly-sqm"),
              d.labels,
              [{ label: "Медиана за м²", data: d.median, borderColor: c.sand, backgroundColor: (ctx) => gradient(ctx, toHex(c.sand)), fill: true }],
              { tension, money: true }
            )
          ),
        $("#chart-monthly-sqm")
      ),
      track(
        (signal) =>
          api("/api/deals/budget-buckets", { signal }).then((d) => {
            const total = (d.values || []).reduce((s, v) => s + v, 0);
            if (!total) return emptyState($("#chart-budget-buckets"), "Нет сделок с известным бюджетом");
            barChart("budget-buckets", $("#chart-budget-buckets"), d.labels, d.values, { horizontal: false, tooltipSuffix: " сделок" });
            const ch = state.charts["budget-buckets"];
            if (ch) {
              ch.options.plugins.tooltip.callbacks.label = (ctx) => ` ${nf0.format(ctx.parsed.y)} сделок · ${nf1.format(d.shares[ctx.dataIndex])}%`;
              ch.update("none");
            }
          }),
        $("#chart-budget-buckets")
      ),
      track(
        (signal) =>
          api("/api/deals/top-complexes", { signal }).then((d) => {
            $("#top-total-sub").textContent = d.year ? `По числу сделок за ${d.year} год` : "По числу сделок за период";
            if (d.message) {
              emptyState($("#chart-top-total"), d.message);
              emptyState($("#chart-top-mortgage"), d.message);
              return;
            }
            renderBarList($("#chart-top-total"), d.total || []);
            renderBarList($("#chart-top-mortgage"), d.mortgage || [], { variant: "bar-fill--sand" });
          }),
        [$("#chart-top-total"), $("#chart-top-mortgage")]
      ),
    ];
    await Promise.allSettled(jobs);
  }

  function toHex(color) {
    // Chart gradient helper needs a #rrggbb colour.
    if (/^#[0-9a-f]{6}$/i.test(color)) return color;
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(color);
    if (!m) return "#0e7490";
    return "#" + [m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, "0")).join("");
  }

  async function loadComplexesTab() {
    const c = palette();
    await Promise.allSettled([
      track(
        (signal) => api("/api/complexes/city-counts", { signal }).then((d) => barChart("city", $("#chart-city-counts"), d.labels, d.values, { tooltipSuffix: " сделок" })),
        $("#chart-city-counts")
      ),
      track(
        (signal) =>
          api("/api/complexes/monthly", { signal }).then((d) => {
            $("#complex-monthly-title").textContent = d.name ? `Продажи по месяцам: ${d.name}` : "Помесячные продажи комплекса";
            if (!d.name) return emptyState($("#chart-complex-monthly"), "Комплекс не выбран", "Выберите его в фильтре «Комплекс»");
            barChart("complex-monthly", $("#chart-complex-monthly"), d.labels, d.values, { horizontal: false, color: c.sea, monthAxis: true, tooltipSuffix: " сделок" });
          }),
        $("#chart-complex-monthly")
      ),
    ]);
  }

  function toggleSelected(name) {
    const set = new Set(state.filters.selected);
    if (set.has(name)) set.delete(name);
    else set.add(name);
    state.filters.selected = [...set];
    writeUrl();
    loadCompareTab();
  }

  async function loadCompareTab() {
    await track(async (signal) => {
      const d = await api("/api/compare", { signal });
      scatterChart("compare", $("#chart-compare"), d.points || [], toggleSelected);
      renderTable(
        $("#table-compare"),
        d.rows || [],
        [
          { key: "object", label: "Комплекс" },
          { key: "city", label: "Город" },
          { key: "developer", label: "Застройщик" },
          { key: "deals", label: "Сделок", num: true },
          { key: "avg_budget", label: "Средний чек, ₽", money: true },
          { key: "avg_price_sqm", label: "Цена м², ₽", money: true },
        ],
        { selected: state.filters.selected, clickable: true }
      );
      $("#table-compare").onclick = (e) => {
        const tr = e.target.closest("tbody tr[data-key]");
        if (tr) toggleSelected(tr.dataset.key);
      };
    }, [$("#chart-compare"), $("#table-compare")]);
  }

  async function loadEulerTab() {
    const el = $("#euler-summary");
    await track(async (signal) => {
      const d = await api("/api/euler", { signal });
      clearSkeleton(el);
      el.classList.remove("skeleton-block");
      const band = `<p class="muted" style="margin:0">Коридор бюджета: <b>${compactStr(d.band?.lo)} – ${compactStr(d.band?.hi)} ₽</b></p>`;
      if (d.message) {
        el.innerHTML = `${band}<div class="empty"><strong>${escapeHtml(d.message)}</strong>Фильтр «Проекты» выше</div>`;
        return;
      }
      const boxes = (d.projects || [])
        .map((p) => `<div class="euler-box"><div class="eb-name">${escapeHtml(p)}</div><strong>${fmt(d.sizes?.[p] || 0)}</strong><span class="muted">ценовых точек в коридоре</span></div>`)
        .join("");
      const pairs = Object.entries(d.pairs || {})
        .map(([k, v]) => {
          const [a, b] = k.split("||");
          const base = Math.min(d.sizes?.[a] || 0, d.sizes?.[b] || 0) || 1;
          return `<div class="euler-box euler-box--pair"><div class="eb-name">${escapeHtml(a)} ∩ ${escapeHtml(b)}</div><strong>${fmt(v)}</strong><span class="muted">${nf0.format((v / base) * 100)}% от меньшего</span></div>`;
        })
        .join("");
      const triple =
        (d.projects || []).length === 3
          ? `<div class="euler-box euler-box--triple"><div class="eb-name">Все три</div><strong>${fmt(d.triple || 0)}</strong><span class="muted">общих точек</span></div>`
          : "";
      el.innerHTML = `${band}<div class="euler-boxes">${boxes}${pairs}${triple}</div>`;
    }, el);
  }

  async function loadHeatmapCellDetails(objectName, monthKey) {
    const titleEl = $("#heatmap-click-title");
    const subEl = $("#heatmap-click-sub");
    const tableEl = $("#heatmap-click-table");
    titleEl.textContent = objectName;
    subEl.textContent = "Загрузка…";
    tableEl.innerHTML = '<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div>';
    try {
      const d = await api("/api/heatmap/details", { extra: { object: objectName, month: monthKey } });
      titleEl.textContent = objectName;
      subEl.textContent = `${monthLabelFull(d.month || monthKey)} · ${nf0.format(d.total || 0)} сделок${(d.total || 0) > 300 ? " (показаны первые 300)" : ""}`;
      if (!(d.rows || []).length) return emptyState(tableEl, d.message || "Сделок не найдено");
      renderTable(
        tableEl,
        d.rows,
        [
          { key: "date", label: "Дата" },
          { key: "budget", label: "Стоимость, ₽", money: true },
          { key: "status", label: "Оплата", render: (v) => escapeHtml(v === "Нет" ? "Без ипотеки" : v ?? "—") },
          { key: "type_lot", label: "Тип" },
          { key: "city", label: "Город" },
          { key: "district", label: "Район" },
          { key: "developer", label: "Застройщик" },
          { key: "source", label: "Источник" },
        ],
        { rowKey: "date" }
      );
      $("#heatmap-details").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      if (err.message === "unauthorized") return;
      subEl.textContent = "";
      tableEl.innerHTML = `<div class="error-box">Не удалось загрузить сделки: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function loadHeatmapTab() {
    $("#heatmap-click-title").textContent = "Сделки по ячейке";
    $("#heatmap-click-sub").textContent = "Кликните по ячейке теплокарты";
    $("#heatmap-click-table").innerHTML = "";
    const root = $("#heatmap");
    setLoading(root);
    await track(async (signal) => {
      const d = await api("/api/heatmap", { signal });
      renderHeatmap(root, d);
      root.onclick = (e) => {
        const cell = e.target.closest("td[data-object][data-month]");
        if (!cell) return;
        $$("#heatmap td.is-active").forEach((td) => td.classList.remove("is-active"));
        cell.classList.add("is-active");
        loadHeatmapCellDetails(cell.dataset.object, cell.dataset.month);
      };
    }, root);
  }

  async function loadEgrzTab() {
    const el = $("#table-egrz");
    await track(async (signal) => {
      const d = await api("/api/egrz", { signal });
      state.egrzMeta = { regions: d.regions || [], work_types: d.work_types || [] };
      renderFilters();
      if (d.message) return emptyState(el, d.message);
      $("#egrz-title").textContent = `ЕГРЗ · ${fmt(d.total)} записей${d.total > 500 ? " (показаны 500)" : ""}`;
      renderTable(
        el,
        d.rows || [],
        [
          { key: "date", label: "Дата" },
          { key: "rns", label: "Номер заключения" },
          { key: "city", label: "Город" },
          { key: "object", label: "Объект", wrap: true },
          { key: "developer", label: "Застройщик", wrap: true },
          { key: "work_type", label: "Вид работ" },
          { key: "keys", label: "Ключи" },
        ],
        { rowKey: "rns" }
      );
    }, el);
  }

  async function loadLotGrowthTab() {
    const c = palette();
    await track(async (signal) => {
      const d = await api("/api/lot-growth", { signal });
      const s = Array.isArray(d.series) ? {} : d.series || {};
      lineChart(
        "lot-growth",
        $("#chart-lot-growth"),
        s.labels || [],
        [
          { label: "Средний чек", data: s.avg_budget || [], borderColor: c.sea, backgroundColor: "transparent", yAxisID: "y" },
          { label: "Сделок", data: s.deals || [], borderColor: c.sand, backgroundColor: "transparent", yAxisID: "y1", borderDash: [5, 4] },
        ],
        { money: true, y1: true }
      );
      renderTable(
        $("#table-lot-growth"),
        (d.rows || []).map((r) => ({ ...r, month: monthLabelFull(r.month) })),
        [
          { key: "month", label: "Месяц" },
          { key: "deals", label: "Сделок", num: true },
          { key: "avg_budget", label: "Средний чек, ₽", money: true },
          { key: "avg_sqm", label: "Цена м², ₽", money: true },
        ],
        { rowKey: "month" }
      );
    }, [$("#chart-lot-growth"), $("#table-lot-growth")]);
  }

  async function loadProjectGrowthTab() {
    await track(async (signal) => {
      const d = await api("/api/project-growth", { signal });
      renderBarList($("#chart-pg-budget"), d.budget_pct || [], { suffix: "%" });
      renderBarList($("#chart-pg-sqm"), d.sqm_pct || [], { suffix: "%", variant: "bar-fill--sand" });
      renderTable($("#table-pg"), d.rows || [], [
        { key: "object", label: "Проект" },
        { key: "city", label: "Город" },
        { key: "deals", label: "Сделок", num: true },
        { key: "budget_growth_pct", label: "Рост бюджета, %", num: true, render: (v) => (v == null ? "—" : nf1.format(v)) },
        { key: "sqm_growth_pct", label: "Рост м², %", num: true, render: (v) => (v == null ? "—" : nf1.format(v)) },
      ]);
    }, [$("#chart-pg-budget"), $("#chart-pg-sqm"), $("#table-pg")]);
  }

  /* ───────────────────────── Insight tabs ───────────────────────── */

  function setKpi(panel, key, valueHtml, footHtml = "") {
    const card = $(`#${panel} .kpi[data-kpi="${key}"]`);
    if (!card) return;
    const v = $(".kpi-value", card);
    v.classList.remove("skeleton");
    v.innerHTML = valueHtml;
    $(".kpi-foot", card).innerHTML = footHtml;
  }

  function monthsRange(list) {
    if (!list?.length) return "";
    const a = monthLabelFull(list[0]);
    const b = monthLabelFull(list[list.length - 1]);
    return a === b ? a : `${a} — ${b}`;
  }

  const pctCell = (v) => {
    if (v === null || v === undefined) return '<span class="muted">—</span>';
    const cls = Math.abs(v) < 0.5 ? "delta--flat" : v > 0 ? "delta--up" : "delta--down";
    const sign = v > 0 ? "+" : v < 0 ? "−" : "";
    return `<span class="delta ${cls}">${sign}${nf1.format(Math.abs(v))}%</span>`;
  };

  async function loadPaceTab() {
    const P = "panel-tab_pace";
    $$("#pace-window .seg").forEach((b) => b.classList.toggle("is-active", Number(b.dataset.window) === Number(state.filters.pace_window)));
    $$(`#${P} .kpi-value`).forEach((el) => el.classList.add("skeleton"));
    await track(async (signal) => {
      const d = await api("/api/pace", { signal });
      if (d.message) {
        ["chart-pace", "table-pace"].forEach((id) => emptyState($("#" + id), d.message));
        return;
      }
      const m = d.market;
      setKpi(P, "pace", nf1.format(m.pace), m.pace_prev != null ? `${deltaHtml(m.pace_delta)}<span>было ${nf1.format(m.pace_prev)}</span>` : "");
      setKpi(P, "active", nf0.format(m.active), `<span>с продажами в окне</span>`);
      setKpi(P, "growing", nf0.format(m.growing), `<span>темп вырос на 20%+</span>`);
      setKpi(P, "slowing", nf0.format(m.slowing), `<span>темп упал на 20%+</span>`);
      const many = (d.windows || []).length > 1;
      const winText = (d.windows || []).map((w) => `${many ? w.region + ": " : ""}${monthsRange(w.cur_months)}`).join(" · ");
      $("#pace-sub").textContent = `Сделок в месяц, ${winText}`;
      $("#pace-table-sub").textContent =
        (d.windows || []).map((w) => `${many ? w.region + ": " : ""}${monthsRange(w.cur_months)} против ${monthsRange(w.prev_months)}`).join("; ") +
        ". Неполный последний месяц выгрузки не учитывается";
      const c = palette();
      barChart("pace", $("#chart-pace"), d.top.map((x) => x.name), d.top.map((x) => x.value), { color: c.sea, tooltipSuffix: " сделок/мес" });
      const cols = [
        { key: "object", label: "Комплекс" },
        { key: "city", label: "Город" },
        ...(many ? [{ key: "region", label: "Регион" }] : []),
        { key: "class", label: "Класс" },
        { key: "pace", label: "Темп, сд/мес", num: true, render: (v) => nf1.format(v) },
        { key: "pace_prev", label: "Было", num: true, render: (v) => (v == null ? "—" : nf1.format(v)) },
        { key: "pace_delta", label: "Изменение", num: true, render: pctCell },
        {
          key: "start",
          label: "Старт продаж",
          render: (v, r) => (v ? `${escapeHtml(v.slice(0, 7).split("-").reverse().join("."))}${r.start_is_real ? "" : ' <span class="pill" title="Старт неизвестен — взята дата первой сделки">≈</span>'}` : "—"),
        },
        { key: "pace_since_start", label: "Темп со старта", num: true, render: (v) => (v == null ? "—" : nf1.format(v)) },
        { key: "mortgage_share", label: "Ипотека, %", num: true },
        { key: "sqm", label: "Медиана м², ₽", money: true },
      ];
      if (d.has_exposure) cols.push({ key: "exposure", label: "Дней в экспозиции", num: true });
      renderTable($("#table-pace"), d.rows, cols);
    }, [$("#chart-pace"), $("#table-pace")]);
  }

  const SERIES_COLORS = ["#0e7490", "#c98a2b", "#7c3aed", "#15803d", "#db2777", "#2563eb"];

  async function loadPriceTab() {
    $$("#price-gran .seg").forEach((b) => b.classList.toggle("is-active", b.dataset.gran === state.filters.gran));
    await track(async (signal) => {
      const d = await api("/api/price-dynamics", { signal });
      const c = palette();
      const datasets = (d.series || []).map((s, i) => ({
        label: s.name,
        data: s.values,
        borderColor: SERIES_COLORS[i % SERIES_COLORS.length],
        backgroundColor: "transparent",
        spanGaps: true,
        pointRadius: 2,
      }));
      if ((d.labels || []).length) {
        datasets.push({ label: "Весь рынок", data: d.market, borderColor: c.faint, borderDash: [5, 4], backgroundColor: "transparent", borderWidth: 1.5 });
      }
      lineChart("price", $("#chart-price"), d.labels || [], datasets, { money: true });
      const sub = $("#price-table-sub");
      const k = d.window || 3;
      sub.textContent = `Медиана цены м² за первые ${k} месяца продаж комплекса в периоде против последних ${k}. Для длинной истории выберите «Все годы»`;
      if (!(d.rows || []).length) return emptyState($("#table-price"), d.message || "Нет данных");
      renderTable(
        $("#table-price"),
        d.rows,
        [
          { key: "object", label: "Комплекс" },
          { key: "city", label: "Город" },
          { key: "class", label: "Класс" },
          { key: "deals", label: "Сделок", num: true },
          { key: "from", label: "Продажи в периоде", render: (v, r) => `${escapeHtml(monthLabel(v))} — ${escapeHtml(monthLabel(r.to))}` },
          { key: "p0", label: "Цена м² в начале, ₽", money: true },
          { key: "p1", label: "Цена м² сейчас, ₽", money: true },
          { key: "growth", label: "Рост", num: true, render: pctCell },
          { key: "growth_month", label: "В среднем за месяц", num: true, render: (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${nf2.format(v)}%`) },
        ],
        { clickable: true, selected: state.filters.selected }
      );
      $("#table-price").onclick = (e) => {
        const tr = e.target.closest("tbody tr[data-key]");
        if (!tr) return;
        const set = new Set(state.filters.selected);
        if (set.has(tr.dataset.key)) set.delete(tr.dataset.key);
        else if (set.size >= 6) return toast("На графике можно показать до 6 комплексов");
        else set.add(tr.dataset.key);
        state.filters.selected = [...set];
        renderFilters();
        writeUrl();
        loadPriceTab();
      };
    }, [$("#chart-price"), $("#table-price")]);
  }

  async function loadMortgageTab() {
    const P = "panel-tab_mortgage";
    $$(`#${P} .kpi-value`).forEach((el) => el.classList.add("skeleton"));
    await track(async (signal) => {
      const d = await api("/api/mortgage", { signal });
      if (d.message) {
        ["chart-banks", "chart-terms", "chart-mortgage-monthly", "table-mortgage"].forEach((id) => emptyState($("#" + id), d.message));
        return;
      }
      const c = palette();
      setKpi(P, "m_share", d.mortgage_share != null ? `${nf1.format(d.mortgage_share)}<small>%</small>` : "—", `<span>${nf0.format(d.mortgage)} из ${nf0.format(d.total)} сделок</span>`);
      setKpi(P, "m_term", d.median_term != null ? `${nf1.format(d.median_term)}<small>лет</small>` : "—", d.term_coverage != null ? `<span>срок известен у ${d.term_coverage}% ипотек</span>` : "");
      setKpi(P, "m_bank", d.top_bank ? `<span class="kpi-value--text">${escapeHtml(d.top_bank.name)}</span>` : "—", d.top_bank ? `<span>${nf1.format(d.top_bank.share)}% ипотечных сделок</span>` : "");
      setKpi(P, "m_cover", d.bank_coverage != null ? `${d.bank_coverage}<small>%</small>` : "—", `<span>ипотек с указанным банком</span>`);

      if ((d.banks || []).length) {
        barChart("banks", $("#chart-banks"), d.banks.map((b) => b.name), d.banks.map((b) => b.share), { color: c.sea, tooltipSuffix: "%" });
      } else emptyState($("#chart-banks"), "Банк в данных не указан");
      if ((d.terms || []).length) {
        barChart("terms", $("#chart-terms"), d.terms.map((t) => t.label), d.terms.map((t) => t.share), { horizontal: false, color: c.sand, tooltipSuffix: "%" });
      } else emptyState($("#chart-terms"), "Срок ипотеки в данных не указан");

      const s = d.series || {};
      const ds = [{ label: "Доля ипотеки, %", data: s.share || [], borderColor: c.sea, backgroundColor: (ctx) => gradient(ctx, toHex(c.sea)), fill: true, yAxisID: "y" }];
      if ((s.term || []).some((x) => x != null)) ds.push({ label: "Срок, лет", data: s.term, borderColor: c.sand, backgroundColor: "transparent", borderDash: [5, 4], yAxisID: "y1", spanGaps: true });
      lineChart("mortgage-monthly", $("#chart-mortgage-monthly"), s.labels || [], ds, { y1: ds.length > 1 });

      renderTable($("#table-mortgage"), d.rows || [], [
        { key: "object", label: "Комплекс" },
        { key: "city", label: "Город" },
        { key: "deals", label: "Сделок", num: true },
        { key: "mortgage_share", label: "Ипотека, %", num: true },
        { key: "top_bank", label: "Главный банк" },
        { key: "top_bank_share", label: "Его доля, %", num: true },
        { key: "term", label: "Срок, лет", num: true, render: (v) => (v == null ? "—" : nf1.format(v)) },
      ]);
    }, [$("#chart-banks"), $("#chart-terms"), $("#chart-mortgage-monthly"), $("#table-mortgage")]);
  }

  async function loadActiveTab({ refreshDims = true } = {}) {
    abortAll();
    closeMs({ apply: false });
    showPanel();
    renderTabs();
    if (refreshDims && state.tab !== "tab_egrz") {
      try {
        await loadDimensions();
      } catch (err) {
        if (err.message !== "unauthorized") toast("Не удалось обновить списки фильтров");
      }
    }
    renderFilters();
    writeUrl();

    if (ADMIN_TABS.has(state.tab) && !state.filters.access) {
      const ids = state.tab === "tab_lot_growth" ? ["#chart-lot-growth", "#table-lot-growth"] : ["#chart-pg-budget", "#chart-pg-sqm", "#table-pg"];
      ids.forEach((id) => emptyState($(id), "Раздел закрыт", "Нужна ссылка с ключом доступа"));
      return;
    }

    const loaders = {
      tab_deals: loadDealsTab,
      tab_pace: loadPaceTab,
      tab_price: loadPriceTab,
      tab_mortgage: loadMortgageTab,
      tab_complexes: loadComplexesTab,
      tab_compare: loadCompareTab,
      tab_euler: loadEulerTab,
      tab_heatmap: loadHeatmapTab,
      tab_egrz: loadEgrzTab,
      tab_lot_growth: loadLotGrowthTab,
      tab_project_growth: loadProjectGrowthTab,
    };
    await ensureChartJs();
    applyChartDefaults();
    await loaders[state.tab]?.();
  }

  /* ───────────────────────── Events ───────────────────────── */

  const RELOAD_DIMS = new Set(["source", "agglomeration", "year", "date_from", "date_to", "developer"]);

  function onFilterValueChanged(key) {
    if (key === "developer") state.filters.project = [];
    if (key === "date_from" || key === "date_to") {
      const { date_from: a, date_to: b } = state.filters;
      if (a && b && a > b) {
        toast("Дата начала позже даты конца — поменял местами");
        state.filters.date_from = b;
        state.filters.date_to = a;
      }
    }
    loadActiveTab({ refreshDims: RELOAD_DIMS.has(key) });
  }

  function bindEvents() {
    $("#tabs").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tab]");
      if (!btn || btn.dataset.tab === state.tab) return;
      state.tab = btn.dataset.tab;
      state.filters.selected = [];
      loadActiveTab();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });

    const onChange = (e) => {
      const quality = e.target.closest("[data-quality]");
      if (quality) {
        state.filters.data_quality = $$("[data-quality]:checked").map((x) => x.dataset.quality);
        loadActiveTab({ refreshDims: false });
        return;
      }
      const el = e.target.closest("[data-filter]");
      if (!el) return;
      const key = el.dataset.filter;
      state.filters[key] = el.type === "number" ? (el.value === "" ? "" : Number(el.value)) : el.value;
      if (key === "year") state.filters.year = el.value === "" ? null : Number(el.value);
      onFilterValueChanged(key);
    };

    const onClick = (e) => {
      if (e.target.closest("[data-reset]")) return resetFilters();
      if (e.target.closest("[data-toggle-filters]")) {
        $("#filters-card").classList.toggle("is-collapsed");
        return renderFiltersFoot();
      }
      const trigger = e.target.closest(".ms-trigger");
      if (trigger) openMultiSelect(trigger.closest("[data-ms]"));
    };

    for (const root of [$("#filters-card"), $("#heatmap-filters")]) {
      root?.addEventListener("change", onChange);
      root?.addEventListener("click", onClick);
    }

    // Search in EGRZ reacts while typing (debounced), not only on blur.
    let searchTimer;
    $("#filters").addEventListener("input", (e) => {
      if (e.target.dataset.filter !== "search") return;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.filters.search = e.target.value;
        loadEgrzTab();
        writeUrl();
      }, 350);
    });

    document.addEventListener("mousedown", (e) => {
      if (openMs && !openMs.root.contains(e.target)) closeMs();
    });

    $("#line-style-toolbar")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-shape]");
      if (!btn) return;
      state.filters.line_shape = btn.dataset.shape;
      const tension = btn.dataset.shape === "spline" ? 0.35 : 0;
      $$("#line-style-toolbar .seg").forEach((b) => b.classList.toggle("is-active", b === btn));
      for (const key of ["monthly-counts", "monthly-avg", "monthly-sqm"]) {
        const ch = state.charts[key];
        if (ch) {
          ch.options.elements.line.tension = tension;
          ch.update();
        }
      }
      writeUrl();
    });

    $("#pace-window")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-window]");
      if (!btn) return;
      state.filters.pace_window = Number(btn.dataset.window);
      writeUrl();
      renderFiltersFoot();
      loadPaceTab();
    });

    $("#price-gran")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-gran]");
      if (!btn) return;
      state.filters.gran = btn.dataset.gran;
      writeUrl();
      loadPriceTab();
    });

    $("#hm-palette")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-palette]");
      if (!btn) return;
      setHeatPalette(btn.dataset.palette);
      syncPaletteUi();
      if (state.lastHeatmap) renderHeatmap($("#heatmap"), state.lastHeatmap);
    });

    $("#cmp-clear")?.addEventListener("click", () => {
      state.filters.selected = [];
      writeUrl();
      loadCompareTab();
    });
  }

  async function boot() {
    readUrl();
    if (window.matchMedia("(max-width: 640px)").matches) $("#filters-card").classList.add("is-collapsed");
    renderTabs();
    showPanel();
    bindEvents();
    try {
      await loadMeta();
      await loadActiveTab({ refreshDims: true });
    } catch (err) {
      if (String(err.message) !== "unauthorized") {
        console.error(err);
        $("#filters").innerHTML = `<div class="error-box" style="grid-column:1/-1">Не удалось загрузить данные: ${escapeHtml(err.message)}</div>`;
      }
    }
  }

  boot();
})();
