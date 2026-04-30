// Stock Tracker — frontend app
// Single-page app with hash routing.
//   #/        -> home view (centered search prompt)
//   #/SYMBOL  -> detail view (price, candlestick chart, asset info)

const view = document.getElementById('view');
const searchInput = document.getElementById('search-input');
const searchResults = document.getElementById('search-results');

const RANGE_TO_DAYS = {
  '1M': 22,
  '3M': 66,
  '6M': 130,
  '1Y': 260,
  '5Y': 1300,
};

let chart = null;
let candleSeries = null;
let currentSymbol = null;
let currentRange = '1Y';
let resizeObserver = null;

// ---------- Routing ----------

function parseRoute() {
  const hash = window.location.hash.slice(1) || '/';
  const parts = hash.split('/').filter(Boolean);
  if (parts.length === 0) return { name: 'home' };
  return { name: 'detail', symbol: parts[0].toUpperCase() };
}

function render() {
  teardownChart();
  const route = parseRoute();
  if (route.name === 'home') {
    renderHome();
  } else {
    renderDetail(route.symbol);
  }
}

window.addEventListener('hashchange', render);

// ---------- Home ----------

async function renderHome() {
  document.title = 'Stock Tracker';
  view.innerHTML = '';
  const tpl = document.getElementById('tpl-home').content.cloneNode(true);
  view.appendChild(tpl);

  // Wire up SPY chart with timeframe buttons
  currentSymbol = 'SPY';
  currentRange = '1Y';
  const buttons = view.querySelectorAll('.timeframe-bar button');
  buttons.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.range === currentRange);
    btn.addEventListener('click', () => {
      currentRange = btn.dataset.range;
      buttons.forEach((b) => b.classList.toggle('active', b === btn));
      loadBars('SPY', currentRange);
    });
  });

  loadBars('SPY', currentRange);
  loadAccount();
  loadPortfolio();
}

async function loadPortfolio() {
  const list = view.querySelector('.portfolio-list');
  const empty = view.querySelector('.portfolio-empty');
  const summary = view.querySelector('.portfolio-summary');
  if (!list) return;

  list.innerHTML = '<li class="skeleton">Loading portfolio…</li>';

  try {
    const data = await fetchJSON('/portfolio');
    list.innerHTML = '';

    if (!data.holdings || data.holdings.length === 0) {
      empty.hidden = false;
      summary.textContent = '';
      return;
    }
    empty.hidden = true;

    const totalValue = data.total_market_value || 0;
    const totalGain = data.total_gain_loss || 0;
    const totalPct = data.total_cost_basis
      ? (totalGain / data.total_cost_basis) * 100
      : 0;
    const sign = totalGain >= 0 ? '+' : '';
    summary.textContent = `${formatMoney(totalValue)}  (${sign}${formatMoney(totalGain)} / ${sign}${totalPct.toFixed(2)}%)`;
    summary.classList.toggle('up', totalGain >= 0);
    summary.classList.toggle('down', totalGain < 0);

    data.holdings.forEach((h) => {
      const li = document.createElement('li');
      li.dataset.symbol = h.symbol;
      li.tabIndex = 0;
      li.innerHTML = `
        <div class="holding-left">
          <span class="holding-name"></span>
          <div class="holding-meta">
            <span class="holding-ticker"></span>
            <span class="holding-shares"></span>
          </div>
        </div>
        <div class="holding-right">
          <div class="holding-price"></div>
          <div class="holding-change"></div>
        </div>
      `;
      li.querySelector('.holding-name').textContent = h.name || h.symbol;
      li.querySelector('.holding-ticker').textContent = h.symbol;
      li.querySelector('.holding-shares').textContent =
        h.shares != null ? `${h.shares.toFixed(4)} sh` : '';
      li.querySelector('.holding-price').textContent =
        h.price != null ? formatMoney(h.price) : '—';

      const changeEl = li.querySelector('.holding-change');
      if (h.gain_loss != null && h.gain_loss_pct != null) {
        const s = h.gain_loss >= 0 ? '+' : '';
        changeEl.textContent = `${s}${formatMoney(h.gain_loss)} (${s}${h.gain_loss_pct.toFixed(2)}%)`;
        changeEl.classList.toggle('up', h.gain_loss >= 0);
        changeEl.classList.toggle('down', h.gain_loss < 0);
      } else {
        changeEl.textContent = '';
      }

      li.addEventListener('click', () => goToSymbol(h.symbol));
      li.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          goToSymbol(h.symbol);
        }
      });
      list.appendChild(li);
    });
  } catch (err) {
    list.innerHTML = '';
    empty.hidden = false;
    empty.textContent = `Couldn't load portfolio: ${err.message}`;
    summary.textContent = '';
  }
}

async function loadAccount() {
  const setText = (sel, val) => {
    const el = view.querySelector(sel);
    if (el) el.textContent = val;
  };
  const errEl = view.querySelector('.account-error');

  try {
    const acct = await fetchJSON('/account');
    setText('.account-buying-power', formatMoney(acct.buying_power));
    setText('.account-cash', formatMoney(acct.cash));
    setText('.account-portfolio', formatMoney(acct.portfolio_value));
    setText('.account-status-value', formatStatus(acct.status));
    if (errEl) errEl.hidden = true;
  } catch (err) {
    setText('.account-buying-power', '—');
    setText('.account-cash', '—');
    setText('.account-portfolio', '—');
    setText('.account-status-value', '—');
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = `Account unavailable: ${err.message}`;
    }
  }
}

// ---------- Detail ----------

async function renderDetail(symbol) {
  currentSymbol = symbol;
  document.title = `${symbol} — Stock Tracker`;

  view.innerHTML = '';
  const tpl = document.getElementById('tpl-detail').content.cloneNode(true);
  view.appendChild(tpl);

  // Wire up timeframe buttons
  const buttons = view.querySelectorAll('.timeframe-bar button');
  buttons.forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.range === currentRange);
    btn.addEventListener('click', () => {
      currentRange = btn.dataset.range;
      buttons.forEach((b) => b.classList.toggle('active', b === btn));
      loadBars(symbol, currentRange);
    });
  });

  // Show placeholder while loading
  view.querySelector('.company-name').textContent = symbol;
  view.querySelector('.ticker').textContent = symbol;

  // Fetch info + bars in parallel
  const [info, bars] = await Promise.allSettled([
    fetchJSON(`/stocks/${symbol}/info`),
    fetchJSON(`/stocks/${symbol}?limit=${RANGE_TO_DAYS[currentRange]}`),
  ]);

  if (bars.status === 'rejected') {
    renderError(`No price data found for ${symbol}.`);
    return;
  }

  applyInfo(info.status === 'fulfilled' ? info.value : null, symbol);
  applyBars(bars.value);
}

function applyInfo(info, fallbackSymbol) {
  const set = (sel, val) => {
    const el = view.querySelector(sel);
    if (el) el.textContent = val == null || val === '' ? '—' : val;
  };

  if (info) {
    view.querySelector('.company-name').textContent = info.name || info.symbol;
    set('.ticker', info.symbol);
    set('.exchange', info.exchange || '');
    set('.info-symbol', info.symbol);
    set('.info-exchange', info.exchange);
    set('.info-class', formatAssetClass(info.asset_class));
    set('.info-status', formatStatus(info.status));
    set('.info-tradable', info.tradable ? 'Yes' : 'No');
  } else {
    view.querySelector('.company-name').textContent = fallbackSymbol;
    set('.ticker', fallbackSymbol);
    set('.info-symbol', fallbackSymbol);
    set('.info-exchange', '—');
    set('.info-class', '—');
    set('.info-status', '—');
    set('.info-tradable', '—');
  }
}

function applyBars(payload) {
  const bars = (payload && payload.bars) || [];
  if (bars.length === 0) {
    renderError(`No price history available for ${payload && payload.symbol}.`);
    return;
  }

  const ascending = [...bars].reverse();
  const latest = bars[0];
  const previous = bars[1];

  // Price + change
  const priceEl = view.querySelector('.price');
  const changeEl = view.querySelector('.price-change');
  priceEl.textContent = formatMoney(latest.close);

  if (previous) {
    const diff = latest.close - previous.close;
    const pct = (diff / previous.close) * 100;
    const sign = diff >= 0 ? '+' : '';
    changeEl.textContent = `${sign}${formatMoney(diff)} (${sign}${pct.toFixed(2)}%) since ${previous.date}`;
    changeEl.classList.toggle('up', diff >= 0);
    changeEl.classList.toggle('down', diff < 0);
  } else {
    changeEl.textContent = '';
  }

  const volEl = view.querySelector('.info-volume');
  if (volEl) volEl.textContent = formatVolume(latest.volume);

  drawChart(ascending);
}

async function loadBars(symbol, range) {
  try {
    const bars = await fetchJSON(`/stocks/${symbol}?limit=${RANGE_TO_DAYS[range]}`);
    applyBars(bars);
  } catch (err) {
    renderError(err.message || 'Failed to load price data.');
  }
}

function renderError(message) {
  view.innerHTML = '';
  const tpl = document.getElementById('tpl-error').content.cloneNode(true);
  tpl.querySelector('.error-message').textContent = message;
  view.appendChild(tpl);
}

// ---------- Chart ----------

function teardownChart() {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (chart) {
    chart.remove();
    chart = null;
    candleSeries = null;
  }
}

function drawChart(ascendingBars) {
  const container = document.getElementById('chart');
  if (!container || typeof LightweightCharts === 'undefined') return;

  teardownChart();

  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight,
    layout: {
      background: { type: 'solid', color: '#ffffff' },
      textColor: '#0f172a',
      fontFamily:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    },
    grid: {
      vertLines: { color: '#eef2f9' },
      horzLines: { color: '#eef2f9' },
    },
    rightPriceScale: { borderColor: '#dbe3f0' },
    timeScale: {
      borderColor: '#dbe3f0',
      rightOffset: 4,
      barSpacing: 6,
    },
    crosshair: {
      vertLine: { color: '#2962FF', width: 1, style: 2 },
      horzLine: { color: '#2962FF', width: 1, style: 2 },
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: '#2962FF',
    downColor: '#dc2626',
    borderUpColor: '#2962FF',
    borderDownColor: '#dc2626',
    wickUpColor: '#2962FF',
    wickDownColor: '#dc2626',
  });

  candleSeries.setData(
    ascendingBars.map((b) => ({
      time: b.date,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    })),
  );

  chart.timeScale().fitContent();

  resizeObserver = new ResizeObserver(() => {
    if (chart) {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
    }
  });
  resizeObserver.observe(container);
}

// ---------- Search ----------

let searchTimer = null;
let activeIndex = -1;
let lastResults = [];

searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim();
  clearTimeout(searchTimer);
  if (q.length === 0) {
    hideResults();
    return;
  }
  searchTimer = setTimeout(() => runSearch(q), 200);
});

searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    moveActive(1);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    moveActive(-1);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (lastResults.length === 0) return;
    const pick = lastResults[Math.max(0, activeIndex)];
    if (pick) goToSymbol(pick.symbol);
  } else if (e.key === 'Escape') {
    hideResults();
    searchInput.blur();
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.search')) hideResults();
});

async function runSearch(q) {
  try {
    const data = await fetchJSON(`/search?q=${encodeURIComponent(q)}&limit=10`);
    lastResults = data.results || [];
    activeIndex = lastResults.length > 0 ? 0 : -1;
    renderResults(lastResults);
  } catch (err) {
    renderResults([], err.message || 'Search failed');
  }
}

function renderResults(results, errorMessage) {
  searchResults.innerHTML = '';
  if (errorMessage) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = errorMessage;
    searchResults.appendChild(li);
    searchResults.hidden = false;
    return;
  }
  if (results.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No matches';
    searchResults.appendChild(li);
    searchResults.hidden = false;
    return;
  }
  results.forEach((r, i) => {
    const li = document.createElement('li');
    li.dataset.symbol = r.symbol;
    if (i === activeIndex) li.classList.add('active');
    li.innerHTML = `
      <span class="sym"></span>
      <span class="nm"></span>
      <span class="ex"></span>
    `;
    li.querySelector('.sym').textContent = r.symbol;
    li.querySelector('.nm').textContent = r.name || '';
    li.querySelector('.ex').textContent = r.exchange || '';
    li.addEventListener('mousedown', (e) => {
      e.preventDefault();
      goToSymbol(r.symbol);
    });
    searchResults.appendChild(li);
  });
  searchResults.hidden = false;
}

function moveActive(delta) {
  if (lastResults.length === 0) return;
  activeIndex = (activeIndex + delta + lastResults.length) % lastResults.length;
  Array.from(searchResults.children).forEach((el, i) => {
    el.classList.toggle('active', i === activeIndex);
  });
}

function hideResults() {
  searchResults.hidden = true;
  searchResults.innerHTML = '';
  lastResults = [];
  activeIndex = -1;
}

function goToSymbol(symbol) {
  searchInput.value = '';
  hideResults();
  searchInput.blur();
  if (parseRoute().symbol === symbol) {
    render();
  } else {
    window.location.hash = `#/${symbol}`;
  }
}

// ---------- Helpers ----------

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function formatMoney(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  return (
    (n < 0 ? '-$' : '$') +
    abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  );
}

function formatVolume(n) {
  if (n == null || isNaN(n)) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
  return n.toLocaleString();
}

function formatAssetClass(s) {
  if (!s) return '—';
  // Alpaca returns things like "AssetClass.US_EQUITY"
  const cleaned = String(s).split('.').pop().replace(/_/g, ' ');
  return cleaned.replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatStatus(s) {
  if (!s) return '—';
  const cleaned = String(s).split('.').pop().toLowerCase();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

// ---------- Boot ----------

render();
