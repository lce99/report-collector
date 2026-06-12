const TOOLBAR_PIN_STORAGE_KEY = "broker-report-toolbar-pinned";
const THEME_STORAGE_KEY = "broker-report-theme";

const state = {
  index: null,
  subjectIndex: null,
  digest: null,
  performance: null,
  subjectDetail: null,
  selectedDate: null,
  selectedSubjectKey: null,
  query: "",
  selectedCategory: "all",
  selectedBroker: "all",
  sortBy: "score",
  priorityOnlyView: false,
  changesOnlyView: false,
  toolbarPinned: false,
  theme: "light",
};

function debounce(fn, delayMs = 200) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delayMs);
  };
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = text;
  }
  return node;
}

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`);
  }
  return response.json();
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return new Intl.NumberFormat("ko-KR").format(Number(value));
}

function formatDuration(value) {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds)) {
    return "0.00초";
  }
  return `${seconds.toFixed(2)}초`;
}

function sourceStatusLabel(status) {
  if (status === "ok") {
    return "정상";
  }
  if (status === "empty") {
    return "무출력";
  }
  if (status === "failed") {
    return "실패";
  }
  return "확인 필요";
}

function alertSeverityLabel(severity) {
  if (severity === "critical") {
    return "긴급";
  }
  if (severity === "warning") {
    return "주의";
  }
  return "확인";
}

function formatShortDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateLabel(date) {
  if (!date) {
    return "-";
  }
  const parsed = new Date(`${date}T00:00:00+09:00`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }
  return parsed.toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}

function formatTargetValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return formatNumber(value);
}

function buildDailyHref(date) {
  const params = new URLSearchParams(window.location.search);
  params.delete("subject");
  if (date) {
    params.set("date", date);
  }
  const query = params.toString();
  return query ? `${window.location.pathname}?${query}` : window.location.pathname;
}

function buildSubjectHref(subjectKey) {
  if (!subjectKey) {
    return "#";
  }
  const params = new URLSearchParams(window.location.search);
  if (state.selectedDate) {
    params.set("date", state.selectedDate);
  }
  params.set("subject", subjectKey);
  return `${window.location.pathname}?${params.toString()}`;
}

function getRequestedSubject() {
  const params = new URLSearchParams(window.location.search);
  return params.get("subject");
}

function syncSubjectInUrl(subjectKey) {
  const params = new URLSearchParams(window.location.search);
  if (state.selectedDate) {
    params.set("date", state.selectedDate);
  }
  if (subjectKey) {
    params.set("subject", subjectKey);
  } else {
    params.delete("subject");
  }
  const query = params.toString();
  const next = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, "", next);
}

function resolveSubjectKey(query) {
  const normalizedQuery = normalize(query).replace(/\s+/g, "");
  if (!normalizedQuery || !state.subjectIndex?.subjects?.length) {
    return null;
  }

  const exact = state.subjectIndex.subjects.find((item) => {
    const subjectName = normalize(item.subject_name).replace(/\s+/g, "");
    return item.subject_key === normalizedQuery || subjectName === normalizedQuery;
  });
  if (exact) {
    return exact.subject_key;
  }

  const partial = state.subjectIndex.subjects.find((item) => {
    const subjectName = normalize(item.subject_name).replace(/\s+/g, "");
    return item.subject_key.includes(normalizedQuery) || subjectName.includes(normalizedQuery);
  });
  return partial?.subject_key || null;
}

function loadToolbarPinnedPreference() {
  try {
    return window.localStorage.getItem(TOOLBAR_PIN_STORAGE_KEY) === "true";
  } catch (error) {
    console.error(error);
    return false;
  }
}

function saveToolbarPinnedPreference() {
  try {
    window.localStorage.setItem(TOOLBAR_PIN_STORAGE_KEY, String(state.toolbarPinned));
  } catch (error) {
    console.error(error);
  }
}

function applyToolbarPinnedState() {
  const toolbar = document.querySelector(".toolbar");
  const toggle = document.getElementById("toolbarPinnedToggle");
  if (toolbar) {
    toolbar.classList.toggle("toolbar-pinned", state.toolbarPinned);
  }
  if (toggle) {
    toggle.checked = state.toolbarPinned;
  }
}

function loadThemePreference() {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") {
      return saved;
    }
  } catch (error) {
    console.error(error);
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function saveThemePreference() {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  } catch (error) {
    console.error(error);
  }
}

function applyThemeState() {
  document.documentElement.dataset.theme = state.theme;
  const toggle = document.getElementById("darkModeToggle");
  if (toggle) {
    toggle.checked = state.theme === "dark";
  }
}

function populateSubjectSuggestions() {
  const datalist = document.getElementById("subjectSuggestions");
  const quickLinks = document.getElementById("subjectQuickLinks");
  datalist.innerHTML = "";
  quickLinks.innerHTML = "";

  if (!state.subjectIndex?.subjects?.length) {
    quickLinks.appendChild(el("span", "hint-chip", "종목 인덱스를 아직 불러오지 못했습니다."));
    return;
  }

  state.subjectIndex.subjects.slice(0, 200).forEach((item) => {
    const option = el("option");
    option.value = item.subject_name || item.subject_key;
    option.label = `${item.subject_name || item.subject_key} · ${formatNumber(item.report_count || 0)}건`;
    datalist.appendChild(option);
  });

  const featured = [...state.subjectIndex.subjects]
    .sort((left, right) => {
      const changeGap = Number(right.changed_reports || 0) - Number(left.changed_reports || 0);
      if (changeGap !== 0) {
        return changeGap;
      }
      return Number(right.report_count || 0) - Number(left.report_count || 0);
    })
    .slice(0, 8);

  featured.forEach((item) => {
    const link = el("a", "hint-chip chip-link");
    link.href = buildSubjectHref(item.subject_key);
    link.textContent = `${item.subject_name} · ${formatNumber(item.changed_reports || 0)}건 변화`;
    quickLinks.appendChild(link);
  });
}

function normalize(text) {
  return String(text || "").toLowerCase();
}

function compactText(text, maxLength = 180) {
  const cleaned = String(text || "").replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return "요약 정보가 아직 없습니다.";
  }
  return cleaned.length > maxLength ? `${cleaned.slice(0, maxLength - 1)}…` : cleaned;
}

function syncSelectedDate(date) {
  const params = new URLSearchParams(window.location.search);
  params.set("date", date);
  const next = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, "", next);
}

function hasChangeSignal(report) {
  return Boolean(
    report &&
      (report.target_price_change ||
        report.opinion_changed ||
        report.analyst_changed ||
        (report.change_reasons && report.change_reasons.length) ||
        (report.estimate_signal_types && report.estimate_signal_types.length) ||
        (report.estimate_reasons && report.estimate_reasons.length))
  );
}

function reportMatchesFilters(report) {
  if (!report) {
    return false;
  }

  if (state.priorityOnlyView && !report.is_priority_match) {
    return false;
  }

  if (state.changesOnlyView && !hasChangeSignal(report)) {
    return false;
  }

  if (state.selectedCategory !== "all" && report.category !== state.selectedCategory) {
    return false;
  }

  if (state.selectedBroker !== "all" && report.broker !== state.selectedBroker) {
    return false;
  }

  if (!state.query) {
    return true;
  }

  const haystack = [
    report.display_title,
    report.title,
    report.broker,
    report.subject,
    report.category_label,
    report.summary,
    report.excerpt,
    report.analyst,
    report.target_price,
    report.previous_target_price,
    report.opinion,
    report.previous_opinion,
    report.previous_analyst,
    estimateMetricsText(report.estimate_metrics),
    ...(report.estimate_reasons || []),
    ...(report.estimate_signal_types || []),
    investmentMemoText(report.investment_memo),
    ...(report.score_reasons || []),
    ...(report.priority_subject_matches || []),
    ...(report.priority_keyword_matches || []),
    ...(report.change_reasons || []),
  ]
    .map(normalize)
    .join(" ");

  return haystack.includes(state.query);
}

function sortReports(reports) {
  const sorted = [...reports];
  sorted.sort((left, right) => {
    if (state.sortBy === "changes") {
      const changeGap = Number(hasChangeSignal(right)) - Number(hasChangeSignal(left));
      if (changeGap !== 0) {
        return changeGap;
      }
    }

    if (state.sortBy === "views") {
      const gap = Number(right.views || 0) - Number(left.views || 0);
      if (gap !== 0) {
        return gap;
      }
    }

    if (state.sortBy === "latest") {
      const dateGap = normalize(right.published_date).localeCompare(normalize(left.published_date));
      if (dateGap !== 0) {
        return dateGap;
      }
    }

    if (state.sortBy === "title") {
      const titleGap = normalize(left.display_title).localeCompare(normalize(right.display_title), "ko");
      if (titleGap !== 0) {
        return titleGap;
      }
    }

    const scoreGap = Number(right.score || 0) - Number(left.score || 0);
    if (scoreGap !== 0) {
      return scoreGap;
    }

    return Number(right.views || 0) - Number(left.views || 0);
  });
  return sorted;
}

function getFilteredReports() {
  return sortReports((state.digest?.reports || []).filter(reportMatchesFilters));
}

function getFilteredSubjectReports() {
  return sortReports((state.subjectDetail?.timeline || []).filter(reportMatchesFilters));
}

function isSubjectMode() {
  return Boolean(state.selectedSubjectKey && state.subjectDetail);
}

function buildBadge(text, tone = "default") {
  return el("span", `badge badge-${tone}`, text);
}

function buildDatum(label, value) {
  return el("span", "datum", `${label} ${value}`);
}

function estimateMetricsText(metrics) {
  return (metrics || [])
    .map((metric) =>
      [
        metric.label,
        metric.period,
        formatEstimateMetric(metric),
        metric.source_excerpt,
      ]
        .filter(Boolean)
        .join(" ")
    )
    .join(" ");
}

function estimateMetricValue(metric, group) {
  if (!metric) {
    return null;
  }
  if (group === "margin") {
    return metric.value_pct ?? metric.value;
  }
  return metric.value_krw_100m ?? metric.value_won ?? metric.value;
}

function estimateMetricUnit(metric, group) {
  if (group === "margin") {
    return "%";
  }
  if (metric?.value_krw_100m !== null && metric?.value_krw_100m !== undefined) {
    return "억원";
  }
  return metric?.unit || "";
}

function formatEstimateMetric(metric) {
  if (!metric) {
    return "-";
  }
  if (metric.value_krw_100m !== null && metric.value_krw_100m !== undefined) {
    return `${formatNumber(metric.value_krw_100m)}억원`;
  }
  if (metric.value_won !== null && metric.value_won !== undefined) {
    return `${formatNumber(metric.value_won)}원`;
  }
  if (metric.value_pct !== null && metric.value_pct !== undefined) {
    return `${Number(metric.value_pct).toFixed(1)}%`;
  }
  if (metric.value !== null && metric.value !== undefined) {
    return `${formatNumber(metric.value)}${metric.unit || ""}`;
  }
  return "-";
}

function formatEstimateAxisValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  const numeric = Number(value);
  if (unit === "%") {
    return `${numeric.toFixed(1)}%`;
  }
  return `${formatNumber(Math.round(numeric * 10) / 10)}${unit}`;
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => {
    node.setAttribute(key, String(value));
  });
  return node;
}

function selectEstimateSeries(history, group) {
  const points = (history || []).filter((item) => {
    const value = estimateMetricValue(item, group);
    return item?.metric_group === group && value !== null && value !== undefined && Number.isFinite(Number(value));
  });
  if (group !== "earnings" || points.length <= 1) {
    return points.slice(-12);
  }

  const counts = points.reduce((acc, item) => {
    acc[item.metric] = (acc[item.metric] || 0) + 1;
    return acc;
  }, {});
  const preferredMetric =
    ["operating_profit", "net_profit", "eps"].find((metric) => counts[metric] >= 2) ||
    ["operating_profit", "net_profit", "eps"].find((metric) => counts[metric]) ||
    points[0]?.metric;
  return points.filter((item) => item.metric === preferredMetric).slice(-12);
}

function estimateValueTo100m(value, unit) {
  const numeric = Number(String(value || "").replace(/,/g, ""));
  if (!Number.isFinite(numeric)) {
    return null;
  }
  if (unit === "조원") {
    return numeric * 10000;
  }
  if (unit === "십억원") {
    return numeric * 10;
  }
  if (unit === "억원") {
    return numeric;
  }
  return null;
}

function parseEstimateMetricsFromText(text) {
  const source = String(text || "").replace(/\s+/g, " ").trim();
  if (!source) {
    return [];
  }
  const metrics = [];
  const profitLabels = {
    OP: ["operating_profit", "영업이익"],
    영업이익: ["operating_profit", "영업이익"],
    순이익: ["net_profit", "순이익"],
    지배순이익: ["net_profit", "지배순이익"],
    지배주주순이익: ["net_profit", "지배주주순이익"],
    EPS: ["eps", "EPS"],
  };
  const profitRe =
    /((?:(?:[12]\d{3}|[’']?\d{2})\s*(?:년|F|E)?|[1-4]Q\s*(?:\d{2,4})?|[1-4]분기)?)\s*(지배주주순이익|지배순이익|영업이익|순이익|EPS|OP)(?:은|는|이|가|을|를|:|의|으로)?\s*(?:약|전망|추정|예상|기록|컨센서스|시장 기대치|당사 추정치)?\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(조원|억원|십억원|원)/gi;
  let match;
  while ((match = profitRe.exec(source)) && metrics.length < 8) {
    const rawLabel = match[2].toUpperCase() === "OP" ? "OP" : match[2];
    const [metric, label] = profitLabels[rawLabel] || [rawLabel, rawLabel];
    const value = Number(match[3].replace(/,/g, ""));
    const unit = match[4];
    const item = {
      metric,
      metric_group: "earnings",
      label,
      period: match[1]?.trim() || null,
      value,
      unit,
    };
    const value100m = estimateValueTo100m(match[3], unit);
    if (value100m !== null) {
      item.value_krw_100m = Math.round(value100m * 100) / 100;
    }
    if (unit === "원") {
      item.value_won = value;
    }
    metrics.push(item);
  }

  const marginRe = /(OPM|영업이익률|영업마진|마진율|순이익률)(?:은|는|이|가|:|의)?\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*%/gi;
  while ((match = marginRe.exec(source)) && metrics.length < 12) {
    const value = Number(match[2].replace(/,/g, ""));
    metrics.push({
      metric: "operating_margin",
      metric_group: "margin",
      label: match[1].toUpperCase() === "OPM" ? "OPM" : match[1],
      period: null,
      value,
      unit: "%",
      value_pct: value,
    });
  }
  const seen = new Set();
  return metrics.filter((metric) => {
    const key = [metric.metric, metric.period || "", metric.value, metric.unit].join("|");
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function estimateHistoryFromDetail(detail) {
  const direct = detail.estimate_metric_history || detail.charts?.estimate_metric_history || [];
  if (direct.length) {
    return direct;
  }
  return (detail.timeline || []).flatMap((report) => {
    const metrics =
      report.estimate_metrics?.length
        ? report.estimate_metrics
        : parseEstimateMetricsFromText(
            [report.display_title, report.title, report.summary, report.excerpt, investmentMemoText(report.investment_memo)]
              .filter(Boolean)
              .join(" ")
          );
    return metrics.map((metric) => ({
      date: report.published_date,
      broker: report.broker,
      title: report.display_title || report.title,
      primary_url: getReportPrimaryUrl(report),
      ...metric,
    }));
  });
}

function renderEstimateLineChart(container, points, group, emptyText) {
  container.innerHTML = "";
  if (!points.length) {
    container.appendChild(el("div", "empty", emptyText));
    return;
  }

  const width = 360;
  const height = 168;
  const pad = { left: 48, right: 18, top: 16, bottom: 34 };
  const values = points.map((item) => Number(estimateMetricValue(item, group)));
  const unit = estimateMetricUnit(points[0], group);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min || 1;
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const coords = points.map((item, index) => {
    const value = Number(estimateMetricValue(item, group));
    const x = pad.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
    const y = pad.top + (1 - (value - min) / span) * plotHeight;
    return { item, value, x, y };
  });

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  [0, 0.5, 1].forEach((ratio) => {
    const y = pad.top + ratio * plotHeight;
    svg.appendChild(svgEl("line", { class: "estimate-line-grid", x1: pad.left, y1: y, x2: width - pad.right, y2: y }));
  });

  if (coords.length > 1) {
    const path = coords.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
    svg.appendChild(svgEl("path", { class: "estimate-line-path", d: path }));
  }

  coords.forEach((point) => {
    const dot = svgEl("circle", {
      class: "estimate-line-dot",
      cx: point.x.toFixed(1),
      cy: point.y.toFixed(1),
      r: 4.5,
    });
    const title = svgEl("title");
    title.textContent = `${point.item.date || "-"} ${point.item.broker || ""} ${point.item.label || ""} ${formatEstimateAxisValue(point.value, unit)}`;
    dot.appendChild(title);
    svg.appendChild(dot);
  });

  container.appendChild(svg);
  const axis = el("div", "estimate-line-axis");
  axis.appendChild(el("span", null, points[0]?.date || "-"));
  axis.appendChild(el("span", null, `${formatEstimateAxisValue(max, unit)} / ${formatEstimateAxisValue(min, unit)}`));
  axis.appendChild(el("span", null, points[points.length - 1]?.date || "-"));
  container.appendChild(axis);
  container.appendChild(
    el(
      "div",
      "estimate-line-meta",
      `${points[0]?.label || "추정치"} ${points.length}개 포인트 · ${points[points.length - 1]?.broker || "증권사"} 최신`
    )
  );
}

function getReportPrimaryUrl(report) {
  return report?.primary_url || report?.pdf_url || report?.detail_url || "#";
}

function getReportPrimaryLabel(report) {
  if (report?.primary_url_label === "PDF" || report?.pdf_url) {
    return "PDF 바로 열기";
  }
  return "원문 보기";
}

function decorateExternalLink(link, url) {
  link.href = url || "#";
  link.target = "_blank";
  link.rel = "noreferrer";
  return link;
}

function appendReportLink(actions, text, url) {
  if (!url) {
    return;
  }
  actions.appendChild(decorateExternalLink(el("a", null, text), url));
}

function getLinkHealth(report) {
  if (report?.link_health?.status) {
    return report.link_health;
  }
  if (report?.pdf_url) {
    return { status: "pdf_preferred" };
  }
  if (report?.detail_url) {
    return { status: "detail_only" };
  }
  return { status: "missing" };
}

function linkHealthLabel(report) {
  const status = getLinkHealth(report).status;
  if (status === "pdf_preferred") {
    return "PDF 우선";
  }
  if (status === "detail_only") {
    return "상세만";
  }
  if (status === "missing") {
    return "링크 없음";
  }
  return "";
}

function buildScoreBreakdown(report) {
  const parts = (report?.score_breakdown || [])
    .filter((item) => item && Number(item.value || 0) !== 0)
    .slice(0, 4);
  if (!parts.length) {
    return null;
  }

  const node = el("div", "score-breakdown");
  parts.forEach((item) => {
    const value = Number(item.value || 0);
    const sign = value > 0 ? "+" : "";
    const part = el(
      "span",
      `score-part ${value < 0 ? "score-part-penalty" : ""}`,
      `${item.label || "점수"} ${sign}${value.toFixed(2)}`
    );
    node.appendChild(part);
  });
  return node;
}

function buildSubjectDatum(report) {
  if (!report?.subject || !report?.subject_key) {
    return null;
  }
  const link = el("a", "datum");
  link.href = buildSubjectHref(report.subject_key);
  link.textContent = `종목 ${report.subject}`;
  return link;
}

function investmentMemoText(memo) {
  if (!memo || typeof memo !== "object") {
    return "";
  }
  return [
    memo.stance,
    memo.confidence,
    memo.action,
    ...(memo.thesis || []),
    ...(memo.catalysts || []),
    ...(memo.risks || []),
    ...(memo.numbers || []),
  ]
    .map(normalize)
    .join(" ");
}

function hasInvestmentMemo(report) {
  return Boolean(investmentMemoText(report?.investment_memo));
}

function memoStanceLabel(stance) {
  if (stance === "positive") {
    return "긍정";
  }
  if (stance === "neutral") {
    return "중립";
  }
  if (stance === "negative") {
    return "부정";
  }
  return "관찰";
}

function memoConfidenceLabel(confidence) {
  if (confidence === "high") {
    return "높음";
  }
  if (confidence === "medium") {
    return "보통";
  }
  return "낮음";
}

function buildMemoLine(label, values) {
  const cleaned = (values || []).filter(Boolean);
  if (!cleaned.length) {
    return null;
  }
  const row = el("div", "report-memo-line");
  row.appendChild(el("strong", null, label));
  row.appendChild(el("span", null, cleaned.slice(0, 3).join(" · ")));
  return row;
}

function buildInvestmentMemo(report) {
  const memo = report?.investment_memo || {};
  if (!hasInvestmentMemo(report)) {
    return null;
  }

  const node = el("div", "report-memo");
  node.appendChild(el("div", "report-memo-title", "LLM 투자 메모"));

  const meta = el("div", "report-kicker");
  meta.appendChild(buildBadge(`톤 ${memoStanceLabel(memo.stance)}`, "accent"));
  meta.appendChild(buildBadge(`신뢰도 ${memoConfidenceLabel(memo.confidence)}`));
  node.appendChild(meta);

  if (memo.action) {
    node.appendChild(el("p", "report-memo-action", memo.action));
  }

  [
    ["핵심", memo.thesis],
    ["촉매", memo.catalysts],
    ["리스크", memo.risks],
    ["숫자", memo.numbers],
  ].forEach(([label, values]) => {
    const line = buildMemoLine(label, values);
    if (line) {
      node.appendChild(line);
    }
  });

  return node;
}

function buildReportCard(report, featured = false) {
  const article = el("article", "report-card");
  const kicker = el("div", "report-kicker");

  if (featured) {
    kicker.appendChild(buildBadge("우선 검토 후보", "signal"));
  }
  if (report.is_priority_match) {
    kicker.appendChild(buildBadge("관심 일치", "accent"));
  }
  if (hasChangeSignal(report)) {
    kicker.appendChild(buildBadge("변화 감지", "rose"));
  }
  if (report.estimate_signal_types?.includes("earnings_estimate_up")) {
    kicker.appendChild(buildBadge("이익 추정↑", "accent"));
  }
  if (report.estimate_signal_types?.includes("margin_estimate_up")) {
    kicker.appendChild(buildBadge("마진 개선", "signal"));
  }
  if (report.has_pdf_text) {
    kicker.appendChild(buildBadge("PDF 본문 확보", "sky"));
  }
  const linkHealth = getLinkHealth(report);
  const linkLabel = linkHealthLabel(report);
  if (linkLabel) {
    kicker.appendChild(buildBadge(linkLabel, linkHealth.status === "pdf_preferred" ? "sky" : "default"));
  }
  if (hasInvestmentMemo(report)) {
    kicker.appendChild(buildBadge("LLM 투자 메모", "accent"));
  }

  kicker.appendChild(buildBadge(report.category_label || "카테고리 없음"));
  kicker.appendChild(buildBadge(report.broker || "증권사 없음"));
  article.appendChild(kicker);

  const title = el("h3", "report-title");
  const titleLink = el("a");
  decorateExternalLink(titleLink, getReportPrimaryUrl(report));
  titleLink.textContent = report.display_title || report.title || "제목 없음";
  title.appendChild(titleLink);
  article.appendChild(title);

  article.appendChild(el("p", "report-summary", compactText(report.summary || report.excerpt, featured ? 220 : 180)));
  const memo = buildInvestmentMemo(report);
  if (memo && featured) {
    article.appendChild(memo);
  }

  const data = el("div", "report-data");
  data.appendChild(buildDatum("우선순위", Number(report.score || 0).toFixed(2)));
  const subjectDatum = buildSubjectDatum(report);
  if (subjectDatum) {
    data.appendChild(subjectDatum);
  } else if (report.subject) {
    data.appendChild(buildDatum("주제", report.subject));
  }
  if (report.target_price) {
    data.appendChild(buildDatum("목표가", report.target_price));
  }
  (report.estimate_metrics || []).slice(0, 2).forEach((metric) => {
    data.appendChild(buildDatum(metric.label || "추정치", formatEstimateMetric(metric)));
  });
  if (report.opinion) {
    data.appendChild(buildDatum("의견", report.opinion));
  }
  if (report.analyst) {
    data.appendChild(buildDatum("애널리스트", report.analyst));
  }
  if (report.views) {
    data.appendChild(buildDatum("조회수", formatNumber(report.views)));
  }
  article.appendChild(data);
  const scoreBreakdown = buildScoreBreakdown(report);
  if (scoreBreakdown) {
    article.appendChild(scoreBreakdown);
  }

  const footer = el("div", "report-footer");
  const reasons = el("div", "report-reasons");
  const reasonParts = [];
  if (report.score_reasons && report.score_reasons.length) {
    reasonParts.push(report.score_reasons.join(" · "));
  }
  if (report.change_reasons && report.change_reasons.length) {
    reasonParts.push(`변화: ${report.change_reasons.join(" · ")}`);
  }
  if (report.priority_subject_matches?.length || report.priority_keyword_matches?.length) {
    reasonParts.push(
      `일치: ${[...(report.priority_subject_matches || []), ...(report.priority_keyword_matches || [])].join(", ")}`
    );
  }
  reasons.textContent = reasonParts.length
    ? `선정 근거: ${reasonParts.join(" / ")}`
    : "선정 근거 정보 없음";
  footer.appendChild(reasons);

  const actions = el("div", "report-actions");
  appendReportLink(actions, getReportPrimaryLabel(report), getReportPrimaryUrl(report));
  if (report.pdf_url && report.detail_url) {
    appendReportLink(actions, "상세 페이지", report.detail_url);
  }

  if (report.subject_key && !isSubjectMode()) {
    const subjectLink = el("a");
    subjectLink.href = buildSubjectHref(report.subject_key);
    subjectLink.textContent = "종목 히스토리";
    actions.appendChild(subjectLink);
  }

  footer.appendChild(actions);
  article.appendChild(footer);

  return article;
}

function formatTargetChange(report) {
  if (!report?.target_price_change) {
    return null;
  }

  const direction = report.target_price_change === "up" ? "상향" : "하향";
  const pct =
    report.target_price_change_pct === null || report.target_price_change_pct === undefined
      ? ""
      : ` (${Number(report.target_price_change_pct).toFixed(1)}%)`;
  return `목표가 ${direction}: ${report.previous_target_price || "-"} → ${report.target_price || "-"}${pct}`;
}

function buildChangeCard(report) {
  const article = el("article", "report-card");
  const kicker = el("div", "report-kicker");
  kicker.appendChild(buildBadge("변화 감지", "rose"));
  kicker.appendChild(buildBadge(report.broker || "증권사 없음"));
  if (report.published_date) {
    kicker.appendChild(buildBadge(report.published_date));
  }
  article.appendChild(kicker);

  const title = el("h3", "report-title");
  const titleLink = el("a");
  decorateExternalLink(titleLink, getReportPrimaryUrl(report));
  titleLink.textContent = report.display_title || report.title || "제목 없음";
  title.appendChild(titleLink);
  article.appendChild(title);

  const reasons = report.change_reasons?.length
    ? report.change_reasons.join(" · ")
    : "비교는 가능하지만 세부 변화 정보가 비어 있습니다.";
  article.appendChild(el("p", "report-summary", reasons));

  const data = el("div", "report-data");
  const subjectDatum = buildSubjectDatum(report);
  if (subjectDatum) {
    data.appendChild(subjectDatum);
  }
  const targetChange = formatTargetChange(report);
  if (targetChange) {
    data.appendChild(buildDatum("변화", targetChange));
  }
  (report.estimate_metrics || []).slice(0, 2).forEach((metric) => {
    data.appendChild(buildDatum(metric.label || "추정치", formatEstimateMetric(metric)));
  });
  if (report.opinion_changed) {
    data.appendChild(buildDatum("의견", `${report.previous_opinion || "-"} → ${report.opinion || "-"}`));
  }
  if (report.analyst_changed) {
    data.appendChild(buildDatum("애널리스트", `${report.previous_analyst || "-"} → ${report.analyst || "-"}`));
  }
  if (report.previous_report_date) {
    data.appendChild(buildDatum("비교 기준", report.previous_report_date));
  }
  article.appendChild(data);

  const footer = el("div", "report-footer");
  footer.appendChild(el("div", "report-reasons", compactText(report.summary || report.excerpt, 140)));
  const actions = el("div", "report-actions");
  appendReportLink(actions, getReportPrimaryLabel(report), getReportPrimaryUrl(report));
  if (report.pdf_url && report.detail_url) {
    appendReportLink(actions, "상세 페이지", report.detail_url);
  }
  if (report.subject_key && !isSubjectMode()) {
    const subjectLink = el("a");
    subjectLink.href = buildSubjectHref(report.subject_key);
    subjectLink.textContent = "종목 상세";
    actions.appendChild(subjectLink);
  }
  footer.appendChild(actions);
  article.appendChild(footer);

  return article;
}

function buildRankingCard(label, reports) {
  const card = el("section", "ranking-card");
  card.appendChild(el("h3", null, label || "랭킹"));
  const list = el("div", "ranking-list");

  reports.slice(0, 5).forEach((report, index) => {
    const item = el("div", "ranking-item");
    const strong = el("strong");
    const link = el("a");
    decorateExternalLink(link, getReportPrimaryUrl(report));
    link.textContent = `${index + 1}. ${report.display_title || report.title || "제목 없음"}`;
    strong.appendChild(link);
    item.appendChild(strong);
    item.appendChild(
      el(
        "small",
        null,
        `${report.broker || "증권사 없음"} · 우선순위 ${Number(report.score || 0).toFixed(2)}${
          report.views ? ` · 조회수 ${formatNumber(report.views)}` : ""
        }`
      )
    );
    list.appendChild(item);
  });

  card.appendChild(list);
  return card;
}

function renderLoadingState() {
  document.getElementById("heroSummary").textContent = "데이터를 불러오는 중입니다.";
  document.getElementById("editorialNote").textContent = "편집 메모를 불러오는 중입니다.";
  document.getElementById("mustReadList").innerHTML = '<div class="loading">우선 검토 후보를 정리하는 중입니다.</div>';
  document.getElementById("reportList").innerHTML = '<div class="loading">리포트 목록을 불러오는 중입니다.</div>';
  document.getElementById("changeList").innerHTML = '<div class="loading">변화 감지 정보를 준비하는 중입니다.</div>';
  document.getElementById("rankingGrid").innerHTML = '<div class="loading">랭킹을 계산하는 중입니다.</div>';
  document.getElementById("activeFilterBar").innerHTML = '<span class="hint-chip">필터 상태를 준비하는 중입니다.</span>';
}

function renderHintBar(totalVisible, totalReports) {
  const bar = document.getElementById("activeFilterBar");
  bar.innerHTML = "";

  const hints = [`표시 ${formatNumber(totalVisible)} / 전체 ${formatNumber(totalReports)}건`];
  if (state.subjectDetail?.subject_name) {
    hints.push(`종목: ${state.subjectDetail.subject_name}`);
  }
  if (state.query) {
    hints.push(`검색: "${state.query}"`);
  }
  if (state.selectedCategory !== "all") {
    const selectedOption = document.querySelector(`#categorySelect option[value="${state.selectedCategory}"]`);
    hints.push(`카테고리: ${selectedOption?.textContent || state.selectedCategory}`);
  }
  if (state.selectedBroker !== "all") {
    hints.push(`증권사: ${state.selectedBroker}`);
  }
  if (state.priorityOnlyView) {
    hints.push("관심 일치만");
  }
  if (state.changesOnlyView) {
    hints.push("변화 감지만");
  }
  hints.push(`정렬: ${document.getElementById("sortSelect").selectedOptions[0]?.textContent || ""}`);

  hints.forEach((hint) => {
    bar.appendChild(el("span", "hint-chip", hint));
  });
}

function renderHero(digest) {
  const editorial = digest.editorial_note || "오늘의 편집 메모가 없습니다.";
  const collection = digest.collection_note ? `${digest.collection_note} ` : "";
  document.getElementById("heroSummary").classList.remove("loading");
  document.getElementById("heroSummary").textContent = `${collection}${editorial}`.trim();
  document.getElementById("heroGeneratedAt").textContent = formatShortDateTime(digest.generated_at);
  document.getElementById("heroDateMeta").textContent = `${formatDateLabel(digest.requested_date || digest.date)} 기준`;
  document.getElementById("heroMustReadCount").textContent = formatNumber((digest.must_read || []).length);
  document.getElementById("heroMustReadMeta").textContent = `전체 ${formatNumber(digest.stats?.total_reports || 0)}건 중 우선 확인할 후보`;
  document.getElementById("heroChangeCount").textContent = formatNumber(digest.change_summary?.changed_reports || 0);

  const changeSummary = digest.change_summary || {};
  document.getElementById("heroChangeMeta").textContent = changeSummary.available
    ? `이익↑ ${formatNumber(changeSummary.earnings_estimate_up || 0)} · 마진↑ ${formatNumber(
        changeSummary.margin_estimate_up || 0
      )} · 목표가↑ ${formatNumber(changeSummary.target_price_up || 0)}`
    : "과거 아카이브가 충분하지 않아 변화 비교가 제한됩니다.";
}

function renderNotes(digest) {
  const editorial = document.getElementById("editorialNote");
  editorial.classList.remove("loading");
  editorial.textContent = digest.editorial_note || "편집 메모가 없습니다.";

  const collection = document.getElementById("collectionNote");
  collection.textContent = digest.collection_note || "수집 메모는 비어 있습니다.";

  const priority = digest.priority_filters || { enabled: false };
  const priorityCopy = document.getElementById("priorityCopy");
  const priorityFilterChips = document.getElementById("priorityFilterChips");
  const keywordChips = document.getElementById("keywordChips");

  priorityFilterChips.innerHTML = "";
  keywordChips.innerHTML = "";

  if (!priority.enabled) {
    priorityCopy.textContent = "관심 종목/키워드 필터가 아직 설정되지 않았습니다.";
    document.getElementById("priorityOnlyToggle").checked = false;
    document.getElementById("priorityOnlyToggle").disabled = true;
    state.priorityOnlyView = false;
  } else {
    document.getElementById("priorityOnlyToggle").disabled = false;
    priorityCopy.textContent = `관심 필터 일치 리포트 ${formatNumber(priority.matched_reports || 0)}건, 우선 검토 후보 ${formatNumber(
      priority.matched_must_read || 0
    )}건입니다.`;

    [...(priority.subjects || []), ...(priority.keywords || [])].forEach((item) => {
      const chip = el("span", "chip");
      chip.appendChild(el("strong", null, item));
      priorityFilterChips.appendChild(chip);
    });
  }

  (digest.keywords || []).forEach((keyword) => {
    keywordChips.appendChild(el("span", "chip", `# ${keyword}`));
  });

  if (!(digest.keywords || []).length) {
    keywordChips.appendChild(el("span", "chip", "키워드 없음"));
  }
}

function renderCountBreakdown(items, containerId, keyName) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";

  if (!items || !items.length) {
    container.appendChild(el("div", "empty", "집계 정보가 없습니다."));
    return;
  }

  const max = Math.max(...items.map((item) => Number(item.count || 0)), 1);
  items.slice(0, 6).forEach((item) => {
    const row = el("div", "count-row");
    const head = el("div", "count-row-head");
    head.appendChild(el("span", null, item[keyName] || "-"));
    head.appendChild(el("strong", null, formatNumber(item.count || 0)));
    row.appendChild(head);

    const bar = el("div", "count-bar");
    const fill = el("div", "count-bar-fill");
    fill.style.width = `${Math.max((Number(item.count || 0) / max) * 100, 8)}%`;
    bar.appendChild(fill);
    row.appendChild(bar);
    container.appendChild(row);
  });
}

function renderSourceHealth(digest) {
  const container = document.getElementById("sourceHealthList");
  const alertContainer = document.getElementById("sourceAlertList");
  const meta = document.getElementById("sourceHealthMeta");
  const health = digest.stats?.collector_health || [];
  const summary = digest.stats?.collector_health_summary || {};
  const alerts = digest.stats?.collector_alerts || [];
  container.innerHTML = "";
  alertContainer.innerHTML = "";

  if (!health.length) {
    meta.textContent = "이번 데이터에는 소스 상태 정보가 없습니다.";
    container.appendChild(el("div", "empty", "소스 헬스체크 정보가 아직 저장되지 않았습니다."));
    return;
  }

  meta.textContent =
    `정상 ${formatNumber(summary.ok_sources || 0)}개 · ` +
    `무출력 ${formatNumber(summary.empty_sources || 0)}개 · ` +
    `실패 ${formatNumber(summary.failed_sources || 0)}개 · ` +
    `알림 ${formatNumber(alerts.length)}건`;

  alerts.slice(0, 5).forEach((item) => {
    const row = el("div", "source-alert-item");
    const title = el("div", "source-alert-title");
    title.appendChild(el("span", null, alertSeverityLabel(item.severity)));
    title.appendChild(el("strong", null, item.title || item.label || "-"));
    row.appendChild(title);
    row.appendChild(el("div", "source-alert-message", compactText(item.message, 120)));
    alertContainer.appendChild(row);
  });

  health.forEach((item) => {
    const row = el("div", "source-health-item");
    const main = el("div", "source-health-main");
    const title = el("div", "source-health-title");
    const dot = el("span", `status-dot status-${item.status || "unknown"}`);
    title.appendChild(dot);
    title.appendChild(el("span", null, item.label || item.source || "-"));
    main.appendChild(title);

    const detailParts = [
      sourceStatusLabel(item.status),
      item.collector || "",
      formatDuration(item.duration_seconds),
    ].filter(Boolean);
    if (item.message && item.status !== "ok") {
      detailParts.push(compactText(item.message, 90));
    }
    main.appendChild(el("div", "source-health-detail", detailParts.join(" · ")));

    row.appendChild(main);
    row.appendChild(el("strong", "source-health-count", `${formatNumber(item.report_count || 0)}건`));
    container.appendChild(row);
  });
}

function renderStats(digest) {
  const statsGrid = document.getElementById("statsGrid");
  statsGrid.innerHTML = "";

  const categories = digest.stats?.categories || [];
  const brokers = digest.stats?.brokers || [];
  const changeSummary = digest.change_summary || {};
  const collectorSummary = digest.stats?.collector_health_summary || {};
  const collectorAlertSummary = digest.stats?.collector_alert_summary || {};
  let linkHealth = digest.stats?.link_health || {};
  if (!linkHealth.total) {
    linkHealth = (digest.reports || []).reduce(
      (counts, report) => {
        const status = getLinkHealth(report).status;
        counts[status] = (counts[status] || 0) + 1;
        counts.total += 1;
        return counts;
      },
      { pdf_preferred: 0, detail_only: 0, missing: 0, total: 0 }
    );
  }
  const performance = digest.stats?.selection_performance || {};
  const completedPerformance = Object.values(performance.completed_by_horizon || {}).reduce(
    (sum, value) => sum + Number(value || 0),
    0
  );
  const pricedPerformance = Object.values(performance.priced_by_horizon || {}).reduce(
    (sum, value) => sum + Number(value || 0),
    0
  );
  const averageReturns = performance.average_price_return_by_horizon || {};
  const headlineReturn =
    averageReturns["7d"] ?? averageReturns["1d"] ?? averageReturns["30d"];
  const diversity = digest.stats?.must_read_diversity || {};

  const cards = [
    {
      label: "총 리포트",
      value: formatNumber(digest.stats?.total_reports || 0),
      body: "해당 날짜에 수집된 전체 건수",
    },
    {
      label: "관심 일치",
      value: formatNumber(digest.stats?.priority_match_reports || 0),
      body: "관심 종목/키워드와 겹친 리포트",
    },
    {
      label: "PDF 본문 확보",
      value: formatNumber(digest.stats?.pdf_text_reports || 0),
      body: "PDF에서 텍스트까지 읽은 리포트",
    },
    {
      label: "PDF 우선 링크",
      value: formatNumber(linkHealth.pdf_preferred || 0),
      body: `상세만 ${formatNumber(linkHealth.detail_only || 0)} · 누락 ${formatNumber(linkHealth.missing || 0)}`,
    },
    {
      label: "LLM 투자 메모",
      value: formatNumber(digest.stats?.llm_investment_memo_reports || 0),
      body: "구조화된 투자 메모가 붙은 리포트",
    },
    {
      label: "변화 감지",
      value: formatNumber(changeSummary.changed_reports || 0),
      body: `이익↑ ${formatNumber(changeSummary.earnings_estimate_up || 0)} · 마진↑ ${formatNumber(
        changeSummary.margin_estimate_up || 0
      )} · 목표가↑ ${formatNumber(changeSummary.target_price_up || 0)}`,
    },
    {
      label: "추정치 숫자",
      value: formatNumber(digest.stats?.estimate_metric_reports || 0),
      body: "영업이익, 순이익, EPS, OPM을 읽은 리포트",
    },
    {
      label: "최다 카테고리",
      value: categories[0]?.label || "-",
      body: `${formatNumber(categories[0]?.count || 0)}건`,
    },
    {
      label: "활동 증권사",
      value: brokers[0]?.name || "-",
      body: `${formatNumber(brokers[0]?.count || 0)}건`,
    },
    {
      label: "소스 상태",
      value: `${formatNumber(collectorSummary.failed_sources || 0)} 실패`,
      body: `정상 ${formatNumber(collectorSummary.ok_sources || 0)} · 무출력 ${formatNumber(
        collectorSummary.empty_sources || 0
      )}`,
    },
    {
      label: "운영 알림",
      value: `${formatNumber(collectorAlertSummary.total_alerts || 0)}건`,
      body: `긴급 ${formatNumber(collectorAlertSummary.critical_alerts || 0)} · 주의 ${formatNumber(
        collectorAlertSummary.warning_alerts || 0
      )}`,
    },
    {
      label: "성과 추적",
      value: `${formatNumber(completedPerformance)} 완료`,
      body: `시세 ${formatNumber(pricedPerformance)}건${
        headlineReturn !== undefined ? ` · 평균 ${Number(headlineReturn).toFixed(2)}%` : ""
      } · 추적 후보 ${formatNumber(performance.tracked_selections || 0)}건`,
    },
    {
      label: "후보 다양성",
      value: `${formatNumber(diversity.unique_subject_or_title || 0)}개 주제`,
      body: `증권사 ${formatNumber(diversity.unique_brokers || 0)}곳 · 최대 ${formatNumber(
        diversity.max_broker_count || 0
      )}건`,
    },
  ];

  cards.forEach((card) => {
    const node = el("article", "stat-card");
    node.appendChild(el("span", null, card.label));
    node.appendChild(el("strong", null, card.value));
    node.appendChild(el("small", null, card.body));
    statsGrid.appendChild(node);
  });

  renderCountBreakdown(categories, "categoryBreakdown", "label");
  renderCountBreakdown(brokers, "brokerBreakdown", "name");
  renderSourceHealth(digest);
}

function renderSignalSummary(digest, filteredChanges) {
  const container = document.getElementById("signalSummary");
  const meta = document.getElementById("changeMeta");
  const summary = digest.change_summary || {};
  container.innerHTML = "";

  if (!summary.available) {
    meta.textContent = "비교 가능한 과거 아카이브가 부족합니다.";
    container.appendChild(el("div", "empty", "이 날짜는 히스토리 부족으로 변화 요약이 제한됩니다."));
    return;
  }

  meta.textContent = `현재 필터 기준 ${formatNumber(filteredChanges.length)}건 표시`;
  const stats = [
    { label: "변화 감지", value: summary.changed_reports || 0 },
    { label: "추정치 상향", value: summary.estimate_revision_up || 0 },
    { label: "추정치 하향", value: summary.estimate_revision_down || 0 },
    { label: "이익 추정 상향", value: summary.earnings_estimate_up || 0 },
    { label: "마진 개선", value: summary.margin_estimate_up || 0 },
    { label: "목표가 상향", value: summary.target_price_up || 0 },
    { label: "의견 변경", value: summary.opinion_changed || 0 },
  ];

  stats.forEach((stat) => {
    const node = el("div", "signal-stat");
    node.appendChild(el("span", null, stat.label));
    node.appendChild(el("strong", null, formatNumber(stat.value)));
    container.appendChild(node);
  });
}

function renderChanges(digest) {
  const container = document.getElementById("changeList");
  container.innerHTML = "";

  const changes = sortReports((digest.changes || []).filter(reportMatchesFilters));
  renderSignalSummary(digest, changes);

  if (!digest.change_summary?.available) {
    container.appendChild(el("div", "empty", "변화 감지 비교가 가능한 시점부터 카드가 채워집니다."));
    return;
  }

  if (!changes.length) {
    container.appendChild(el("div", "empty", "현재 필터 조건에 맞는 변화 감지 리포트가 없습니다."));
    return;
  }

  changes.forEach((report) => {
    container.appendChild(buildChangeCard(report));
  });
}

function renderRankings(digest) {
  const container = document.getElementById("rankingGrid");
  container.innerHTML = "";

  const groups = Object.values(digest.rankings || {}).map((group) => ({
    label: group.label,
    reports: sortReports((group.reports || []).filter(reportMatchesFilters)),
  }));

  const nonEmpty = groups.filter((group) => group.reports.length);
  if (!nonEmpty.length) {
    container.appendChild(el("div", "empty", "현재 필터 조건에 맞는 랭킹이 없습니다."));
    return;
  }

  nonEmpty.forEach((group) => {
    container.appendChild(buildRankingCard(group.label, group.reports));
  });
}

function renderMustRead(digest) {
  const container = document.getElementById("mustReadList");
  const meta = document.getElementById("mustReadMeta");
  container.innerHTML = "";

  const mustRead = sortReports((digest.must_read || []).filter(reportMatchesFilters));
  meta.textContent = `현재 필터 기준 ${formatNumber(mustRead.length)}건`;

  if (!mustRead.length) {
    container.appendChild(el("div", "empty", "현재 조건에서는 우선 검토 후보가 없습니다."));
    return;
  }

  mustRead.forEach((report) => {
    container.appendChild(buildReportCard(report, true));
  });
}

function renderReports() {
  const container = document.getElementById("reportList");
  const meta = document.getElementById("reportMeta");
  container.innerHTML = "";

  const reports = getFilteredReports();
  meta.textContent = `현재 필터 기준 ${formatNumber(reports.length)}건`;
  renderHintBar(reports.length, state.digest?.stats?.total_reports || 0);

  if (!reports.length) {
    container.appendChild(el("div", "empty", "현재 필터 조건에 맞는 리포트가 없습니다."));
    return;
  }

  reports.forEach((report) => {
    container.appendChild(buildReportCard(report));
  });
}

function populateCategoryOptions(digest) {
  const select = document.getElementById("categorySelect");
  const previousValue = state.selectedCategory;
  select.innerHTML = "";

  const optionAll = el("option");
  optionAll.value = "all";
  optionAll.textContent = "전체 카테고리";
  select.appendChild(optionAll);

  const categories = Array.from(
    new Map(
      (digest.reports || [])
        .filter((report) => report.category)
        .map((report) => [report.category, report.category_label || report.category])
    ).entries()
  ).sort((left, right) => left[1].localeCompare(right[1], "ko"));

  categories.forEach(([value, label]) => {
    const option = el("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });

  state.selectedCategory = categories.some(([value]) => value === previousValue) ? previousValue : "all";
  select.value = state.selectedCategory;
}

function populateBrokerOptions(digest) {
  const select = document.getElementById("brokerSelect");
  if (!select) {
    return;
  }
  const previousValue = state.selectedBroker;
  select.innerHTML = "";

  const optionAll = el("option");
  optionAll.value = "all";
  optionAll.textContent = "전체 증권사";
  select.appendChild(optionAll);

  const counts = new Map();
  (digest.reports || []).forEach((report) => {
    if (report.broker) {
      counts.set(report.broker, (counts.get(report.broker) || 0) + 1);
    }
  });

  const brokers = [...counts.entries()].sort((left, right) => {
    const gap = right[1] - left[1];
    return gap !== 0 ? gap : left[0].localeCompare(right[0], "ko");
  });

  brokers.forEach(([broker, count]) => {
    const option = el("option");
    option.value = broker;
    option.textContent = `${broker} · ${formatNumber(count)}건`;
    select.appendChild(option);
  });

  state.selectedBroker = counts.has(previousValue) ? previousValue : "all";
  select.value = state.selectedBroker;
}

function setViewMode(mode) {
  document.getElementById("dailyView").hidden = mode !== "daily";
  document.getElementById("subjectView").hidden = mode !== "subject";
  document.getElementById("subjectBackLink").href = buildDailyHref(state.selectedDate);
}

function renderSubjectHero(detail) {
  const summary = detail.change_summary || {};
  document.getElementById("heroSummary").classList.remove("loading");
  document.getElementById("heroSummary").textContent =
    `${detail.subject_name} 관련 리포트 ${formatNumber(detail.report_count || 0)}건을 누적 추적 중입니다. 최근 업데이트는 ${
      detail.latest_report_date || "-"
    }이며, 변화 감지 ${formatNumber(summary.changed_reports || 0)}건을 함께 확인할 수 있습니다.`;
  document.getElementById("heroGeneratedAt").textContent = detail.latest_report_date || "-";
  document.getElementById("heroDateMeta").textContent = `${detail.subject_name || "종목"} 히스토리`;
  document.getElementById("heroMustReadCount").textContent = formatNumber(detail.report_count || 0);
  document.getElementById("heroMustReadMeta").textContent = `활동 증권사 ${formatNumber(
    detail.active_broker_count || 0
  )}곳`;
  document.getElementById("heroChangeCount").textContent = formatNumber(summary.changed_reports || 0);
  document.getElementById("heroChangeMeta").textContent = `이익↑ ${formatNumber(
    summary.earnings_estimate_up || 0
  )} · 마진↑ ${formatNumber(summary.margin_estimate_up || 0)} · 목표가↑ ${formatNumber(
    summary.target_price_up || 0
  )}`;
}

function renderSubjectChangeSummary(detail) {
  const container = document.getElementById("subjectChangeSummary");
  container.innerHTML = "";
  const summary = detail.change_summary || {};
  const cards = [
    { label: "변화 감지", value: summary.changed_reports || 0 },
    { label: "이익 추정 상향", value: summary.earnings_estimate_up || 0 },
    { label: "마진 개선", value: summary.margin_estimate_up || 0 },
    { label: "목표가 상향", value: summary.target_price_up || 0 },
    { label: "의견 변경", value: summary.opinion_changed || 0 },
    { label: "신규 커버리지", value: summary.coverage_initiated || 0 },
  ];

  cards.forEach((card) => {
    const node = el("div", "signal-stat");
    node.appendChild(el("span", null, card.label));
    node.appendChild(el("strong", null, formatNumber(card.value)));
    container.appendChild(node);
  });
}

function renderSubjectCharts(detail) {
  const profitContainer = document.getElementById("subjectProfitEstimateChart");
  const marginContainer = document.getElementById("subjectMarginEstimateChart");
  const opinionContainer = document.getElementById("subjectOpinionChart");
  const timelineContainer = document.getElementById("subjectBrokerTimelineChart");
  profitContainer.innerHTML = "";
  marginContainer.innerHTML = "";
  opinionContainer.innerHTML = "";
  timelineContainer.innerHTML = "";

  const estimateHistory = estimateHistoryFromDetail(detail);
  renderEstimateLineChart(
    profitContainer,
    selectEstimateSeries(estimateHistory, "earnings"),
    "earnings",
    "아직 이익 추정치 숫자를 찾지 못했습니다."
  );
  renderEstimateLineChart(
    marginContainer,
    selectEstimateSeries(estimateHistory, "margin"),
    "margin",
    "아직 마진율 추정치 숫자를 찾지 못했습니다."
  );

  const opinions = detail.opinion_distribution || detail.charts?.opinion_distribution || detail.opinion_summary || [];
  if (!opinions.length) {
    opinionContainer.appendChild(el("div", "empty", "의견 정보가 아직 없습니다."));
  } else {
    const maxCount = Math.max(...opinions.map((item) => Number(item.count || 0)), 1);
    opinions.forEach((item) => {
      const row = el("div", "opinion-row");
      row.appendChild(el("span", null, item.label || "-"));
      const track = el("div", "opinion-bar-track");
      const fill = el("div", "opinion-bar-fill");
      fill.style.width = `${Math.max((Number(item.count || 0) / maxCount) * 100, 8)}%`;
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("strong", null, formatNumber(item.count || 0)));
      opinionContainer.appendChild(row);
    });
  }

  const timeline = (detail.broker_timeline || detail.charts?.broker_timeline || []).slice(-8).reverse();
  if (!timeline.length) {
    timelineContainer.appendChild(el("div", "empty", "최근 2주 브로커 업데이트가 없습니다."));
  } else {
    timeline.forEach((item) => {
      const row = el("div", "broker-timeline-item");
      row.appendChild(el("span", null, item.date || "-"));
      const body = el("div");
      body.appendChild(el("strong", null, item.broker || "-"));
      body.appendChild(el("div", null, compactText(item.title || "-", 90)));
      row.appendChild(body);
      timelineContainer.appendChild(row);
    });
  }
}

function renderSubjectView() {
  const detail = state.subjectDetail;
  if (!detail) {
    return;
  }

  setViewMode("subject");
  renderSubjectHero(detail);
  renderSubjectCharts(detail);

  document.getElementById("subjectTitle").textContent = detail.subject_name || "종목 상세";
  document.getElementById("subjectMeta").textContent = `최근 업데이트 ${detail.latest_report_date || "-"} · 누적 ${
    formatNumber(detail.report_count || 0)
  }건 · 활동 증권사 ${formatNumber(detail.active_broker_count || 0)}곳`;
  document.getElementById("subjectSummary").textContent =
    `${detail.subject_name} 관련 리포트의 이익 추정, 마진율, 브로커별 최신 시각을 한 화면에서 볼 수 있습니다. 변화 신호는 우측 패널에서 우선 확인하세요.`;
  document.getElementById("subjectBackLink").href = buildDailyHref(state.selectedDate);

  const stats = document.getElementById("subjectStats");
  stats.innerHTML = "";
  const targetSummary = detail.target_summary || {};
  const changeSummary = detail.change_summary || {};
  const estimateHistory = estimateHistoryFromDetail(detail);
  const profitSeries = selectEstimateSeries(estimateHistory, "earnings");
  const marginSeries = selectEstimateSeries(estimateHistory, "margin");
  [
    { label: "누적 리포트", value: formatNumber(detail.report_count || 0), body: "아카이브 전체 기준" },
    {
      label: "활동 증권사",
      value: formatNumber(detail.active_broker_count || 0),
      body: "같은 종목을 다룬 브로커 수",
    },
    {
      label: "변화 감지",
      value: formatNumber(detail.change_summary?.changed_reports || 0),
      body: `이익↑ ${formatNumber(changeSummary.earnings_estimate_up || 0)} · 마진↑ ${formatNumber(
        changeSummary.margin_estimate_up || 0
      )} · 목표가↑ ${formatNumber(changeSummary.target_price_up || 0)}`,
    },
    {
      label: "추정치 포인트",
      value: formatNumber(estimateHistory.length || 0),
      body: `이익 ${formatNumber(profitSeries.length)} · 마진 ${formatNumber(marginSeries.length)}`,
    },
  ].forEach((card) => {
    const node = el("article", "stat-card");
    node.appendChild(el("span", null, card.label));
    node.appendChild(el("strong", null, card.value));
    node.appendChild(el("small", null, card.body));
    stats.appendChild(node);
  });

  const targetChips = document.getElementById("subjectTargetChips");
  targetChips.innerHTML = "";
  [
    `이익 추정 상향 ${formatNumber(changeSummary.earnings_estimate_up || 0)}건`,
    `마진 개선 ${formatNumber(changeSummary.margin_estimate_up || 0)}건`,
    `목표가 평균 ${formatTargetValue(targetSummary.avg)}`,
    `최신 목표가 ${formatNumber(targetSummary.count || 0)}건`,
  ].forEach((label) => {
    targetChips.appendChild(el("span", "chip", label));
  });

  const brokerLatest = sortReports((detail.latest_by_broker || []).filter(reportMatchesFilters));
  document.getElementById("subjectBrokerMeta").textContent = `현재 필터 기준 ${formatNumber(
    brokerLatest.length
  )}건`;
  const brokerContainer = document.getElementById("subjectBrokerLatest");
  brokerContainer.innerHTML = "";
  if (!brokerLatest.length) {
    brokerContainer.appendChild(el("div", "empty", "현재 필터 조건에 맞는 최신 브로커 리포트가 없습니다."));
  } else {
    brokerLatest.forEach((report) => {
      brokerContainer.appendChild(buildReportCard(report));
    });
  }

  const recentChanges = sortReports((detail.recent_changes || []).filter(reportMatchesFilters));
  document.getElementById("subjectChangeMeta").textContent = `현재 필터 기준 ${formatNumber(
    recentChanges.length
  )}건`;
  renderSubjectChangeSummary(detail);
  const changeContainer = document.getElementById("subjectRecentChanges");
  changeContainer.innerHTML = "";
  if (!recentChanges.length) {
    changeContainer.appendChild(el("div", "empty", "이 종목에는 현재 필터 기준 변화 감지가 없습니다."));
  } else {
    recentChanges.forEach((report) => {
      changeContainer.appendChild(buildChangeCard(report));
    });
  }

  const opinionChips = document.getElementById("subjectOpinionChips");
  opinionChips.innerHTML = "";
  if ((detail.opinion_summary || []).length) {
    detail.opinion_summary.forEach((item) => {
      opinionChips.appendChild(el("span", "chip", `${item.label} ${formatNumber(item.count)}건`));
    });
  } else {
    opinionChips.appendChild(el("span", "chip", "의견 정보 없음"));
  }

  renderCountBreakdown(detail.broker_summary || [], "subjectBrokerBreakdown", "name");
  renderCountBreakdown(detail.category_summary || [], "subjectCategoryBreakdown", "label");

  const timeline = getFilteredSubjectReports();
  document.getElementById("subjectTimelineMeta").textContent = `현재 필터 기준 ${formatNumber(
    timeline.length
  )}건`;
  const timelineContainer = document.getElementById("subjectTimeline");
  timelineContainer.innerHTML = "";
  if (!timeline.length) {
    timelineContainer.appendChild(el("div", "empty", "현재 필터 조건에 맞는 타임라인이 없습니다."));
  } else {
    timeline.forEach((report) => {
      timelineContainer.appendChild(buildReportCard(report));
    });
  }
}

function formatSignedPct(value, suffix = "%") {
  if (value === null || value === undefined) {
    return "–";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "–";
  }
  return `${numeric > 0 ? "+" : ""}${numeric.toFixed(1)}${suffix}`;
}

function perfCell(value, suffix = "%") {
  const cell = document.createElement("td");
  cell.textContent = formatSignedPct(value, suffix);
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric !== 0 && value !== null && value !== undefined) {
    cell.className = numeric > 0 ? "perf-positive" : "perf-negative";
  }
  return cell;
}

function buildPerformanceTable(rows) {
  const table = document.createElement("table");
  table.className = "perf-table";
  const head = document.createElement("tr");
  ["구분", "표본", "1d 평균", "7d 평균", "7d 적중률", "7d 초과수익", "30d 평균"].forEach(
    (label) => {
      head.appendChild(el("th", null, label));
    }
  );
  table.appendChild(head);

  rows.forEach((row) => {
    const horizons = row.horizons || {};
    const day7 = horizons["7d"] || {};
    const tr = document.createElement("tr");
    tr.appendChild(el("td", null, row.label || "-"));
    tr.appendChild(el("td", null, formatNumber(row.priced || 0)));
    tr.appendChild(perfCell(horizons["1d"]?.avg_return_pct));
    tr.appendChild(perfCell(day7.avg_return_pct));
    tr.appendChild(
      el(
        "td",
        null,
        day7.hit_rate_pct === undefined || day7.hit_rate_pct === null
          ? "–"
          : `${day7.hit_rate_pct}%`
      )
    );
    tr.appendChild(perfCell(day7.avg_excess_return_pct));
    tr.appendChild(perfCell(horizons["30d"]?.avg_return_pct));
    table.appendChild(tr);
  });
  return table;
}

function renderPerformance() {
  const summaryContainer = document.getElementById("performanceSummary");
  const meta = document.getElementById("performanceMeta");
  if (!summaryContainer) {
    return;
  }
  summaryContainer.innerHTML = "";
  const panels = [
    ["perfByScore", "by_score_bucket"],
    ["perfByCategory", "by_category"],
    ["perfByBroker", "by_broker"],
  ];
  panels.forEach(([id]) => {
    const node = document.getElementById(id);
    if (node) {
      node.innerHTML = "";
    }
  });

  const summary = state.performance?.summary;
  if (!summary || !summary.tracked_selections) {
    meta.textContent = "";
    summaryContainer.appendChild(
      el("div", "empty", "추적된 선정 성과 데이터가 아직 없습니다.")
    );
    return;
  }

  const pricedTotal = Object.values(summary.priced_by_horizon || {}).reduce(
    (acc, value) => acc + Number(value || 0),
    0
  );
  meta.textContent = `누적 ${formatNumber(summary.tracked_selections)}건 추적 · 가격 매칭 ${formatNumber(pricedTotal)}건`;

  const byHorizon = summary.by_horizon || {};
  ["1d", "7d", "30d"].forEach((horizon) => {
    const stat = byHorizon[horizon];
    const node = el("div", "signal-stat");
    node.appendChild(el("span", null, `${horizon} 평균수익률`));
    if (!stat || !stat.priced) {
      node.appendChild(el("strong", null, "–"));
      node.appendChild(el("span", null, "표본 없음"));
    } else {
      const strong = el("strong", null, formatSignedPct(stat.avg_return_pct));
      if (Number(stat.avg_return_pct) > 0) {
        strong.classList.add("perf-positive");
      } else if (Number(stat.avg_return_pct) < 0) {
        strong.classList.add("perf-negative");
      }
      node.appendChild(strong);
      const excessText =
        stat.avg_excess_return_pct === null || stat.avg_excess_return_pct === undefined
          ? ""
          : ` · 시장 대비 ${formatSignedPct(stat.avg_excess_return_pct)}`;
      node.appendChild(
        el(
          "span",
          null,
          `적중률 ${stat.hit_rate_pct}% · ${formatNumber(stat.priced)}건${excessText}`
        )
      );
    }
    summaryContainer.appendChild(node);
  });

  panels.forEach(([id, key]) => {
    const node = document.getElementById(id);
    if (!node) {
      return;
    }
    const rows = (summary[key] || []).slice(0, 8);
    if (!rows.length) {
      node.appendChild(el("div", "empty", "표본이 아직 없습니다."));
      return;
    }
    node.appendChild(buildPerformanceTable(rows));
  });
}

function renderAll() {
  if (!state.digest) {
    return;
  }
  if (isSubjectMode()) {
    renderSubjectView();
    renderHintBar(
      (state.subjectDetail?.timeline || []).filter(reportMatchesFilters).length,
      state.subjectDetail?.report_count || 0
    );
    return;
  }
  setViewMode("daily");
  renderHero(state.digest);
  renderNotes(state.digest);
  renderStats(state.digest);
  renderChanges(state.digest);
  renderRankings(state.digest);
  renderMustRead(state.digest);
  renderPerformance();
  renderReports();
}

async function ensurePerformanceLoaded() {
  if (state.performance !== null) {
    return;
  }
  try {
    state.performance = await fetchJson("./data/performance/latest.json");
  } catch (error) {
    console.error(error);
    state.performance = { summary: null };
  }
}

function applyDigest(digest) {
  state.digest = digest;
  state.selectedDate = digest.date;
  syncSelectedDate(digest.date);
  populateSubjectSuggestions();
  populateCategoryOptions(digest);
  populateBrokerOptions(digest);
  renderAll();
}

function renderLoadFailure() {
  document.getElementById("heroSummary").textContent =
    "데이터를 불러오지 못했습니다. GitHub Actions로 최신 정적 파일이 생성됐는지 확인해 주세요.";
  document.getElementById("editorialNote").textContent =
    "대시보드 데이터 로딩에 실패했습니다. 잠시 후 다시 시도해 주세요.";
}

async function loadDigest(date) {
  renderLoadingState();
  await ensurePerformanceLoaded();
  try {
    applyDigest(await fetchJson(`./data/days/${date}.json`));
  } catch (error) {
    console.error(error);
    try {
      applyDigest(await fetchJson("./data/latest.json"));
    } catch (fallbackError) {
      console.error(fallbackError);
      renderLoadFailure();
    }
  }
}

async function loadSubjectDetail(subjectKey) {
  if (!subjectKey) {
    state.selectedSubjectKey = null;
    state.subjectDetail = null;
    document.getElementById("subjectSearchMeta").textContent = "";
    renderAll();
    return;
  }

  try {
    const detail = await fetchJson(`./data/subjects/${subjectKey}.json`);
    state.selectedSubjectKey = subjectKey;
    state.subjectDetail = detail;
    document.getElementById("subjectSearchInput").value = detail.subject_name || "";
    document.getElementById("subjectSearchMeta").textContent = `${
      detail.subject_name || subjectKey
    } · ${formatNumber(detail.report_count || 0)}건`;
    syncSubjectInUrl(subjectKey);
    renderAll();
  } catch (error) {
    console.error(error);
    state.selectedSubjectKey = null;
    state.subjectDetail = null;
    document.getElementById("subjectSearchMeta").textContent = "해당 종목 상세를 불러오지 못했습니다.";
    renderAll();
  }
}

async function openSubjectByQuery() {
  const input = document.getElementById("subjectSearchInput");
  const subjectKey = resolveSubjectKey(input.value);
  if (!subjectKey) {
    document.getElementById("subjectSearchMeta").textContent = "일치하는 종목을 찾지 못했습니다.";
    return;
  }
  await loadSubjectDetail(subjectKey);
}

function getRequestedDate(days) {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("date");
  return days.some((day) => day.date === requested) ? requested : days[0]?.date || null;
}

function populateDateOptions(days) {
  const select = document.getElementById("dateSelect");
  select.innerHTML = "";
  days.forEach((day) => {
    const option = el("option");
    option.value = day.date;
    option.textContent = `${day.date} · ${formatNumber(day.total_reports || 0)}건`;
    select.appendChild(option);
  });
}

function resetFilters() {
  state.query = "";
  state.selectedCategory = "all";
  state.selectedBroker = "all";
  state.sortBy = "score";
  state.priorityOnlyView = false;
  state.changesOnlyView = false;

  document.getElementById("searchInput").value = "";
  document.getElementById("categorySelect").value = "all";
  document.getElementById("brokerSelect").value = "all";
  document.getElementById("sortSelect").value = "score";
  document.getElementById("priorityOnlyToggle").checked = false;
  document.getElementById("changesOnlyToggle").checked = false;

  renderAll();
}

async function init() {
  renderLoadingState();

  const dateSelect = document.getElementById("dateSelect");
  const searchInput = document.getElementById("searchInput");
  const categorySelect = document.getElementById("categorySelect");
  const brokerSelect = document.getElementById("brokerSelect");
  const sortSelect = document.getElementById("sortSelect");
  const priorityOnlyToggle = document.getElementById("priorityOnlyToggle");
  const changesOnlyToggle = document.getElementById("changesOnlyToggle");
  const toolbarPinnedToggle = document.getElementById("toolbarPinnedToggle");
  const darkModeToggle = document.getElementById("darkModeToggle");
  const subjectSearchInput = document.getElementById("subjectSearchInput");
  const subjectSearchButton = document.getElementById("subjectSearchButton");
  const resetFiltersButton = document.getElementById("resetFiltersButton");

  state.toolbarPinned = loadToolbarPinnedPreference();
  applyToolbarPinnedState();
  state.theme = loadThemePreference();
  applyThemeState();

  const debouncedRenderAll = debounce(renderAll);
  searchInput.addEventListener("input", (event) => {
    state.query = normalize(event.target.value.trim());
    debouncedRenderAll();
  });

  categorySelect.addEventListener("change", (event) => {
    state.selectedCategory = event.target.value;
    renderAll();
  });

  brokerSelect.addEventListener("change", (event) => {
    state.selectedBroker = event.target.value;
    renderAll();
  });

  sortSelect.addEventListener("change", (event) => {
    state.sortBy = event.target.value;
    renderAll();
  });

  priorityOnlyToggle.addEventListener("change", (event) => {
    state.priorityOnlyView = Boolean(event.target.checked);
    renderAll();
  });

  changesOnlyToggle.addEventListener("change", (event) => {
    state.changesOnlyView = Boolean(event.target.checked);
    renderAll();
  });

  toolbarPinnedToggle.addEventListener("change", (event) => {
    state.toolbarPinned = Boolean(event.target.checked);
    saveToolbarPinnedPreference();
    applyToolbarPinnedState();
  });

  darkModeToggle.addEventListener("change", (event) => {
    state.theme = event.target.checked ? "dark" : "light";
    saveThemePreference();
    applyThemeState();
  });

  subjectSearchInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    await openSubjectByQuery();
  });

  subjectSearchButton.addEventListener("click", async () => {
    await openSubjectByQuery();
  });

  resetFiltersButton.addEventListener("click", resetFilters);

  try {
    const index = await fetchJson("./data/index.json");
    state.index = index;
    try {
      state.subjectIndex = await fetchJson("./data/subjects/index.json");
    } catch (subjectIndexError) {
      console.error(subjectIndexError);
    }
    const days = index.days || [];
    const requestedSubject = getRequestedSubject();

    if (days.length) {
      populateDateOptions(days);
      const initialDate = getRequestedDate(days);
      dateSelect.value = initialDate;
      dateSelect.addEventListener("change", async (event) => {
        if (state.selectedSubjectKey) {
          window.location.href = buildDailyHref(event.target.value);
          return;
        }
        await loadDigest(event.target.value);
      });
      await loadDigest(initialDate);
      if (requestedSubject) {
        await loadSubjectDetail(requestedSubject);
      }
      return;
    }

    applyDigest(await fetchJson("./data/latest.json"));
    if (requestedSubject) {
      await loadSubjectDetail(requestedSubject);
    }
  } catch (error) {
    console.error(error);
    try {
      applyDigest(await fetchJson("./data/latest.json"));
      const requestedSubject = getRequestedSubject();
      if (requestedSubject) {
        await loadSubjectDetail(requestedSubject);
      }
    } catch (fallbackError) {
      console.error(fallbackError);
      renderLoadFailure();
    }
  }
}

init();
