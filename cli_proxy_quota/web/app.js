import { messages } from "./i18n.js";
const $ = (id) => document.getElementById(id),
  ns = "http://www.w3.org/2000/svg";
const embedded = window.parent !== window && new URLSearchParams(location.search).get("embedded") === "1";
if (embedded) {
  document.documentElement.dataset.embedded = "true";
  addEventListener("message", (event) => {
    if (!document.referrer || event.source !== parent || event.origin !== new URL(document.referrer).origin) return;
    if (event.data?.type !== "quota-appearance") return;
    if (!["light", "dark"].includes(event.data.theme) || !["en", "ko"].includes(event.data.language)) return;
    theme = event.data.theme;
    lang = event.data.language;
    applyLanguage();
    applyTheme();
  });
}
let lang =
  localStorage.getItem("quota-language") ||
  (navigator.language.startsWith("ko") ? "ko" : "en");
let theme = localStorage.getItem("quota-theme") || "system",
  latest = null,
  busy = false,
  queued = false,
  period = "today",
  sequence = 0;
const tr = (key) => {
  if (!messages[lang]?.[key]) throw Error(`Missing translation: ${key}`);
  return messages[lang][key];
};
const number = (value) =>
  value == null ? "—" : new Intl.NumberFormat(lang).format(value);
const compact = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat(lang, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
const date = (value) =>
  new Intl.DateTimeFormat(lang, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
const shortDate = (value) =>
  new Intl.DateTimeFormat(lang, { month: "short", day: "numeric" }).format(
    new Date(value * 1000),
  );
const text = (tag, content, className) => {
  const node = document.createElement(tag);
  node.textContent = content;
  if (className) node.className = className;
  return node;
};
function svgNode(tag, attrs = {}, content) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attrs))
    node.setAttribute(key, value);
  if (content !== undefined) node.textContent = content;
  return node;
}
function applyTheme() {
  const dark =
    theme === "dark" ||
    (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  if (latest) render(latest);
}
function applyLanguage() {
  document.documentElement.lang = lang;
  document
    .querySelectorAll("[data-t]")
    .forEach((node) => (node.textContent = tr(node.dataset.t)));
  document
    .querySelectorAll("[data-t-aria]")
    .forEach((node) => node.setAttribute("aria-label", tr(node.dataset.tAria)));
  $("language").value = lang;
  $("theme").value = theme;
  if (latest) render(latest);
}
function notice(message, enable = false) {
  $("notice").hidden = !message;
  $("notice-text").textContent = message;
  $("enable").hidden = !enable;
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Quota-Client": "1",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    if (response.status === 401) throw Error(tr("login"));
    throw Error(tr("failed"));
  }
  return response.json();
}
function localDate(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
function setPeriod(value) {
  period = value;
  const end = new Date(),
    start = new Date(end);
  start.setHours(0, 0, 0, 0);
  if (value !== "today" && value !== "all")
    start.setDate(start.getDate() - Number(value) + 1);
  $("start").value = value === "all" ? "" : localDate(start);
  $("end").value = localDate(end);
  $("periods")
    .querySelectorAll("button")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.period === value),
      ),
    );
}
function range() {
  const end = new Date($("end").value + "T00:00:00");
  end.setDate(end.getDate() + 1);
  const start = $("start").value
    ? new Date($("start").value + "T00:00:00")
    : new Date(1970, 0, 1);
  if (!Number.isFinite(+start) || !Number.isFinite(+end) || end <= start)
    throw Error(tr("invalidDates"));
  return { start: +start / 1000, end: +end / 1000 };
}
function optionList(id, items, empty) {
  const select = $(id),
    current = select.value;
  select.replaceChildren();
  const option = text("option", tr(empty));
  option.value = "";
  select.append(option);
  for (const [value, label] of items) {
    const item = text("option", label);
    item.value = value;
    select.append(item);
  }
  if ([...select.options].some((option) => option.value === current))
    select.value = current;
}
function plan(code) {
  return (
    {
      prolite: "Pro Lite",
      self_serve_business_prolite: "Business Pro Lite",
      team: "Team",
      pro: "Pro",
      free: "Free",
      credits: "Credits",
      max: "Max",
      max_5x: "Max 5x",
      max_20x: "Max 20x",
      unknown: tr("unknown"),
      oauth: tr("unknown"),
    }[code] || code.replace(/^self_serve_|^claude_/g, "").replaceAll("_", " ")
  );
}
function accountName(report, index) {
  return $("identities").checked
    ? report.alias || report.email || report.name
    : `${report.provider === "codex" ? "Codex" : report.provider === "claude" ? "Claude" : "OpenRouter"} · ${plan(report.plan_type)} · ${index + 1}`;
}
function emptyChart(id, message = "noData") {
  $(id).replaceChildren(text("p", tr(message)));
}
function chartBase(id, height = 220, width = 500) {
  const chart = svgNode("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label":
      id === "line-chart"
        ? tr("trend")
        : id === "bar-chart"
          ? tr("daily")
          : tr("compare"),
  });
  $(id).replaceChildren(chart);
  return chart;
}
function scaleChart(chart, maximum) {
  for (let step = 0; step < 4; step++) {
    const y = 18 + step * 52;
    chart.append(
      svgNode("line", { x1: 45, y1: y, x2: 488, y2: y, class: "grid-line" }),
      svgNode(
        "text",
        { x: 38, y: y + 4, "text-anchor": "end" },
        compact(maximum * (1 - step / 3)),
      ),
    );
  }
}
function renderLine(data) {
  const points = data.timeline;
  if (
    !points.some(
      (point) => point.input_tokens != null || point.output_tokens != null,
    )
  ) {
    emptyChart("line-chart", points.length ? "noTokenData" : "noData");
    return;
  }
  const chart = chartBase("line-chart"),
    maximum = Math.max(
      1,
      ...points.flatMap((point) => [
        point.input_tokens || 0,
        point.output_tokens || 0,
      ]),
    );
  scaleChart(chart, maximum);
  const start = points[0].timestamp,
    end = points.at(-1).timestamp || start;
  const x = (time) =>
      45 + ((time - start) / Math.max(data.bucket_seconds, end - start)) * 443,
    y = (value) => 174 - (value / maximum) * 156;
  for (const key of ["input", "output"]) {
    let path = "",
      previous = null;
    for (const point of points) {
      const value = point[`${key}_tokens`];
      if (value == null) {
        previous = null;
        continue;
      }
      const gap =
        previous == null ||
        point.timestamp - previous >
          (data.bucket_seconds === 86400
            ? 27 * 3600
            : data.bucket_seconds * 1.01);
      path += `${gap ? "M" : "L"}${x(point.timestamp)},${y(value)} `;
      const dot = svgNode("circle", {
        cx: x(point.timestamp),
        cy: y(value),
        r: 3,
        class: `series-dot-${key}`,
      });
      dot.append(
        svgNode(
          "title",
          {},
          `${date(point.timestamp)} · ${tr(key)} ${number(value)}`,
        ),
      );
      chart.append(dot);
      previous = point.timestamp;
    }
    chart.append(svgNode("path", { d: path, class: `series-${key}` }));
  }
  for (const time of [...new Set([start, end])])
    chart.append(
      svgNode(
        "text",
        { x: x(time), y: 207, "text-anchor": time === start ? "start" : "end" },
        data.bucket_seconds === 3600 ? date(time) : shortDate(time),
      ),
    );
}
function renderDaily(data) {
  const points = data.daily.filter((point) => point.total_tokens != null);
  if (!points.length) {
    emptyChart("bar-chart", data.daily.length ? "noTokenData" : "noData");
    return;
  }
  const chart = chartBase("bar-chart"),
    maximum = Math.max(1, ...points.map((point) => point.total_tokens)),
    width = 443 / points.length;
  scaleChart(chart, maximum);
  points.forEach((point, index) => {
    const x = 45 + index * width + width * 0.15,
      height = (point.total_tokens / maximum) * 156,
      bar = svgNode("rect", {
        x,
        y: 174 - height,
        width: Math.max(1, width * 0.7),
        height,
        class: "bar",
        rx: 2,
      });
    bar.append(
      svgNode(
        "title",
        {},
        `${shortDate(point.timestamp)} · ${tr("total")} ${number(point.total_tokens)}`,
      ),
    );
    chart.append(bar);
    if (index === 0 || index === points.length - 1 || points.length < 6)
      chart.append(
        svgNode(
          "text",
          { x: x + width * 0.35, y: 207, "text-anchor": "middle" },
          shortDate(point.timestamp),
        ),
      );
  });
}
function renderComparison(data, reports) {
  const points = data.accounts.filter(
    (account) => account.total_tokens != null,
  );
  if (!points.length) {
    emptyChart(
      "account-chart",
      data.accounts.length ? "noTokenData" : "noData",
    );
    return;
  }
  const height = Math.max(100, points.length * 38 + 16),
    width = Math.max(500, $("account-chart").clientWidth),
    chart = chartBase("account-chart", height, width),
    maximum = Math.max(1, ...points.map((point) => point.total_tokens));
  points.forEach((point, index) => {
    const report = reports.find(
        (report) => report.auth_index === point.account_id,
      ),
      name = report
        ? accountName(report, reports.indexOf(report))
        : `${point.provider} · ${point.account_id.slice(0, 8)}`;
    chart.append(
      svgNode(
        "text",
        { x: 0, y: index * 38 + 28 },
        name.length > (innerWidth < 560 ? 19 : 29)
          ? name.slice(0, innerWidth < 560 ? 17 : 27) + "…"
          : name,
      ),
    );
    const bar = svgNode("rect", {
      x: 205,
      y: index * 38 + 14,
      width: (point.total_tokens / maximum) * (width - 270),
      height: 15,
      rx: 2,
      class: "bar",
    });
    bar.append(svgNode("title", {}, `${name} · ${number(point.total_tokens)}`));
    chart.append(
      bar,
      svgNode(
        "text",
        { x: width - 5, y: index * 38 + 28, "text-anchor": "end" },
        compact(point.total_tokens),
      ),
    );
  });
}
function renderAccounts(data) {
  const rows = $("accounts");
  rows.replaceChildren();
  const reports = data.reports.filter(
    (report) =>
      (!$("provider").value || report.provider === $("provider").value) &&
      (!$("account").value || report.auth_index === $("account").value),
  );
  const rendered = new Set();
  for (const report of reports) {
    const stats = data.accounts.find(
      (account) =>
        account.account_id === report.auth_index &&
        account.provider === report.provider,
    );
    rendered.add(`${report.provider}:${report.auth_index}`);
    const row = document.createElement("tr"),
      identity = document.createElement("td"),
      wrap = text("div", "", "account-cell"),
      icon = document.createElement("img");
    icon.alt = "";
    icon.className =
      "service-icon" + (report.provider === "openrouter" ? "" : " symbolic");
    icon.src =
      "/assets/" +
      (report.provider === "openrouter"
        ? `openrouter-${document.documentElement.dataset.theme}.svg`
        : `${report.provider}-symbolic.svg`);
    wrap.append(
      icon,
      text("span", accountName(report, data.reports.indexOf(report))),
    );
    identity.append(wrap);
    row.append(identity);
    const badge = document.createElement("td");
    badge.append(text("span", plan(report.plan_type), "badge"));
    row.append(badge);
    const quota = document.createElement("td"),
      stack = text("div", "", "quota-stack");
    for (const window of report.windows) {
      const metric = text("div", window.label + " ", "quota-row");
      if (window.remaining_percent != null) {
        const value = window.remaining_percent,
          track = text("span", "", "quota-track"),
          graphic = svgNode("svg", {
            viewBox: "0 0 100 4",
            "aria-hidden": "true",
          });
        graphic.append(
          svgNode("rect", {
            x: 0,
            y: 0,
            width: Math.max(0, Math.min(100, value)),
            height: 4,
            class:
              value < 20
                ? "quota-bad"
                : value < 50
                  ? "quota-warn"
                  : "quota-good",
          }),
        );
        track.append(graphic);
        metric.append(track, text("span", `${number(value)}%`));
        if (window.reset_at)
          metric.title = new Intl.DateTimeFormat(lang, {
            dateStyle: "medium",
            timeStyle: "short",
          }).format(new Date(window.reset_at));
      } else
        metric.append(
          text(
            "span",
            window.used_count != null
              ? `≥${number(window.used_count)} / ${number(window.limit_count)}`
              : tr("missing"),
          ),
        );
      stack.append(metric);
    }
    quota.append(stack);
    row.append(quota);
    appendStats(row, stats);
    rows.append(row);
  }
  for (const stats of data.accounts) {
    if (rendered.has(`${stats.provider}:${stats.account_id}`)) continue;
    const row = document.createElement("tr");
    row.append(
      text("td", `${stats.provider} · ${stats.account_id.slice(0, 8)}`),
      text("td", tr("historyOnly")),
      text("td", "—"),
    );
    appendStats(row, stats);
    rows.append(row);
  }
  if (!rows.children.length) {
    const row = document.createElement("tr"),
      cell = text(
        "td",
        data.status.quota_error ? tr("quotaError") : tr("noAccounts"),
      );
    cell.colSpan = 8;
    row.append(cell);
    rows.append(row);
  }
}
function appendStats(row, stats) {
  for (const key of [
    "requests",
    "input_tokens",
    "output_tokens",
    "cache",
    "total_tokens",
  ]) {
    let value = stats?.[key];
    if (key === "cache")
      value = stats
        ? stats.cache_read_tokens == null && stats.cache_write_tokens == null
          ? null
          : (stats.cache_read_tokens || 0) + (stats.cache_write_tokens || 0)
        : null;
    row.append(text("td", number(value), "numeric"));
  }
}
function render(data) {
  const summary = data.summary;
  $("requests").textContent = number(summary.requests);
  $("success").textContent = summary.requests
    ? `${new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(((summary.requests - (summary.failures || 0)) / summary.requests) * 100)}%`
    : "—";
  for (const [key, field] of [
    ["total", "total_tokens"],
    ["input", "input_tokens"],
    ["output", "output_tokens"],
  ])
    $(key).textContent = compact(summary[field]);
  $("cache").textContent = compact(
    summary.cache_read_tokens == null && summary.cache_write_tokens == null
      ? null
      : (summary.cache_read_tokens || 0) + (summary.cache_write_tokens || 0),
  );
  const status = data.status,
    coverage = data.coverage,
    now = Date.now() / 1000;
  const runs = data.collection_runs;
  const hasGaps = runs.some(
    (run, index) =>
      index > 0 &&
      runs[index - 1].last_collected_at != null &&
      run.started_at - runs[index - 1].last_collected_at > 15 &&
      run.started_at < data.range.end &&
      runs[index - 1].last_collected_at > data.range.start,
  );
  let message = "";
  if (status.demo) message = tr("demo");
  else if (status.error) message = `${tr("failed")} ${status.error}`;
  else if (status.recording === false) message = tr("disabled");
  else if (status.recording == null) message = tr("pending");
  else if (status.quota_error) message = tr("quotaError");
  else if (data.errors.length)
    message = data.errors
      .map((error) => `${error.provider}: ${error.message}`)
      .join(" · ");
  else if (status.last_collected_at && now - status.last_collected_at > 45)
    message = tr("gap");
  else message = hasGaps ? tr("gap") : tr("collecting");
  notice(message, status.recording === false);
  $("coverage").textContent = coverage.started_at
    ? `${tr("started")} ${date(coverage.started_at)} · ${tr("lastCollected")} ${coverage.last_collected_at ? date(coverage.last_collected_at) : "—"}`
    : tr("noData");
  $("quality").textContent = summary.unmeasured
    ? `${tr("unmeasured")}: ${number(summary.unmeasured)} · ${tr("partial")}`
    : "";
  $("updated").textContent =
    `${tr("updated")} ${new Intl.DateTimeFormat(lang, { timeStyle: "short" }).format(new Date())}`;
  optionList(
    "account",
    data.reports.map((report, index) => [
      report.auth_index,
      accountName(report, index),
    ]),
    "allAccounts",
  );
  optionList(
    "model",
    data.models.map((model) => [model, model]),
    "allModels",
  );
  renderLine(data);
  renderDaily(data);
  renderAccounts(data);
  renderComparison(data, data.reports);
  const rows = $("chart-data");
  rows.replaceChildren();
  for (const point of data.timeline) {
    const row = document.createElement("tr");
    row.append(
      text("td", date(point.timestamp)),
      text("td", number(point.input_tokens)),
      text("td", number(point.output_tokens)),
      text("td", number(point.total_tokens)),
    );
    rows.append(row);
  }
}
async function refresh() {
  if (busy) {
    queued = true;
    sequence++;
    return;
  }
  busy = true;
  $("refresh").disabled = true;
  const current = ++sequence;
  try {
    const selected = range(),
      query = new URLSearchParams({
        ...selected,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
    for (const key of ["provider", "account", "model"])
      if ($(key).value) query.set(key, $(key).value);
    const data = await api("/api/usage?" + query);
    if (current === sequence) {
      latest = data;
      render(data);
    }
  } catch (error) {
    notice(error.message);
  } finally {
    busy = false;
    $("refresh").disabled = false;
    if (queued) {
      queued = false;
      refresh();
    }
  }
}
$("language").addEventListener("change", () => {
  lang = $("language").value;
  localStorage.setItem("quota-language", lang);
  applyLanguage();
});
$("theme").addEventListener("change", () => {
  theme = $("theme").value;
  localStorage.setItem("quota-theme", theme);
  applyTheme();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (theme === "system") applyTheme();
});
$("refresh").addEventListener("click", refresh);
$("periods").addEventListener("click", (event) => {
  const button = event.target.closest("[data-period]");
  if (button) {
    setPeriod(button.dataset.period);
    refresh();
  }
});
for (const key of ["provider", "account", "model"])
  $(key).addEventListener("change", refresh);
for (const key of ["start", "end"])
  $(key).addEventListener("change", () => {
    period = "custom";
    $("periods")
      .querySelectorAll("button")
      .forEach((button) => button.setAttribute("aria-pressed", "false"));
    refresh();
  });
$("identities").addEventListener("change", () => {
  if (latest) render(latest);
});
$("enable").addEventListener("click", async () => {
  try {
    $("enable").disabled = true;
    await api("/api/recording", {});
    await refresh();
  } catch (error) {
    notice(tr("failedEnable"));
  } finally {
    $("enable").disabled = false;
  }
});
applyLanguage();
applyTheme();
setPeriod("today");
notice(tr("loading"));
async function bootstrap() {
  try {
    const token = new URLSearchParams(location.hash.slice(1)).get("token");
    if (token) {
      history.replaceState(null, "", location.pathname);
      await api("/api/session", { token });
    }
    await refresh();
    if (embedded && document.referrer) {
      parent.postMessage({ type: "quota-ready" }, new URL(document.referrer).origin);
    }
  } catch (error) {
    notice(error.message);
  }
}
addEventListener("hashchange", bootstrap);
await bootstrap();
setInterval(() => {
  if (!document.hidden) refresh();
}, 10000);

let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (latest) render(latest);
  }, 100);
});
