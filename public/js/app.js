(() => {
  const PUBLIC_TABS = [
    ["tab_deals", "Дашборд"],
    ["tab_complexes", "Комплексы"],
    ["tab_compare", "Сравнение"],
    ["tab_euler", "Эйлер"],
    ["tab_heatmap", "Теплокарта"],
  ];
  const HIDDEN_TABS = {
    tab_egrz: "ЕГРЗ",
    tab_lot_growth: "Рост лота",
    tab_project_growth: "Рост проектов",
  };
  const ADMIN_TABS = new Set(["tab_lot_growth", "tab_project_growth"]);

  const state = {
    tab: "tab_deals",
    meta: null,
    dims: null,
    filters: {
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
      top_n: 30,
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
    },
    charts: {},
    controllers: [],
    loadedTabs: new Set(),
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function qs() {
    return new URLSearchParams(location.search);
  }

  function readUrl() {
    const p = qs();
    const tab = p.get("tab") || "tab_deals";
    state.tab = tab;
    state.filters.access = p.get("access") || "";
    const keys = [
      "source",
      "agglomeration",
      "year",
      "date_from",
      "date_to",
      "mortgage_mode",
      "budget_min",
      "budget_max",
      "object",
      "line_shape",
      "search",
      "type_lot_single",
      "top_n",
      "target_budget",
      "delta_budget",
    ];
    for (const k of keys) {
      if (p.has(k)) state.filters[k] = p.get(k);
    }
    for (const k of ["months", "city", "developer", "project", "type_lot", "district", "selected", "projects", "region", "work_type", "data_quality"]) {
      if (p.has(k)) state.filters[k] = p.get(k).split(",").filter(Boolean);
    }
    if (state.filters.year) state.filters.year = Number(state.filters.year);
    if (state.filters.top_n) state.filters.top_n = Number(state.filters.top_n);
    if (state.filters.target_budget) state.filters.target_budget = Number(state.filters.target_budget);
    if (state.filters.delta_budget) state.filters.delta_budget = Number(state.filters.delta_budget);
  }

  function writeUrl() {
    const p = new URLSearchParams();
    if (state.tab !== "tab_deals") p.set("tab", state.tab);
    if (state.filters.access) p.set("access", state.filters.access);
    const f = state.filters;
    const putScalar = (k, skipVals = []) => {
      const v = f[k];
      if (v === null || v === undefined || v === "" || skipVals.includes(v)) return;
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
    if (state.tab === "tab_heatmap") putScalar("top_n", [30]);
    for (const k of ["months", "city", "developer", "project", "type_lot", "district", "selected", "projects", "region", "work_type"]) {
      if (f[k] && f[k].length) p.set(k, f[k].join(","));
    }
    if (
      state.tab === "tab_heatmap" &&
      f.data_quality &&
      f.data_quality.length &&
      !(f.data_quality.length === 2 && f.data_quality.includes("exclude_wholesale") && f.data_quality.includes("known_budget_only"))
    ) {
      p.set("data_quality", f.data_quality.join(","));
    }
    const next = p.toString();
    const url = next ? `?${next}` : location.pathname;
    history.replaceState(null, "", url);
  }

  function filterQuery(extra = {}) {
    const f = { ...state.filters, ...extra };
    const p = new URLSearchParams();
    const put = (k, v) => {
      if (v === null || v === undefined || v === "") return;
      if (Array.isArray(v)) {
        if (v.length) p.set(k, v.join(","));
        return;
      }
      p.set(k, String(v));
    };
    put("source", f.source);
    put("agglomeration", f.agglomeration);
    put("year", f.year);
    put("date_from", f.date_from);
    put("date_to", f.date_to);
    put("months", f.months);
    put("city", f.city);
    put("developer", f.developer);
    put("project", f.project);
    put("type_lot", f.type_lot);
    put("mortgage_mode", f.mortgage_mode);
    put("budget_min", f.budget_min);
    put("budget_max", f.budget_max);
    put("object", f.object);
    put("district", f.district);
    put("selected", f.selected);
    put("top_n", f.top_n);
    put("line_shape", f.line_shape);
    put("data_quality", f.data_quality);
    put("target_budget", f.target_budget);
    put("delta_budget", f.delta_budget);
    put("type_lot_single", f.type_lot_single);
    put("projects", f.projects);
    put("search", f.search);
    put("region", f.region);
    put("work_type", f.work_type);
    put("access", f.access);
    return p.toString();
  }

  function abortAll() {
    for (const c of state.controllers) c.abort();
    state.controllers = [];
  }

  async function api(path, { signal } = {}) {
    const q = filterQuery();
    const url = q ? `${path}?${q}` : path;
    const res = await fetch(url, { credentials: "same-origin", signal });
    if (res.status === 401) {
      location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || res.statusText);
    }
    return res.json();
  }

  function track(promise) {
    const c = new AbortController();
    state.controllers.push(c);
    return promise(c.signal).finally(() => {
      state.controllers = state.controllers.filter((x) => x !== c);
    });
  }

  function setSkeleton(el, on) {
    if (!el) return;
    el.classList.toggle("skeleton", on);
    if (on) el.classList.add("skeleton-chart");
    else el.classList.remove("skeleton-chart", "skeleton-kpi");
  }

  function destroyChart(key) {
    if (state.charts[key]) {
      state.charts[key].destroy();
      delete state.charts[key];
    }
  }

  function ensureCanvas(container) {
    container.classList.remove("skeleton", "skeleton-chart");
    container.innerHTML = "";
    const canvas = document.createElement("canvas");
    container.appendChild(canvas);
    return canvas;
  }

  function lineChart(key, container, labels, datasets, { tension = 0 } = {}) {
    destroyChart(key);
    if (!window.Chart) return;
    const canvas = ensureCanvas(container);
    state.charts[key] = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "top", align: "start" } },
        elements: { line: { tension }, point: { radius: 2 } },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, grid: { color: "#eef1f4" } },
        },
      },
    });
  }

  function barChart(key, container, labels, values, { horizontal = true } = {}) {
    destroyChart(key);
    if (!window.Chart) return;
    const canvas = ensureCanvas(container);
    state.charts[key] = new Chart(canvas, {
      type: "bar",
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: "#3d6ef5", borderRadius: 4 }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, grid: { color: "#eef1f4" } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  function scatterChart(key, container, points, onClick) {
    destroyChart(key);
    if (!window.Chart) return;
    const canvas = ensureCanvas(container);
    const selected = points.filter((p) => p.selected);
    const rest = points.filter((p) => !p.selected);
    state.charts[key] = new Chart(canvas, {
      type: "scatter",
      data: {
        datasets: [
          {
            label: "Комплексы",
            data: rest.map((p) => ({ x: p.x, y: p.y, name: p.name })),
            backgroundColor: "rgba(61,110,245,0.45)",
          },
          {
            label: "Выбранные",
            data: selected.map((p) => ({ x: p.x, y: p.y, name: p.name })),
            backgroundColor: "#111",
            pointRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: {
              label(ctx) {
                const n = ctx.raw.name || "";
                return `${n}: м² ${ctx.raw.x}, бюджет ${ctx.raw.y}`;
              },
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Цена м²" }, grid: { color: "#eef1f4" } },
          y: { title: { display: true, text: "Средний бюджет" }, grid: { color: "#eef1f4" } },
        },
        onClick(_e, elements) {
          if (!elements.length || !onClick) return;
          const el = elements[0];
          const ds = state.charts[key].data.datasets[el.datasetIndex].data[el.index];
          if (ds?.name) onClick(ds.name);
        },
      },
    });
  }

  function renderBarList(container, items) {
    container.classList.remove("skeleton", "skeleton-chart");
    if (!items.length) {
      container.innerHTML = '<div class="empty">Нет данных</div>';
      return;
    }
    const max = Math.max(...items.map((i) => i.deals || i.value || 0), 1);
    container.innerHTML = `<div class="bar-list">${items
      .map((i) => {
        const v = i.deals ?? i.value ?? 0;
        const pct = Math.round((v / max) * 100);
        return `<div class="bar-row"><div class="bar-name" title="${escapeHtml(i.name)}">${escapeHtml(i.name)}</div><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><div>${fmt(v)}</div></div>`;
      })
      .join("")}</div>`;
  }

  function renderTable(container, rows, columns, { rowKey = "object", selected = [] } = {}) {
    container.classList.remove("skeleton", "skeleton-chart");
    if (!rows.length) {
      container.innerHTML = '<div class="empty">Нет данных</div>';
      return;
    }
    const sel = new Set(selected);
    const head = columns.map((c) => `<th>${escapeHtml(c.label)}</th>`).join("");
    const body = rows
      .map((r) => {
        const key = r[rowKey];
        const cls = sel.has(key) ? "is-selected" : "";
        const cells = columns.map((c) => `<td>${escapeHtml(fmt(r[c.key]))}</td>`).join("");
        return `<tr class="${cls}" data-key="${escapeHtml(String(key ?? ""))}">${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function heatmapColor(t) {
    // Same scale as old Plotly heatmap: red → yellow → green
    const stops = [
      [0, [215, 48, 39]], // #d73027
      [0.5, [254, 224, 139]], // #fee08b
      [1, [26, 152, 80]], // #1a9850
    ];
    const x = Math.max(0, Math.min(1, t));
    let i = 0;
    while (i < stops.length - 2 && x > stops[i + 1][0]) i += 1;
    const [aT, aC] = stops[i];
    const [bT, bC] = stops[i + 1];
    const u = bT === aT ? 0 : (x - aT) / (bT - aT);
    const r = Math.round(aC[0] + (bC[0] - aC[0]) * u);
    const g = Math.round(aC[1] + (bC[1] - aC[1]) * u);
    const b = Math.round(aC[2] + (bC[2] - aC[2]) * u);
    return `rgb(${r},${g},${b})`;
  }

  function renderHeatmap(container, data) {
    container.classList.remove("skeleton", "skeleton-chart");
    const { display = [], months = [], z = [] } = data;
    if (!months.length || !display.length) {
      container.innerHTML = '<div class="empty">Нет данных</div>';
      return;
    }
    const nonzero = [];
    for (const row of z) for (const v of row) if (v > 0) nonzero.push(v);
    nonzero.sort((a, b) => a - b);
    const q = (p) => {
      if (!nonzero.length) return 1;
      const idx = Math.min(nonzero.length - 1, Math.max(0, Math.floor((nonzero.length - 1) * p)));
      return nonzero[idx];
    };
    let zmin = q(0.05);
    let zmax = q(0.95);
    if (zmax <= zmin) {
      zmin = nonzero[0] || 0;
      zmax = nonzero[nonzero.length - 1] || 1;
    }
    const span = zmax - zmin || 1;
    const head = `<tr><th class="row-label">Объект</th>${months.map((m) => `<th>${escapeHtml(m)}</th>`).join("")}</tr>`;
    const body = display
      .map((name, i) => {
        const cells = (z[i] || [])
          .map((v) => {
            const vv = Number(v) || 0;
            if (vv <= 0) return `<td class="hm-zero"></td>`;
            const t = Math.max(0, Math.min(1, (vv - zmin) / span));
            return `<td style="background:${heatmapColor(t)};color:#111">${vv}</td>`;
          })
          .join("");
        return `<tr><th class="row-label" title="${escapeHtml(name)}">${escapeHtml(name)}</th>${cells}</tr>`;
      })
      .join("");
    container.innerHTML = `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  function fmt(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") return v.toLocaleString("ru-RU");
    return String(v);
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function optionHtml(options, selected, { multi = false, emptyLabel = null } = {}) {
    const sel = multi ? new Set(selected || []) : selected;
    let html = "";
    if (emptyLabel != null && !multi) {
      html += `<option value="">${escapeHtml(emptyLabel)}</option>`;
    }
    for (const o of options || []) {
      const isSel = multi ? sel.has(o.value) : String(sel) === String(o.value);
      html += `<option value="${escapeHtml(o.value)}" ${isSel ? "selected" : ""}>${escapeHtml(o.label)}</option>`;
    }
    return html;
  }

  function renderTabs() {
    const nav = $("#tabs");
    const items = [...PUBLIC_TABS];
    if (state.tab === "tab_egrz" || HIDDEN_TABS[state.tab]) {
      const id = state.tab;
      if (!items.find((x) => x[0] === id)) items.push([id, HIDDEN_TABS[id] || id]);
    }
    nav.innerHTML = items
      .map(
        ([id, label]) =>
          `<button type="button" class="tab ${state.tab === id ? "is-active" : ""}" data-tab="${id}">${label}</button>`
      )
      .join("");
  }

  function renderFilters() {
    const meta = state.meta || {};
    const dims = state.dims || {};
    const f = state.filters;
    const years = (meta.years || []).map((y) => ({ label: String(y), value: y }));
    const sources = meta.sources?.options || [];
    const showSource = meta.sources?.show !== false && sources.length > 1;

    const blocks = [];
    if (showSource) {
      blocks.push(filterSelect("source", "Источник", sources, f.source));
    }
    blocks.push(
      filterSelect("agglomeration", "Агломерация", [
        { label: "Все", value: "all" },
        { label: "Анапа", value: "Анапа" },
        { label: "Сочи", value: "Сочи" },
        { label: "Крым", value: "Крым" },
        { label: "Без групп", value: "без групп" },
      ], f.agglomeration)
    );
    blocks.push(`<div class="filter"><label>С даты</label><input type="date" data-filter="date_from" value="${escapeHtml(f.date_from || "")}"></div>`);
    blocks.push(`<div class="filter"><label>По дату</label><input type="date" data-filter="date_to" value="${escapeHtml(f.date_to || "")}"></div>`);
    blocks.push(filterSelect("year", "Год", years, f.year, { emptyLabel: "Все годы" }));
    blocks.push(filterMulti("months", "Месяцы", dims.months || [], f.months));
    blocks.push(`<div class="filter"><label>Бюджет от, млн</label><input type="number" min="0" step="0.5" data-filter="budget_min" value="${escapeHtml(f.budget_min || "")}" placeholder="без мин."></div>`);
    blocks.push(`<div class="filter"><label>Бюджет до, млн</label><input type="number" min="0" step="0.5" data-filter="budget_max" value="${escapeHtml(f.budget_max || "")}" placeholder="напр. 10"></div>`);
    blocks.push(filterMulti("city", "Город", dims.city || [], f.city));
    blocks.push(
      filterSelect("mortgage_mode", "Ипотека", [
        { label: "Все", value: "all" },
        { label: "Ипотека", value: "mortgage" },
        { label: "Не ипотека", value: "non_mortgage" },
      ], f.mortgage_mode)
    );

    if (state.tab === "tab_deals") {
      blocks.push(filterMulti("developer", "Застройщик", dims.developer || [], f.developer));
      blocks.push(filterMulti("project", "Проект", dims.project || [], f.project));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    } else if (state.tab === "tab_complexes") {
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
      blocks.push(filterSelect("object", "Комплекс", dims.object || [], f.object, { emptyLabel: "Выберите комплекс" }));
    } else if (state.tab === "tab_compare") {
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    } else if (state.tab === "tab_euler") {
      blocks.push(filterSelect("type_lot_single", "Тип", dims.type_lot || [], f.type_lot_single, { emptyLabel: "Все типы" }));
      blocks.push(filterMulti("projects", "Проекты (до 3)", dims.project || [], f.projects));
      blocks.push(`<div class="filter"><label>Целевой бюджет</label><input type="number" data-filter="target_budget" value="${escapeHtml(f.target_budget)}"></div>`);
      blocks.push(`<div class="filter"><label>Коридор ±</label><input type="number" data-filter="delta_budget" value="${escapeHtml(f.delta_budget)}"></div>`);
    } else if (state.tab === "tab_heatmap") {
      blocks.push(filterMulti("district", "Район", dims.district || [], f.district));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
      blocks.push(`<div class="filter"><label>Топ N</label><input type="number" min="5" max="100" data-filter="top_n" value="${escapeHtml(f.top_n)}"></div>`);
    } else if (state.tab === "tab_egrz") {
      blocks.length = 0;
      blocks.push(`<div class="filter filter--grow"><label>Поиск</label><input type="search" data-filter="search" value="${escapeHtml(f.search || "")}" placeholder="Объект, застройщик, РНС…"></div>`);
      blocks.push(filterMulti("region", "Регион", state.egrzMeta?.regions || [], f.region));
      blocks.push(filterMulti("work_type", "Вид работ", state.egrzMeta?.work_types || [], f.work_type));
    } else if (state.tab === "tab_lot_growth" || state.tab === "tab_project_growth") {
      blocks.push(filterMulti("district", "Район", dims.district || [], f.district));
      blocks.push(filterMulti("type_lot", "Тип", dims.type_lot || [], f.type_lot));
    }

    $("#filters").innerHTML = blocks.join("");
  }

  function filterSelect(name, label, options, value, { emptyLabel = null } = {}) {
    return `<div class="filter"><label>${escapeHtml(label)}</label><select data-filter="${name}">${optionHtml(options, value, { emptyLabel })}</select></div>`;
  }

  function filterMulti(name, label, options, value) {
    const selected = value || [];
    const summary = selected.length ? `${selected.length} выбрано` : "Все";
    const chips = selected
      .map((v) => `<option value="${escapeHtml(v)}" selected>${escapeHtml(v)}</option>`)
      .join("");
    const rest = (options || [])
      .filter((o) => !selected.includes(o.value))
      .map((o) => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`)
      .join("");
    return `<div class="filter filter--grow filter-multi-wrap">
      <label>${escapeHtml(label)}</label>
      <details class="filter-multi-details">
        <summary>${escapeHtml(summary)}</summary>
        <select multiple data-filter="${name}" data-multi="1" class="filter-multi-panel" size="8">${chips}${rest}</select>
      </details>
    </div>`;
  }

  function showPanel() {
    $$(".panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === state.tab));
    $$(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === state.tab));
  }

  async function loadMeta() {
    state.meta = await api("/api/meta");
    if (state.filters.year == null && state.meta.default_year != null) {
      state.filters.year = state.meta.default_year;
    }
    if ((!state.filters.source || state.filters.source === "all") && state.meta.sources?.default) {
      state.filters.source = state.meta.sources.default;
    }
  }

  async function loadDimensions() {
    state.dims = await api("/api/dimensions");
  }

  async function loadDealsTab() {
    const tension = state.filters.line_shape === "spline" ? 0.35 : 0;
    const kpiP = track((signal) => api("/api/deals/kpi", { signal }).then((d) => {
      $("#w-kpi-deals .kpi-value").textContent = d.total_deals;
      $("#w-kpi-sum .kpi-value").textContent = d.sum_budget;
      $("#w-kpi-avg .kpi-value").textContent = d.avg_budget;
      $$(".kpi-value").forEach((el) => el.classList.remove("skeleton", "skeleton-kpi"));
    }));
    const countsP = track((signal) => api("/api/deals/monthly-counts", { signal }).then((d) => {
      lineChart(
        "monthly-counts",
        $("#chart-monthly-counts"),
        d.labels,
        [
          { label: "Всего", data: d.total, borderColor: "#111", backgroundColor: "transparent" },
          { label: "Ипотека", data: d.mortgage, borderColor: "#3d6ef5", backgroundColor: "transparent" },
          { label: "Не ипотека", data: d.non_mortgage, borderColor: "#9aa3ab", backgroundColor: "transparent" },
        ],
        { tension }
      );
    }));
    const avgP = track((signal) => api("/api/deals/monthly-avg", { signal }).then((d) => {
      lineChart(
        "monthly-avg",
        $("#chart-monthly-avg"),
        d.labels,
        [{ label: "Средний бюджет", data: d.avg, borderColor: "#3d6ef5", backgroundColor: "transparent" }],
        { tension }
      );
    }));
    const topP = track((signal) => api("/api/deals/top-complexes", { signal }).then((d) => {
      renderBarList($("#chart-top-total"), d.total || []);
      renderBarList($("#chart-top-mortgage"), d.mortgage || []);
    }));
    await Promise.allSettled([kpiP, countsP, avgP, topP]);
  }

  async function loadComplexesTab() {
    const cityP = track((signal) => api("/api/complexes/city-counts", { signal }).then((d) => {
      barChart("city", $("#chart-city-counts"), d.labels, d.values);
    }));
    const monP = track((signal) => api("/api/complexes/monthly", { signal }).then((d) => {
      if (!d.name) {
        const el = $("#chart-complex-monthly");
        el.classList.remove("skeleton", "skeleton-chart");
        el.innerHTML = '<div class="empty">Выберите комплекс в фильтрах</div>';
        return;
      }
      barChart("complex-monthly", $("#chart-complex-monthly"), d.labels, d.values, { horizontal: false });
    }));
    await Promise.allSettled([cityP, monP]);
  }

  async function loadCompareTab() {
    await track(async (signal) => {
      const d = await api("/api/compare", { signal });
      scatterChart("compare", $("#chart-compare"), d.points || [], (name) => {
        const set = new Set(state.filters.selected);
        if (set.has(name)) set.delete(name);
        else set.add(name);
        state.filters.selected = [...set];
        writeUrl();
        loadCompareTab();
      });
      renderTable(
        $("#table-compare"),
        d.rows || [],
        [
          { key: "object", label: "Комплекс" },
          { key: "city", label: "Город" },
          { key: "developer", label: "Девелопер" },
          { key: "deals", label: "Сделок" },
          { key: "avg_budget", label: "Средний бюджет" },
          { key: "avg_price_sqm", label: "Цена м²" },
        ],
        { selected: state.filters.selected }
      );
      $("#table-compare").onclick = (e) => {
        const tr = e.target.closest("tr[data-key]");
        if (!tr) return;
        const name = tr.dataset.key;
        const set = new Set(state.filters.selected);
        if (set.has(name)) set.delete(name);
        else set.add(name);
        state.filters.selected = [...set];
        writeUrl();
        loadCompareTab();
      };
    });
  }

  async function loadEulerTab() {
    await track(async (signal) => {
      const d = await api("/api/euler", { signal });
      const el = $("#euler-summary");
      el.classList.remove("skeleton", "skeleton-chart");
      if (d.message) {
        el.innerHTML = `<div class="empty">${escapeHtml(d.message)}</div>`;
        return;
      }
      const boxes = (d.projects || [])
        .map((p) => `<div class="euler-box">${escapeHtml(p)}<strong>${fmt(d.sizes?.[p] || 0)}</strong><span class="muted">в коридоре</span></div>`)
        .join("");
      const pairs = Object.entries(d.pairs || {})
        .map(([k, v]) => {
          const [a, b] = k.split("||");
          return `<div class="euler-box">${escapeHtml(a)} ∩ ${escapeHtml(b)}<strong>${fmt(v)}</strong></div>`;
        })
        .join("");
      const triple =
        (d.projects || []).length === 3
          ? `<div class="euler-box">Все три<strong>${fmt(d.triple || 0)}</strong></div>`
          : "";
      el.innerHTML = `<p class="muted">Коридор бюджета: ${fmt(d.band?.lo)} – ${fmt(d.band?.hi)} ₽</p><div class="euler-boxes">${boxes}${pairs}${triple}</div>`;
    });
  }

  async function loadHeatmapTab() {
    await track(async (signal) => {
      const d = await api("/api/heatmap", { signal });
      renderHeatmap($("#heatmap"), d);
    });
  }

  async function loadEgrzTab() {
    await track(async (signal) => {
      const d = await api("/api/egrz", { signal });
      state.egrzMeta = { regions: d.regions || [], work_types: d.work_types || [] };
      renderFilters();
      const el = $("#table-egrz");
      if (d.message) {
        el.classList.remove("skeleton", "skeleton-chart");
        el.innerHTML = `<div class="empty">${escapeHtml(d.message)}</div>`;
        return;
      }
      renderTable(
        el,
        d.rows || [],
        [
          { key: "date", label: "Дата" },
          { key: "rns", label: "РНС" },
          { key: "city", label: "Город" },
          { key: "object", label: "Объект" },
          { key: "developer", label: "Застройщик" },
          { key: "work_type", label: "Вид работ" },
          { key: "keys", label: "Ключи" },
        ],
        { rowKey: "rns" }
      );
      const title = el.previousElementSibling;
      if (title) title.textContent = `ЕГРЗ · ${fmt(d.total)} записей`;
    });
  }

  async function loadLotGrowthTab() {
    await track(async (signal) => {
      const d = await api("/api/lot-growth", { signal });
      const s = d.series || {};
      lineChart(
        "lot-growth",
        $("#chart-lot-growth"),
        s.labels || [],
        [
          { label: "Средний бюджет", data: s.avg_budget || [], borderColor: "#3d6ef5", backgroundColor: "transparent", yAxisID: "y" },
          { label: "Сделок", data: s.deals || [], borderColor: "#111", backgroundColor: "transparent", yAxisID: "y1" },
        ]
      );
      renderTable($("#table-lot-growth"), d.rows || [], [
        { key: "month", label: "Месяц" },
        { key: "deals", label: "Сделок" },
        { key: "avg_budget", label: "Средний бюджет" },
        { key: "avg_sqm", label: "Цена м²" },
      ], { rowKey: "month" });
    });
  }

  async function loadProjectGrowthTab() {
    await track(async (signal) => {
      const d = await api("/api/project-growth", { signal });
      renderBarList($("#chart-pg-budget"), d.budget_pct || []);
      renderBarList($("#chart-pg-sqm"), d.sqm_pct || []);
      renderTable($("#table-pg"), d.rows || [], [
        { key: "object", label: "Проект" },
        { key: "city", label: "Город" },
        { key: "deals", label: "Сделок" },
        { key: "budget_growth_pct", label: "Рост бюджета %" },
        { key: "sqm_growth_pct", label: "Рост м² %" },
      ]);
    });
  }

  async function loadActiveTab({ refreshDims = true } = {}) {
    abortAll();
    showPanel();
    renderTabs();
    if (refreshDims && state.tab !== "tab_egrz") {
      try {
        await loadDimensions();
      } catch (_) {
        /* ignore */
      }
    }
    renderFilters();
    writeUrl();

    if (ADMIN_TABS.has(state.tab) && !state.filters.access) {
      const msg = '<div class="empty">Нужен параметр access в ссылке</div>';
      if (state.tab === "tab_lot_growth") {
        $("#chart-lot-growth").innerHTML = msg;
        $("#table-lot-growth").innerHTML = msg;
      } else {
        $("#chart-pg-budget").innerHTML = msg;
        $("#chart-pg-sqm").innerHTML = msg;
        $("#table-pg").innerHTML = msg;
      }
      return;
    }

    const loaders = {
      tab_deals: loadDealsTab,
      tab_complexes: loadComplexesTab,
      tab_compare: loadCompareTab,
      tab_euler: loadEulerTab,
      tab_heatmap: loadHeatmapTab,
      tab_egrz: loadEgrzTab,
      tab_lot_growth: loadLotGrowthTab,
      tab_project_growth: loadProjectGrowthTab,
    };
    const fn = loaders[state.tab];
    if (fn) await fn();
    state.loadedTabs.add(state.tab);
  }

  function bindEvents() {
    $("#tabs").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tab]");
      if (!btn) return;
      state.tab = btn.dataset.tab;
      state.filters.selected = [];
      loadActiveTab();
    });

    $("#filters").addEventListener("change", (e) => {
      const el = e.target.closest("[data-filter]");
      if (!el) return;
      const key = el.dataset.filter;
      if (el.dataset.multi) {
        state.filters[key] = [...el.selectedOptions].map((o) => o.value);
      } else if (el.type === "number") {
        state.filters[key] = el.value === "" ? "" : Number(el.value);
      } else {
        state.filters[key] = el.value;
      }
      if (key === "developer") state.filters.project = [];
      if (["source", "agglomeration", "year", "date_from", "date_to", "developer"].includes(key)) {
        loadActiveTab({ refreshDims: true });
      } else {
        loadActiveTab({ refreshDims: false });
      }
    });

    $("#line-style-toolbar")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-shape]");
      if (!btn) return;
      state.filters.line_shape = btn.dataset.shape;
      $$("#line-style-toolbar .btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      loadDealsTab();
      writeUrl();
    });

    $("#cmp-clear")?.addEventListener("click", () => {
      state.filters.selected = [];
      writeUrl();
      loadCompareTab();
    });
  }

  async function boot() {
    readUrl();
    renderTabs();
    showPanel();
    bindEvents();
    try {
      await api("/api/me");
      await loadMeta();
      await loadActiveTab({ refreshDims: true });
    } catch (err) {
      if (String(err.message) !== "unauthorized") {
        console.error(err);
        $("#filters").innerHTML = `<div class="empty">Не удалось загрузить данные: ${escapeHtml(err.message)}</div>`;
      }
    }
  }

  boot();
})();
