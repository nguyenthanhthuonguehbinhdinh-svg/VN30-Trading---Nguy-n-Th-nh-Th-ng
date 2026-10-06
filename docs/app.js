/* VN30 Quant Desk — đọc JSON do engine Python sinh ra và vẽ dashboard. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const LWC = window.LightweightCharts;
  const S = { live: null, bt: null, charts: null, preview: null, eqSrc: "live", sigFilter: "ALL", charts_: [] };

  // ------------------------------------------------------------ format
  const nf0 = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const vnd = (x) => (x == null ? "—" : nf0.format(Math.round(x)));
  const mil = (x) => (x == null ? "—" : nf2.format(x / 1e6) + " tr");
  const pct = (x, d = 2, sign = true) => (x == null || isNaN(x) ? "—" : (sign && x > 0 ? "+" : "") + (x * 100).toFixed(d).replace(".", ",") + "%");
  const cls = (x) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "ref");
  const num = (x, d = 1) => (x == null ? "—" : Number(x).toFixed(d).replace(".", ","));
  const dmy = (s) => (s ? s.split("-").reverse().join("/") : "—");
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const STRAT = { BREAKOUT: "Breakout", SIDEWAY: "Sideway", SIDEWAY_T: "Lướt T+" };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function getJSON(path) {
    try {
      const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
      return r.ok ? await r.json() : null;
    } catch { return null; }
  }

  // ------------------------------------------------------------ theme
  function initTheme() {
    let t = null;
    try { t = localStorage.getItem("theme"); } catch {}
    if (t) document.documentElement.dataset.theme = t;
    $("#theme-btn").onclick = () => {
      const cur = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = cur;
      try { localStorage.setItem("theme", cur); } catch {}
      renderCharts();
    };
  }

  // ------------------------------------------------------------ session clock (giờ VN)
  function vnNow() {
    const d = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Ho_Chi_Minh" }));
    return d;
  }
  function sessionStatus() {
    const d = vnNow(), wd = d.getDay(), m = d.getHours() * 60 + d.getMinutes();
    if (wd === 0 || wd === 6) return ["Cuối tuần – nghỉ giao dịch", ""];
    if (m < 9 * 60) return ["Trước giờ mở cửa", ""];
    if (m < 11 * 60 + 30) return ["Phiên sáng", "up"];
    if (m < 13 * 60) return ["Nghỉ trưa", "ref"];
    if (m < 14 * 60 + 30) return ["Phiên chiều", "up"];
    if (m < 14 * 60 + 45) return ["ATC 14:30–14:45 · đặt lệnh!", "down"];
    return ["Đã đóng cửa", ""];
  }
  function tickClock() {
    const [t, c] = sessionStatus();
    const el = $("#st-session");
    el.className = "pill " + c;
    el.innerHTML = `<span class="dot"></span>${t}`;
  }

  // ------------------------------------------------------------ chart helpers
  function baseChart(el, opts = {}) {
    el.innerHTML = "";
    const ch = LWC.createChart(el, {
      autoSize: true,
      layout: { attributionLogo: false, background: { type: "solid", color: "transparent" }, textColor: css("--muted"), fontFamily: "'Be Vietnam Pro', system-ui, -apple-system, Segoe UI, sans-serif", fontSize: 11 },
      grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
      rightPriceScale: { borderColor: css("--line-2"), minimumWidth: 78 },
      timeScale: { borderColor: css("--line-2"), timeVisible: false },
      crosshair: { mode: 0 },
      localization: { locale: "vi-VN", priceFormatter: opts.priceFormatter || ((p) => nf0.format(p)) },
      handleScroll: opts.static ? false : true,
      handleScale: opts.static ? false : true,
      ...opts.extra,
    });
    S.charts_.push(ch);
    return ch;
  }

  const fit = (ch) => {
    const ts = ch.timeScale();
    ts.fitContent();
    const el = ch.chartElement().parentElement;
    let n = 0;
    const ro = new ResizeObserver(() => { ts.fitContent(); if (++n > 4) ro.disconnect(); });
    ro.observe(el);
    setTimeout(() => ts.fitContent(), 300);
  };

  // ------------------------------------------------------------ HERO
  function renderHero() {
    const L = S.live;
    const m = L.metrics || {};
    const cap = L.initial_capital;
    const nav = L.nav ?? cap;
    const ret = nav / cap - 1;
    $("#k-nav").textContent = vnd(nav) + " đ";
    $("#k-ret").textContent = pct(ret);
    $("#k-ret").className = "chip " + cls(ret);
    $("#k-cap").textContent = mil(cap);
    $("#k-start").textContent = dmy(L.start_date);

    const h = L.nav_history || [];
    const prev = h.length > 1 ? h[h.length - 2].nav : cap;
    const dayPnl = nav - prev;
    $("#k-day").textContent = (dayPnl > 0 ? "+" : "") + vnd(dayPnl);
    $("#k-day").className = "kv mono " + cls(dayPnl);
    $("#k-day-pct").textContent = `${pct(dayPnl / prev)} · phiên ${dmy(L.as_of)}`;

    $("#k-bench").textContent = pct(m.benchmark_return);
    $("#k-bench").className = "kv mono " + cls(m.benchmark_return);
    $("#k-alpha").innerHTML = m.alpha == null ? "—" : `Vượt trội: <b class="${cls(m.alpha)}">${pct(m.alpha)}</b>`;

    $("#k-cash").textContent = mil(L.cash);
    $("#k-cash-pct").textContent = `${pct(L.cash / nav, 1, false)} NAV`;
    const n = (L.positions || []).length, mx = L.max_positions || 5;
    $("#k-pos").textContent = `${n}/${mx}`;
    $("#k-slots").innerHTML = Array.from({ length: mx }, (_, i) => `<i class="${i < n ? "on" : ""}"></i>`).join("");
    $("#k-dd").textContent = pct(m.max_drawdown);
    $("#k-dd").className = "kv mono " + (m.max_drawdown < 0 ? "down" : "");
    $("#k-win").textContent = m.win_rate == null ? "—" : pct(m.win_rate, 0, false);
    $("#k-win-sub").textContent = m.n_trades ? `${m.n_trades} lệnh đã đóng · PF ${num(m.profit_factor, 2)}` : "chưa có lệnh đóng";

    $("#st-updated").textContent = `Cập nhật ${L.generated_at} · nến ${dmy(L.last_bar)}`;
    $("#ft-src").textContent = [...new Set(Object.values(L.sources || {}))].join(", ") || "—";
    if (L.demo) $("#demo-banner").classList.remove("hidden");
  }

  function renderSpark() {
    const h = S.live.nav_history || [];
    const el = $("#spark");
    if (h.length < 2) { el.innerHTML = ""; return; }
    const ch = baseChart(el, { static: true, extra: { rightPriceScale: { visible: false }, timeScale: { visible: false }, grid: { vertLines: { visible: false }, horzLines: { visible: false } }, crosshair: { vertLine: { visible: false }, horzLine: { visible: false } } } });
    const up = h[h.length - 1].nav >= S.live.initial_capital;
    const c = up ? css("--up") : css("--down");
    const s = ch.addAreaSeries({ lineColor: c, topColor: c + "55", bottomColor: c + "00", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    s.setData(h.map((x) => ({ time: x.date, value: x.nav })));
    fit(ch);
  }

  // ------------------------------------------------------------ ACTIONS
  function renderActions() {
    const L = S.live, P = S.preview;
    const box = $("#actions");
    const usePreview = P && P.is_today && P.date > (L.as_of || "") && !P.demo;
    let html = "";
    if (usePreview) {
      $("#act-when").textContent = `· phiên ${dmy(P.date)} (tính lúc ${P.generated_at.slice(11)})`;
      $("#act-badge").className = "pill ref"; $("#act-badge").textContent = "DỰ KIẾN – đặt lệnh ATC";
      const posMap = Object.fromEntries((L.positions || []).map((p) => [p.ticker, p]));
      const sells = P.decision.sells || [];
      const free = (L.max_positions || 5) - (L.positions || []).length + sells.length;
      let cash = L.cash + sells.reduce((a, s) => a + (posMap[s.ticker] ? posMap[s.ticker].value * (1 - L.fees.sell_fee - L.fees.sell_tax) : 0), 0);
      const slot = (L.nav || L.initial_capital) / (L.max_positions || 5);
      sells.forEach((s) => {
        const p = posMap[s.ticker];
        html += actRow("sell", s.ticker, p ? p.qty : null, p ? p.price : null, reasonVN(s.reason), p ? p.value : null);
      });
      (P.decision.buys || []).slice(0, Math.max(free, 0)).forEach((b) => {
        const budget = Math.min(slot, cash);
        const qty = Math.floor(budget / (b.price * (1 + L.fees.buy_fee)) / 100) * 100;
        if (qty <= 0) return;
        cash -= qty * b.price * (1 + L.fees.buy_fee);
        html += actRow("buy", b.ticker, qty, b.price, `${b.label} · điểm ${num(b.score, 1)}`, qty * b.price);
      });
      (P.decision.blocked || []).forEach((b) => {
        html += `<div class="act"><div class="side" style="background:var(--panel)">CHỜ</div><div class="tk">${b.ticker}</div><div class="det">Chạm điều kiện bán nhưng chưa đủ T+2 — bán phiên sau</div><div></div></div>`;
      });
      $("#act-foot").textContent = "Giá là giá tại thời điểm tính (trong phiên). Lệnh giấy sẽ khớp theo giá đóng cửa (ATC) khi chốt sổ lúc ~15:15.";
    } else {
      $("#act-when").textContent = `· phiên ${dmy(L.as_of)}`;
      $("#act-badge").className = "pill acc"; $("#act-badge").textContent = "ĐÃ KHỚP (giá ATC)";
      (L.today_orders || []).forEach((o) => {
        const sub = o.side === "BÁN"
          ? `${esc(o.note)} · lãi/lỗ <b class="${cls(o.pnl)}">${(o.pnl > 0 ? "+" : "") + vnd(o.pnl)}đ (${pct(o.ret)})</b>`
          : `${esc(o.note)}`;
        html += actRow(o.side === "MUA" ? "buy" : "sell", o.ticker, o.qty, o.price, sub, o.value, o);
      });
      (L.skipped || []).forEach((s) => {
        html += `<div class="act"><div class="side" style="background:var(--panel)">BỎ</div><div class="tk">${s.ticker}</div><div class="det">${esc(s.label)} — ${esc(s.why)}</div><div></div></div>`;
      });
      $("#act-foot").textContent = "Phiên tới: tín hiệu dự kiến sẽ hiện ở đây khoảng 14:25–14:35 để bạn kịp đặt lệnh ATC.";
    }
    box.innerHTML = html || `<div class="empty">Không có lệnh mua/bán — <b>GIỮ</b> nguyên danh mục, <b>CHỜ</b> tín hiệu.</div>`;
  }
  function actRow(side, tk, qty, price, note, value, o) {
    const fee = o ? `phí ${vnd(o.fee)}${o.tax ? " · thuế " + vnd(o.tax) : ""}` : "ước tính";
    return `<div class="act">
      <div class="side ${side}">${side === "buy" ? "MUA" : "BÁN"}</div>
      <div class="tk">${tk}</div>
      <div class="det"><b>${qty ? vnd(qty) + " cp" : "—"}</b> @ <b>${vnd(price)}</b><br>${note || ""}</div>
      <div class="amt">${value ? mil(value) : "—"}<div class="muted small">${fee}</div></div>
    </div>`;
  }
  const REASON = { "STOP_8%": "Cắt lỗ cứng -8%", TRAILING_ATR: "Trailing stop 4×ATR", HET_HAN_365: "Hết hạn 365 phiên", CHOT_LOI: "Chốt lời", CAT_LO: "Cắt lỗ -5%" };
  const reasonVN = (r) => REASON[r] || r;

  // ------------------------------------------------------------ MARKET
  function renderMarket() {
    const m = (S.preview && S.preview.is_today && S.preview.date > (S.live.as_of || "") ? S.preview.decision.market : null) || S.live.market;
    if (!m || !m.ok) { $("#market").innerHTML = `<div class="empty">${esc(m?.note || "Không có dữ liệu VNINDEX")} — không mở lệnh mới</div>`; return; }
    const row = (name, ma, ok, rule) => {
      const d = m.close / ma - 1;
      return `<div class="filter-row"><div><div class="fl">${name}</div><div class="fs">${rule} · ${ma ? vnd(ma) : "—"} (${pct(d)})</div></div>
        <span class="pill ${ok ? "up" : "down"}">${ok ? "✓ ĐƯỢC MỞ LỆNH" : "✕ CHẶN LỆNH MỚI"}</span></div>`;
    };
    $("#market").innerHTML = `<div class="mkt-top"><div><div class="label">VNINDEX</div><div class="mkt-val mono">${nf2.format(m.close)}</div></div>
      <span class="chip ${cls(m.chg)}">${pct(m.chg)}</span></div>
      ${row("Breakout", m.ma50, m.breakout_ok, "VNINDEX > MA50")}
      ${row("Sideway", m.ma200, m.sideway_ok, "VNINDEX > MA200")}`;
  }

  // ------------------------------------------------------------ EQUITY
  function renderEquity() {
    const src = S.eqSrc === "bt" ? S.bt?.nav_history : S.live.nav_history;
    const el = $("#eq-chart");
    if (!src || src.length < 2) { el.innerHTML = `<div class="empty" style="margin-top:120px">Chưa đủ dữ liệu — đường vốn live sẽ xuất hiện sau vài phiên. Xem tab Backtest để thấy lịch sử.</div>`; return; }
    const ch = baseChart(el, { priceFormatter: (p) => p.toFixed(1) });
    const n0 = src[0].nav, v0 = (src.find((x) => x.vnindex) || {}).vnindex;
    const a = ch.addAreaSeries({ lineColor: css("--up"), topColor: css("--up") + "40", bottomColor: css("--up") + "00", lineWidth: 2, title: "Danh mục" });
    a.setData(src.map((x) => ({ time: x.date, value: (x.nav / n0) * 100 })));
    if (v0) {
      const b = ch.addLineSeries({ color: css("--muted"), lineWidth: 1.5, title: "VNINDEX" });
      b.setData(src.filter((x) => x.vnindex).map((x) => ({ time: x.date, value: (x.vnindex / v0) * 100 })));
    }
    const orders = S.eqSrc === "bt" ? [] : S.live.orders || [];
    if (orders.length && orders.length < 400) {
      const showText = orders.length <= 24;
      const set = new Set(src.map((x) => x.date));
      a.setMarkers(orders.filter((o) => set.has(o.date)).map((o) => ({ time: o.date, position: o.side === "MUA" ? "belowBar" : "aboveBar", color: o.side === "MUA" ? css("--up") : css("--down"), shape: o.side === "MUA" ? "arrowUp" : "arrowDown", text: showText ? o.ticker : "" })));
    }
    fit(ch);
  }

  // ------------------------------------------------------------ ALLOC + WATCH
  function renderAlloc() {
    const L = S.live, nav = L.nav || L.initial_capital;
    const palette = ["#22c55e", "#38bdf8", "#a78bfa", "#f59e0b", "#f472b6"];
    const items = (L.positions || []).map((p, i) => ({ name: p.ticker, v: p.value, c: palette[i % 5], sub: STRAT[p.strategy] }));
    items.push({ name: "Tiền mặt", v: L.cash, c: css("--line-2"), sub: "" });
    let acc = 0;
    const stops = items.map((it) => { const a = acc; acc += it.v / nav * 360; return `${it.c} ${a}deg ${acc}deg`; }).join(",");
    $("#donut").style.background = `conic-gradient(${stops})`;
    $("#donut").innerHTML = `<span>${pct(1 - L.cash / nav, 0, false)}<br><span class="muted small" style="position:static;display:block">đã đầu tư</span></span>`;
    $("#alloc-list").innerHTML = items.map((it) => `<div class="alloc-item"><span class="sw" style="background:${it.c}"></span><b>${it.name}</b><span class="muted small">${it.sub}</span><span class="pct">${pct(it.v / nav, 1, false)}</span></div>`).join("");
  }
  function renderWatch() {
    const w = S.live.watch || [];
    if (!w.length) { $("#watch").innerHTML = `<div class="empty">Không có mã nào</div>`; return; }
    $("#watch").innerHTML = w.map((x) => `<div class="hbar click" data-tk="${x.ticker}" style="cursor:pointer">
      <div><b>${x.ticker}</b> <span class="muted small">${vnd(x.close)}</span></div>
      <div class="tr"><i style="width:${Math.max(4, 100 - Math.min(x.dist_breakout * 100, 20) * 5)}%;background:var(--violet)"></i></div>
      <div class="mono small" style="text-align:right">${pct(x.dist_breakout, 1)}</div></div>`).join("") +
      `<div class="muted small foot">Thanh càng dài = càng gần giá cần vượt để có tín hiệu Breakout (còn phải thoả MA10>MA50, giá>MA50, VNINDEX>MA50).</div>`;
    $("#watch").querySelectorAll("[data-tk]").forEach((el) => (el.onclick = () => openTicker(el.dataset.tk)));
  }

  // ------------------------------------------------------------ TABLE builder
  function table(el, cols, rows, opts = {}) {
    let sortKey = opts.sort || null, dir = opts.dir || -1;
    const draw = () => {
      const data = [...rows];
      if (sortKey) {
        const c = cols.find((c) => c.k === sortKey);
        const val = c.sv || ((r) => r[sortKey]);
        data.sort((a, b) => { const x = val(a), y = val(b); return (x == null) - (y == null) || (x > y ? 1 : x < y ? -1 : 0) * dir; });
      }
      el.innerHTML = `<thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}" data-k="${c.k}">${c.t}${sortKey === c.k ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
        <tbody>${data.length ? data.map((r) => `<tr class="${opts.onClick ? "click" : ""}" data-tk="${r.ticker || ""}">${cols.map((c) => `<td class="${c.num ? "num" : ""} ${c.cl ? c.cl(r) : ""}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${cols.length}"><div class="empty">${opts.empty || "Chưa có dữ liệu"}</div></td></tr>`}</tbody>`;
      el.querySelectorAll("th").forEach((th) => (th.onclick = () => { const k = th.dataset.k; dir = sortKey === k ? -dir : -1; sortKey = k; draw(); }));
      if (opts.onClick) el.querySelectorAll("tbody tr[data-tk]").forEach((tr) => tr.dataset.tk && (tr.onclick = () => opts.onClick(tr.dataset.tk)));
    };
    draw();
  }

  // ------------------------------------------------------------ SIGNALS
  function currentBoard() {
    const P = S.preview;
    if (P && P.is_today && P.date > (S.live.as_of || "") && !P.demo) return { board: P.board, date: P.date, tag: `dự kiến lúc ${P.generated_at.slice(11)}` };
    return { board: S.live.board || [], date: S.live.as_of, tag: "chốt phiên" };
  }
  function renderSignals() {
    const { board, date, tag } = currentBoard();
    $("#sig-date").textContent = `· ${dmy(date)} (${tag})`;
    const order = { "MUA": 0, "BÁN": 1, "GIỮ": 2, "CHỜ": 3 };
    const rows = board.filter((r) => S.sigFilter === "ALL" || r.action === S.sigFilter);
    const rsiCell = (r) => {
      if (r.rsi == null) return "—";
      const c = r.rsi <= 30 ? "var(--up)" : r.rsi >= 70 ? "var(--down)" : "var(--accent)";
      return `${num(r.rsi)}<span class="rsi-bar"><i style="width:${r.rsi}%;background:${c}"></i></span>`;
    };
    table($("#sig-table"), [
      { k: "ticker", t: "Mã", f: (r) => `<span class="tk">${r.ticker}</span>` },
      { k: "action", t: "Hành động", sv: (r) => order[r.action], f: (r) => `<span class="act-tag act-${r.action}">${r.action}</span>` },
      { k: "close", t: "Giá", num: 1, f: (r) => vnd(r.close) },
      { k: "chg", t: "+/-", num: 1, f: (r) => `<span class="${cls(r.chg)}">${pct(r.chg)}</span>` },
      { k: "signal", t: "Tín hiệu", f: (r) => r.signal ? `<b>${esc(r.signal)}</b>` : `<span class="muted">—</span>` },
      { k: "score", t: "Điểm", num: 1, f: (r) => r.score == null ? "—" : num(r.score) },
      { k: "rsi", t: "RSI14", num: 1, f: rsiCell },
      { k: "trend", t: "MA10 vs MA50", f: (r) => `<span class="${r.trend === "Tăng" ? "up" : "down"}">${r.trend}</span> <span class="muted small">${r.regime}</span>` },
      { k: "roc60", t: "ROC60", num: 1, f: (r) => `<span class="${cls(r.roc60)}">${pct(r.roc60, 1)}</span>` },
      { k: "breakout_trigger", t: "Mốc Breakout", num: 1, f: (r) => r.breakout_trigger ? `${vnd(r.breakout_trigger)} <span class="muted small">${pct(r.dist_breakout, 1)}</span>` : "—" },
      { k: "rsi_trigger", t: "Mốc RSI≤30", num: 1, f: (r) => vnd(r.rsi_trigger) },
      { k: "action_note", t: "Ghi chú", f: (r) => `<span class="note">${esc(r.action_note || "")}</span>` },
    ], rows, { sort: "action", dir: 1, onClick: openTicker });
  }

  // ------------------------------------------------------------ PORTFOLIO
  function renderPositions() {
    const ps = S.live.positions || [];
    if (!ps.length) { $("#positions").innerHTML = `<div class="empty">Danh mục đang 100% tiền mặt.</div>`; return; }
    $("#positions").innerHTML = `<div class="pos-grid">${ps.map((p) => {
      const lo = p.exit_level, hi = p.take_profit || Math.max(p.peak, p.price) * 1.03;
      const span = hi - lo || 1;
      const posOf = (v) => Math.min(100, Math.max(0, ((v - lo) / span) * 100));
      return `<div class="pos" data-tk="${p.ticker}">
        <div class="pos-head"><div><span class="pos-tk">${p.ticker}</span> <span class="strat strat-${p.strategy}">${STRAT[p.strategy]}</span></div>
          <div style="text-align:right"><div class="pos-pnl mono ${cls(p.pnl_net)}">${pct(p.pnl_net)}</div><div class="small ${cls(p.pnl_vnd)} mono">${(p.pnl_vnd > 0 ? "+" : "") + vnd(p.pnl_vnd)}đ</div></div></div>
        <div class="pos-rows">
          <div><span>Giá vốn</span><span>${vnd(p.entry_price)}</span></div><div><span>Giá hiện tại</span><span>${vnd(p.price)}</span></div>
          <div><span>Khối lượng</span><span>${vnd(p.qty)}</span></div><div><span>Giá trị</span><span>${mil(p.value)}</span></div>
          <div><span>Ngày mua</span><span>${dmy(p.entry_date)}</span></div><div><span>Đã giữ</span><span>${p.bars} phiên</span></div>
          <div><span>${p.strategy === "BREAKOUT" ? "Stop -8%" : "Cắt lỗ -5%"}</span><span class="down">${vnd(p.stop)}</span></div>
          <div><span>${p.strategy === "BREAKOUT" ? "Trailing ATR" : "Chốt lời"}</span><span class="${p.strategy === "BREAKOUT" ? "down" : "up"}">${vnd(p.strategy === "BREAKOUT" ? p.trail : p.take_profit)}</span></div>
        </div>
        <div class="range"><div class="range-track">
            <span class="mk" style="left:${posOf(p.entry_price)}%;background:var(--muted)" title="Giá vốn"></span>
            <span class="mk" style="left:${posOf(p.price)}%;background:var(--text)" title="Giá hiện tại"></span></div>
          <div class="range-lbl"><span class="down">thoát ${vnd(lo)}</span><span>${p.sellable ? "đã về hàng" : "chờ T+2"}</span><span class="${p.take_profit ? "up" : "muted"}">${p.take_profit ? "chốt " + vnd(hi) : "để lãi chạy"}</span></div>
        </div></div>`;
    }).join("")}</div>`;
    $("#positions").querySelectorAll(".pos").forEach((el) => (el.onclick = () => openTicker(el.dataset.tk)));
  }

  // ------------------------------------------------------------ HISTORY
  const tradeCols = [
    { k: "ticker", t: "Mã", f: (r) => `<span class="tk">${r.ticker}</span>` },
    { k: "strategy", t: "Chiến lược", f: (r) => `<span class="strat strat-${r.strategy}">${STRAT[r.strategy]}</span>` },
    { k: "entry_date", t: "Mua", f: (r) => dmy(r.entry_date) },
    { k: "entry_price", t: "Giá mua", num: 1, f: (r) => vnd(r.entry_price) },
    { k: "exit_date", t: "Bán", f: (r) => dmy(r.exit_date) },
    { k: "exit_price", t: "Giá bán", num: 1, f: (r) => vnd(r.exit_price) },
    { k: "qty", t: "KL", num: 1, f: (r) => vnd(r.qty) },
    { k: "bars", t: "Phiên", num: 1 },
    { k: "fees", t: "Phí+thuế", num: 1, sv: (r) => r.buy_fee + r.sell_fee + r.tax, f: (r) => vnd(r.buy_fee + r.sell_fee + r.tax) },
    { k: "pnl", t: "Lãi/lỗ ròng", num: 1, f: (r) => `<span class="${cls(r.pnl)}">${(r.pnl > 0 ? "+" : "") + vnd(r.pnl)}</span>` },
    { k: "ret", t: "%", num: 1, f: (r) => `<span class="${cls(r.ret)}">${pct(r.ret)}</span>` },
    { k: "reason_vn", t: "Lý do thoát" },
  ];
  function renderHistory() {
    const tr = S.live.trades || [];
    const tot = tr.reduce((a, t) => a + t.pnl, 0);
    $("#tr-sum").innerHTML = tr.length ? `${tr.length} lệnh · tổng <b class="${cls(tot)}">${(tot > 0 ? "+" : "") + vnd(tot)}đ</b>` : "";
    table($("#trades-table"), tradeCols, tr, { sort: "exit_date", empty: "Chưa có lệnh nào đóng." });
    table($("#orders-table"), [
      { k: "date", t: "Ngày", f: (r) => dmy(r.date) },
      { k: "side", t: "Lệnh", f: (r) => `<span class="act-tag act-${r.side}">${r.side}</span>` },
      { k: "ticker", t: "Mã", f: (r) => `<span class="tk">${r.ticker}</span>` },
      { k: "qty", t: "KL", num: 1, f: (r) => vnd(r.qty) },
      { k: "price", t: "Giá khớp", num: 1, f: (r) => vnd(r.price) },
      { k: "value", t: "Giá trị", num: 1, f: (r) => vnd(r.value) },
      { k: "fee", t: "Phí", num: 1, f: (r) => vnd(r.fee) },
      { k: "tax", t: "Thuế", num: 1, f: (r) => vnd(r.tax) },
      { k: "net", t: "Tiền ròng", num: 1, f: (r) => `<span class="${cls(r.net)}">${vnd(r.net)}</span>` },
      { k: "note", t: "Ghi chú", f: (r) => `<span class="note">${esc(r.note)}</span>` },
    ], S.live.orders || [], { sort: "date", empty: "Chưa có lệnh nào." });
  }

  // ------------------------------------------------------------ BACKTEST
  function renderBacktest() {
    const B = S.bt;
    if (!B || !B.metrics || !B.metrics.start) { $("#bt-metrics").innerHTML = `<div class="empty">Chưa có kết quả backtest.</div>`; return; }
    const m = B.metrics;
    $("#bt-range").textContent = `· ${dmy(m.start)} → ${dmy(m.end)}`;
    const items = [
      ["Lợi nhuận", pct(m.total_return), cls(m.total_return)], ["VNINDEX", pct(m.benchmark_return), cls(m.benchmark_return)],
      ["Vượt trội", pct(m.alpha), cls(m.alpha)], ["CAGR", pct(m.cagr), cls(m.cagr)],
      ["Max drawdown", pct(m.max_drawdown), "down"], ["MDD VNINDEX", pct(m.benchmark_max_dd), "down"],
      ["Sharpe", num(m.sharpe, 2), ""], ["Số lệnh", m.n_trades, ""],
      ["Tỷ lệ thắng", pct(m.win_rate, 1, false), ""], ["Profit factor", num(m.profit_factor, 2), ""],
      ["Lãi TB lệnh thắng", pct(m.avg_win), "up"], ["Lỗ TB lệnh thua", pct(m.avg_loss), "down"],
      ["Giữ TB", num(m.avg_bars, 0) + " phiên", ""], ["NAV cuối", mil(m.nav), ""],
      ["Tổng phí", mil(m.total_fees), ""], ["Tổng thuế", mil(m.total_tax), ""],
    ];
    $("#bt-metrics").innerHTML = items.map(([k, v, c]) => `<div class="metric"><div class="label">${k}</div><div class="mv mono ${c}">${v}</div></div>`).join("");

    const st = m.by_strategy || {};
    const maxAbs = Math.max(1, ...Object.values(st).map((x) => Math.abs(x.pnl)));
    $("#bt-strat").innerHTML = Object.entries(st).map(([k, x]) => `<div class="hbar"><div><span class="strat strat-${k}">${STRAT[k]}</span> <span class="muted small">${x.n} lệnh · thắng ${pct(x.wins / x.n, 0, false)}</span></div>
      <div class="tr"><i style="width:${Math.abs(x.pnl) / maxAbs * 100}%;background:${x.pnl >= 0 ? "var(--up)" : "var(--down)"}"></i></div><div class="mono small ${cls(x.pnl)}" style="text-align:right">${mil(x.pnl)}</div></div>`).join("") || `<div class="empty">—</div>`;
    const rs = m.by_reason || {}, tot = Object.values(rs).reduce((a, b) => a + b, 0) || 1;
    $("#bt-reason").innerHTML = Object.entries(rs).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div class="hbar"><div>${k}</div><div class="tr"><i style="width:${v / tot * 100}%"></i></div><div class="mono small" style="text-align:right">${v} (${pct(v / tot, 0, false)})</div></div>`).join("");
    renderMonthly();
    table($("#bt-trades"), tradeCols, B.trades || [], { sort: "exit_date" });
  }
  function renderMonthly() {
    const h = S.bt.nav_history || [];
    const last = {};
    h.forEach((x) => (last[x.date.slice(0, 7)] = x.nav));
    const keys = Object.keys(last).sort();
    const ret = {};
    let prev = S.bt.config.initial_capital;
    keys.forEach((k) => { ret[k] = last[k] / prev - 1; prev = last[k]; });
    const years = [...new Set(keys.map((k) => k.slice(0, 4)))];
    const color = (r) => { if (r == null) return ""; const a = Math.min(Math.abs(r) / 0.08, 1); return `background:${r >= 0 ? css("--up") : css("--down")}${Math.round(a * 0x66 + 0x10).toString(16).padStart(2, "0")}`; };
    let html = `<table class="tbl heat"><thead><tr><th>Năm</th>${Array.from({ length: 12 }, (_, i) => `<th>T${i + 1}</th>`).join("")}<th>Năm</th></tr></thead><tbody>`;
    years.forEach((y) => {
      let yr = 1;
      html += `<tr><td><b>${y}</b></td>`;
      for (let i = 1; i <= 12; i++) { const k = `${y}-${String(i).padStart(2, "0")}`; const r = ret[k]; if (r != null) yr *= 1 + r; html += `<td style="${color(r)}">${r == null ? "" : pct(r, 1)}</td>`; }
      html += `<td style="${color(yr - 1)}"><b>${pct(yr - 1, 1)}</b></td></tr>`;
    });
    $("#bt-monthly").innerHTML = html + "</tbody></table>";
  }
  function renderBtCharts() {
    const h = S.bt?.nav_history || [];
    if (h.length < 2) return;
    const ch = baseChart($("#bt-chart"), { priceFormatter: (p) => mil(p) });
    const a = ch.addAreaSeries({ lineColor: css("--up"), topColor: css("--up") + "40", bottomColor: css("--up") + "00", lineWidth: 2, title: "NAV" });
    a.setData(h.map((x) => ({ time: x.date, value: x.nav })));
    const v0 = (h.find((x) => x.vnindex) || {}).vnindex, cap = S.bt.config.initial_capital;
    if (v0) { const b = ch.addLineSeries({ color: css("--muted"), lineWidth: 1.5, title: "VNINDEX (quy đổi)" }); b.setData(h.filter((x) => x.vnindex).map((x) => ({ time: x.date, value: cap * x.vnindex / v0 }))); }
    fit(ch);
    const dd = baseChart($("#bt-dd"), { priceFormatter: (p) => p.toFixed(0) + "%" });
    let peak = 0;
    const s = dd.addAreaSeries({ lineColor: css("--down"), topColor: css("--down") + "00", bottomColor: css("--down") + "55", lineWidth: 1, title: "Drawdown" });
    s.setData(h.map((x) => { peak = Math.max(peak, x.nav); return { time: x.date, value: (x.nav / peak - 1) * 100 }; }));
    fit(dd);
    ch.timeScale().subscribeVisibleLogicalRangeChange((r) => r && dd.timeScale().setVisibleLogicalRange(r));
  }

  // ------------------------------------------------------------ TICKER MODAL
  async function openTicker(tk) {
    if (!S.charts) S.charts = await getJSON("data/charts.json");
    const c = S.charts?.[tk];
    if (!c) return;
    $("#modal").classList.remove("hidden");
    const { board } = currentBoard();
    const b = board.find((x) => x.ticker === tk) || {};
    const pos = (S.live.positions || []).find((p) => p.ticker === tk);
    $("#m-title").innerHTML = `${tk} <span class="act-tag act-${b.action || "CHỜ"}">${b.action || ""}</span> <span class="muted small">${esc(b.action_note || "")}</span>`;
    const pills = [
      ["Giá", vnd(b.close)], ["RSI14", num(b.rsi)], ["MA10", vnd(b.ma10)], ["MA50", vnd(b.ma50)], ["ATR14", vnd(b.atr)],
      ["Đỉnh 55 phiên", vnd(b.hh55)], ["ROC60", pct(b.roc60, 1)], ["Mốc Breakout", vnd(b.breakout_trigger)], ["Mốc RSI≤30", vnd(b.rsi_trigger)],
    ];
    $("#m-stats").innerHTML = pills.map(([k, v]) => `<span class="pill"><span class="muted">${k}</span> <b class="mono">${v}</b></span>`).join("");
    const T = (i) => c.d[i];
    const ch = baseChart($("#m-chart"));
    const cs = ch.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false });
    cs.setData(c.d.map((d, i) => ({ time: d, open: c.open[i], high: c.high[i], low: c.low[i], close: c.close[i] })));
    const line = (key, color, w = 1.5, style = 0) => { const s = ch.addLineSeries({ color, lineWidth: w, lineStyle: style, priceLineVisible: false, lastValueVisible: false }); s.setData(c.d.map((d, i) => c[key]?.[i] == null ? null : { time: d, value: c[key][i] }).filter(Boolean)); };
    line("ma10", "#f59e0b"); line("ma50", "#38bdf8"); line("hh55", "#a78bfa", 1, 2);
    const vol = ch.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, color: css("--line-2"), lastValueVisible: false, priceLineVisible: false });
    ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(c.d.map((d, i) => ({ time: d, value: c.volum?.[i] || 0, color: c.close[i] >= c.open[i] ? css("--up") + "55" : css("--down") + "55" })));
    if (pos) {
      const pl = (p, color, title) => p && cs.createPriceLine({ price: p, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title });
      pl(pos.entry_price, css("--muted"), "Giá vốn"); pl(pos.exit_level, css("--down"), "Thoát"); pl(pos.take_profit, css("--up"), "Chốt lời");
    } else if (b.breakout_trigger) {
      cs.createPriceLine({ price: b.breakout_trigger, color: "#a78bfa", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Mốc Breakout" });
    }
    const set = new Set(c.d);
    const mk = (S.live.orders || []).filter((o) => o.ticker === tk && set.has(o.date)).map((o) => ({ time: o.date, position: o.side === "MUA" ? "belowBar" : "aboveBar", color: o.side === "MUA" ? css("--up") : css("--down"), shape: o.side === "MUA" ? "arrowUp" : "arrowDown", text: `${o.side} ${vnd(o.price)}` }));
    cs.setMarkers(mk);
    ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, c.d.length - 140), to: c.d.length + 3 });
    const rc = baseChart($("#m-rsi"), { priceFormatter: (p) => p.toFixed(0) });
    const rs = rc.addLineSeries({ color: css("--accent"), lineWidth: 1.5, title: "RSI14" });
    rs.setData(c.d.map((d, i) => c.rsi?.[i] == null ? null : { time: d, value: c.rsi[i] }).filter(Boolean));
    rs.createPriceLine({ price: 30, color: css("--up"), lineStyle: 2, lineWidth: 1, title: "30" });
    rs.createPriceLine({ price: 70, color: css("--down"), lineStyle: 2, lineWidth: 1, title: "70" });
    ch.timeScale().subscribeVisibleLogicalRangeChange((r) => r && rc.timeScale().setVisibleLogicalRange(r));
    rc.timeScale().setVisibleLogicalRange({ from: Math.max(0, c.d.length - 140), to: c.d.length + 3 });
    void T;
  }
  function closeModal() { $("#modal").classList.add("hidden"); }

  // ------------------------------------------------------------ RULES
  function renderRules() {
    const f = S.live.fees || {};
    $("#rules").innerHTML = `
      <h3>Cơ chế giả lập</h3>
      <p>Vốn gốc <b>${mil(S.live.initial_capital)}</b>, bắt đầu ${dmy(S.live.start_date)}. Mỗi ngày giao dịch hệ thống tính tín hiệu lúc ~14:25 (giá trong phiên) để bạn kịp đặt lệnh <b>ATC</b>, rồi chốt sổ lúc ~15:15: lệnh giấy khớp đúng <b>giá đóng cửa</b>.</p>
      <table><tr><th>Phí môi giới mua</th><td>${pct(f.buy_fee, 2, false)}</td></tr><tr><th>Phí môi giới bán</th><td>${pct(f.sell_fee, 2, false)}</td></tr>
      <tr><th>Thuế TNCN khi bán</th><td>${pct(f.sell_tax, 2, false)} giá trị bán</td></tr><tr><th>Lô giao dịch</th><td>100 cổ phiếu (HOSE)</td></tr>
      <tr><th>Thanh toán</th><td>T+2: mua phiên T, được bán từ phiên T+2</td></tr><tr><th>Tỷ trọng mỗi mã</th><td>NAV/5, làm tròn xuống lô 100</td></tr></table>
      <h3>1. Bộ lọc thị trường (VNINDEX)</h3>
      <p>Chỉ chặn lệnh mới, không ép bán. Breakout cần VNINDEX &gt; MA50; Sideway cần VNINDEX &gt; MA200. Không có dữ liệu VNINDEX → không mở lệnh mới.</p>
      <h3>2. Breakout (Donchian 55)</h3>
      <p><b>Mua</b> khi đủ 4 điều kiện: đóng cửa &gt; đỉnh 55 phiên trước · giá &gt; MA50 · MA10 &gt; MA50 · VNINDEX &gt; MA50.<br>
      <b>Bán</b> khi chạm điều kiện nào trước: giá ≤ giá mua −8% · giá ≤ đỉnh (giá đóng cửa cao nhất) sau khi mua − 4×ATR(14) · giữ đủ 365 phiên. Không chốt lời cố định.</p>
      <h3>3. Sideway (RSI quá bán)</h3>
      <p><b>Mua</b> khi RSI(14) ≤ 30 và VNINDEX &gt; MA200. |MA10−MA50|/MA50 &lt; 5% → “NÊN MUA” (ưu tiên cao); ngược lại “QUÁ BÁN – LƯỚT T+” (ưu tiên thấp).<br>
      <b>Bán</b>: chốt lời khi lãi ≥ +6,5% · cắt lỗ khi lỗ ≥ −5% (so với giá mua).</p>
      <h3>4. Xếp hạng & giới hạn</h3>
      <table><tr><th>Breakout</th><td>300 + ROC60×100</td></tr><tr><th>Sideway chuẩn</th><td>100 + (30 − RSI)</td></tr><tr><th>Sideway T+</th><td>50 + (30 − RSI)</td></tr></table>
      <p>Lấy top 5 tín hiệu, mua theo thứ tự điểm cho tới khi đủ tối đa <b>5 mã</b> trong danh mục. Mã vừa bán trong ngày không mua lại cùng ngày.</p>
      <h3>Lưu ý</h3>
      <p class="muted">Giá dùng là giá đã điều chỉnh quyền; khi có cổ tức/chia tách, hệ thống tự điều chỉnh giá vốn & số lượng tương ứng. Backtest dùng danh sách VN30 hiện tại nên có thiên lệch sống sót (survivorship bias). Đây là công cụ cá nhân để kiểm chứng chiến lược, không phải khuyến nghị đầu tư.</p>`;
  }

  // ------------------------------------------------------------ wiring
  function renderCharts() {
    S.charts_.forEach((c) => { try { c.remove(); } catch {} });
    S.charts_ = [];
    renderSpark(); renderEquity();
    if (!$("#tab-backtest").classList.contains("hidden")) renderBtCharts();
  }
  function bind() {
    $("#tabs").querySelectorAll("button").forEach((b) => (b.onclick = () => {
      $("#tabs").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("hidden", t.id !== "tab-" + b.dataset.tab));
      if (b.dataset.tab === "backtest") renderBtCharts();
      if (b.dataset.tab === "overview") renderEquity();
      try { history.replaceState(null, "", "#" + b.dataset.tab); } catch {}
    }));
    $("#eq-src").querySelectorAll("button").forEach((b) => (b.onclick = () => {
      $("#eq-src").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      S.eqSrc = b.dataset.v; renderEquity();
    }));
    $("#sig-filter").querySelectorAll("button").forEach((b) => (b.onclick = () => {
      $("#sig-filter").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      S.sigFilter = b.dataset.v; renderSignals();
    }));
    $("#m-close").onclick = closeModal;
    $("#modal").onclick = (e) => e.target.id === "modal" && closeModal();
    document.addEventListener("keydown", (e) => e.key === "Escape" && closeModal());
    const h = location.hash.slice(1);
    if (h) { const b = $(`#tabs button[data-tab="${h}"]`); if (b) b.click(); }
  }

  async function main() {
    initTheme(); tickClock(); setInterval(tickClock, 30000);
    const [live, bt, preview] = await Promise.all([getJSON("data/live.json"), getJSON("data/backtest.json"), getJSON("data/preview.json")]);
    if (!live) {
      document.querySelector("main").innerHTML = `<div class="card empty">Chưa có dữ liệu. Hãy chạy workflow “Daily VN30 update” trên GitHub Actions (xem README).</div>`;
      return;
    }
    Object.assign(S, { live, bt, preview });
    if (S.live.nav_history?.length < 2 && bt) S.eqSrc = "bt", $("#eq-src").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x.dataset.v === "bt"));
    renderHero(); renderActions(); renderMarket(); renderAlloc(); renderWatch();
    renderSignals(); renderPositions(); renderHistory(); renderBacktest(); renderRules();
    renderCharts(); bind();
  }
  main();
})();
