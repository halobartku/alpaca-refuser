/* alpaca-refuser hosted demo — a faithful JavaScript port of refuser/gates.py,
 * refuser/universe.py, refuser/portfolio.py, bs.size_contracts and the
 * DecisionLog hash chain (refuser/log.py / verify.py).
 *
 * Parity is ENFORCED by tools/parity_test.py: the same cases are run through
 * Python evaluate_intent() and this file (node CLI), and decision, contracts
 * and every gate detail string must match byte-for-byte. If you change the
 * rules, change both sides and re-run the battery.
 *
 * Works in the browser (window.REFUSER) and in node (module.exports + CLI):
 *   node demo.js eval   < case.json    -> result JSON on stdout
 *   node demo.js verify < log.jsonl    -> CHAIN OK / CHAIN BROKEN
 *   node demo.js selftest              -> internal consistency checks
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.REFUSER = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // --- presented parameters (mirror gates.py; keep in lockstep) ------------
  var RISK_PER_TRADE = 0.0075;
  var MAX_CONCURRENT = 6;
  var MAX_PORTFOLIO_HEAT = 0.09;
  var MAX_NET_DELTA_ABS = 30; // $100k anchor; live cap scales with equity

  // --- universe (mirror universe.py) ---------------------------------------
  var UNIVERSE = { SPY: null, QQQ: null, IWM: null, AAPL: null, MSFT: null,
                   XOM: null, KO: null, PFE: null };
  // naive ET datetimes, ISO strings for portability
  var EVENT_BLACKOUTS = [["2026-09-03T15:55:00", "2026-09-04T12:00:00"]];
  var ENTRY_DAYS = { 0: true, 2: true }; // Mon=0, Wed=2

  var BETA_GROUPS = {
    index_beta: ["SPY", "QQQ", "IWM"],
    mega_tech: ["AAPL", "MSFT"],
    energy: ["XOM"],
    staples: ["KO"],
    pharma: ["PFE"]
  };
  var MAX_PER_GROUP = 2;
  var GROUP_INDEX = {};
  Object.keys(BETA_GROUPS).forEach(function (g) {
    BETA_GROUPS[g].forEach(function (n) { GROUP_INDEX[n] = g; });
  });

  // --- formatting helpers (Python f-string / %g equivalents) ---------------
  function f2(x) { return Number(x).toFixed(2); }
  function f3(x) { return Number(x).toFixed(3); }
  function f1s(x) { return (x < 0 ? "-" : "+") + Math.abs(x).toFixed(1); }
  function g6(x) { // Python '%g' for the magnitudes a net-delta cap can take
    if (!isFinite(x)) return String(x);
    var s = Number(x).toPrecision(6);
    if (s.indexOf("e") === -1) {
      s = s.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    }
    return s;
  }

  // --- dates ----------------------------------------------------------------
  function parseDate(s) { // "YYYY-MM-DD" -> {y,m,d,utc}
    var p = s.split("-");
    return { y: +p[0], m: +p[1], d: +p[2], utc: Date.UTC(+p[0], +p[1] - 1, +p[2]) };
  }
  function dte(expiryStr, todayStr) {
    return Math.round((parseDate(expiryStr).utc - parseDate(todayStr).utc) / 86400000);
  }
  function parseNaive(s) { // "YYYY-MM-DD[THH:MM[:SS]]" -> comparable number
    var p = s.split("T");
    var d = parseDate(p[0]);
    var t = (p[1] || "00:00:00").split(":");
    return d.utc + (+t[0]) * 3600000 + (+t[1]) * 60000 + (+(t[2] || 0)) * 1000;
  }

  // --- universe gates -------------------------------------------------------
  function inEntryWindow(nowIso) {
    // Python weekday(): Mon=0. JS getUTCDay(): Sun=0 -> convert.
    var wd = (new Date(parseDate(nowIso.split("T")[0]).utc).getUTCDay() + 6) % 7;
    if (!ENTRY_DAYS[wd]) return false;
    var hm = nowIso.split("T")[1];
    return "10:05" <= hm.slice(0, 5) && hm.slice(0, 5) <= "15:00";
  }
  function inEventBlackout(nowIso) {
    var t = parseNaive(nowIso);
    return EVENT_BLACKOUTS.some(function (w) {
      return parseNaive(w[0]) <= t && t <= parseNaive(w[1]);
    });
  }
  function earningsWithin(name, horizonDays, todayStr) {
    // static map is all-None in the shipped skeleton: known-date names report
    // no earnings in the window. Unknown name is refused by gate_calendar.
    var d = UNIVERSE[name];
    if (d === undefined) return null;
    if (d === null) return false;
    var t = parseDate(todayStr).utc;
    return t <= parseDate(d).utc &&
           parseDate(d).utc <= t + horizonDays * 86400000;
  }

  // --- individual gates (detail strings are the Python f-strings) ----------
  function gateDte(expiry, today) {
    var d = dte(expiry, today);
    return [21 <= d && d <= 35, "dte=" + d];
  }
  function gateShortDelta(delta) {
    var a = Math.abs(delta);
    return [0.15 <= a && a <= 0.25, "short_delta=" + f3(a)];
  }
  function gateWidthCredit(width, credit) {
    var okW = 1.0 <= width && width <= 5.0;
    var risk = width - credit;
    var okR = risk <= 4.50;
    var okC = credit >= 1.00 && credit >= 0.20 * width;
    return [okW && okR && okC,
      "width=" + f2(width) + " credit=" + f2(credit) + " risk=" + f2(risk)];
  }
  function gateLiquidity(aS, bS, aL, bL, credit, oiS, oiL) {
    var spS = aS - bS, spL = aL - bL;
    var ok = spS <= 0.35 * credit && spL <= 0.35 * credit &&
             oiS >= 1000 && oiL >= 1000;
    return [ok, "leg_spreads=" + f2(spS) + "/" + f2(spL) +
      " vs 35% of credit; OI=" + oiS + "/" + oiL];
  }
  function gateUnderlying(last) {
    return [last >= 40.0, "underlying_last=" + f2(last)];
  }
  function gateCalendar(name, nowIso, expiry) {
    if (!(name in UNIVERSE)) return [false, "name=" + name + " not in universe"];
    if (inEventBlackout(nowIso)) return [false, "event blackout window (NFP stand-down)"];
    if (!inEntryWindow(nowIso)) return [false, "outside Mon/Wed 10:05-15:00 ET entry window"];
    var hz = dte(expiry, nowIso.split("T")[0]) + 3;
    var e = earningsWithin(name, hz, nowIso.split("T")[0]);
    if (e === null) return [false, "earnings date for " + name + " UNKNOWN -> fail-closed refusal"];
    if (e) return [false, "earnings inside DTE+3 for " + name];
    return [true, "calendar ok"];
  }
  function gateIv(atmIv, spyIv, spy5d) {
    return [atmIv >= 0.18 && spyIv >= spy5d,
      "atm_iv=" + f3(atmIv) + " spy_iv=" + f3(spyIv) + " 5d_avg=" + f3(spy5d)];
  }
  function groupOf(name) {
    if (!(name in GROUP_INDEX)) throw new Error(name + " not in universe — cannot be scored");
    return GROUP_INDEX[name];
  }
  function gateGroup(state, name) {
    var g;
    try { g = groupOf(name); }
    catch (e) { return [false, name + " not in universe — cannot be grouped"]; }
    var held = state.positions_by_name.filter(function (n) {
      return groupOf(n) === g;
    });
    var ok = held.length < MAX_PER_GROUP;
    return [ok, "group " + g + " holds " + held.length + "/" + MAX_PER_GROUP +
      " (" + (held.join(", ") || "none") + ")"];
  }
  function netDeltaCap(equity) {
    if (equity <= 0) return 0.0;
    return equity / (100000.0 / 30);
  }
  function gateNetDelta(state, spreadDelta, contracts, cap) {
    if (cap === undefined || cap === null) cap = netDeltaCap(state.equity);
    var p = state.net_delta + spreadDelta * contracts * 100.0;
    var ok = Math.abs(p) <= cap + 1e-6;
    return [ok, "projected net delta " + f1s(p) + " vs cap +/-" + g6(cap)];
  }
  function gatePortfolio(state, name) {
    if (state.daily_stop_hit)
      return [false, "daily stop hit — no new entries today"];
    if (state.open_positions >= MAX_CONCURRENT)
      return [false, state.open_positions + " open >= " + MAX_CONCURRENT + " slots"];
    if (state.positions_by_name.indexOf(name) !== -1)
      return [false, "already hold a position in " + name];
    var heat = state.equity > 0 ? state.risk_at_open / state.equity : 1.0;
    if (heat + RISK_PER_TRADE > MAX_PORTFOLIO_HEAT)
      return [false, "heat " + f3(heat) + "+" + RISK_PER_TRADE +
        " would exceed " + MAX_PORTFOLIO_HEAT];
    var g = gateGroup(state, name);
    if (!g[0]) return [false, "correlation: " + g[1]];
    return [true, "portfolio ok"];
  }
  function sizeContracts(equity, riskPerTrade, width, credit) {
    var per = (width - credit) * 100.0;
    if (per <= 0) return 0;
    return Math.floor(equity * riskPerTrade / per);
  }

  // --- the full stack (order mirrors evaluate_intent exactly) --------------
  function evaluateIntent(intent, state, market) {
    var results = [];
    function run(label, fn) {
      var r = fn();
      results.push({ gate: label, pass: r[0], detail: r[1] });
    }
    run("dte", function () { return gateDte(intent.expiry, state.today); });
    run("short_delta", function () { return gateShortDelta(intent.short_delta); });
    run("width_credit", function () { return gateWidthCredit(intent.width, intent.credit); });
    run("liquidity", function () {
      return gateLiquidity(intent.ask_short, intent.bid_short,
        intent.ask_long, intent.bid_long, intent.credit,
        intent.oi_short, intent.oi_long);
    });
    run("underlying", function () { return gateUnderlying(market.underlying_last); });
    run("calendar", function () { return gateCalendar(intent.name, state.now, intent.expiry); });
    run("iv", function () { return gateIv(market.atm_iv, market.spy_atm_iv, market.spy_iv_5d_avg); });
    run("portfolio", function () { return gatePortfolio(state, intent.name); });

    var n = sizeContracts(state.equity, RISK_PER_TRADE, intent.width, intent.credit);
    if (n < 1) results.push({ gate: "sizing", pass: false,
      detail: "0 contracts at 0.75% risk -> refusal" });
    if (n >= 1 && intent.spread_delta !== undefined)
      run("net_delta", function () { return gateNetDelta(state, intent.spread_delta, n); });

    var accepted = results.every(function (r) { return r.pass; });
    return { decision: accepted ? "ACCEPT" : "REFUSE", gates: results, contracts: n };
  }

  // --- hash-chained decision log (mirror log.py canonical form) ------------
  // Python hashes sha256(prev + json.dumps(body, sort_keys=True)) where
  // json.dumps uses the DEFAULT separators (", " and ": ").
  function canonical(v) {
    if (v === null || v === undefined) return "null";
    if (typeof v === "number") return String(v);
    if (typeof v === "boolean") return v ? "true" : "false";
    if (typeof v === "string") return JSON.stringify(v);
    if (Array.isArray(v)) return "[" + v.map(canonical).join(", ") + "]";
    var keys = Object.keys(v).sort();
    return "{" + keys.map(function (k) {
      return JSON.stringify(k) + ": " + canonical(v[k]);
    }).join(", ") + "}";
  }
  async function sha256hex(s) {
    var buf = new TextEncoder().encode(s);
    var h = await crypto.subtle.digest("SHA-256", buf);
    return Array.prototype.map.call(new Uint8Array(h), function (b) {
      return ("0" + b.toString(16)).slice(-2);
    }).join("");
  }
  // Records on disk are full-line json; only the BODY is canonicalized.
  async function verifyChain(text) {
    var lines = text.split("\n").filter(function (l) { return l.trim(); });
    var head = "GENESIS", n = 0, err = null;
    for (var i = 0; i < lines.length; i++) {
      var rec;
      try { rec = JSON.parse(lines[i]); }
      catch (e) { err = "line " + i + " is not JSON: " + e.message; break; }
      if (rec.prev !== head) { err = "chain broken at line " + n +
        ": prev " + rec.prev + " != head " + head; break; }
      var expect = await sha256hex(head + canonical(rec.body));
      if (rec.hash !== expect) { err = "chain broken at line " + n +
        ": hash mismatch (body mutated?)"; break; }
      head = rec.hash; n++;
    }
    return err
      ? { ok: false, error: err, records: n, head: head.slice(0, 16) }
      : { ok: true, records: n, head: head.slice(0, 16) };
  }
  async function appendDecision(records, body) {
    // records: array of body dicts already in the chain; returns new record
    var head = "GENESIS", n = 0;
    for (var i = 0; i < records.length; i++) {
      head = records[i].hash; n++;
    }
    var hash = await sha256hex(head + canonical(body));
    var rec = { seq: n, ts: Date.now() / 1000, prev: head, body: body, hash: hash };
    return rec;
  }

  return {
    RISK_PER_TRADE: RISK_PER_TRADE, MAX_CONCURRENT: MAX_CONCURRENT,
    MAX_PORTFOLIO_HEAT: MAX_PORTFOLIO_HEAT, MAX_NET_DELTA_ABS: MAX_NET_DELTA_ABS,
    UNIVERSE: UNIVERSE, BETA_GROUPS: BETA_GROUPS, MAX_PER_GROUP: MAX_PER_GROUP,
    evaluateIntent: evaluateIntent, sizeContracts: sizeContracts,
    gateDte: gateDte, gateShortDelta: gateShortDelta,
    gateWidthCredit: gateWidthCredit, gateLiquidity: gateLiquidity,
    gateUnderlying: gateUnderlying, gateCalendar: gateCalendar,
    gateIv: gateIv, gatePortfolio: gatePortfolio, gateGroup: gateGroup,
    gateNetDelta: gateNetDelta, netDeltaCap: netDeltaCap,
    canonical: canonical, verifyChain: verifyChain, appendDecision: appendDecision,
    sha256hex: sha256hex
  };
});

// --- node CLI (parity harness + humans): eval / verify ---------------------
if (typeof require !== "undefined" && require.main === module) {
  var fs = require("fs");
  var R = module.exports;
  (async function () {
    var mode = process.argv[2];
    if (mode === "eval") {
      var input = JSON.parse(fs.readFileSync(0, "utf8"));
      var out = R.evaluateIntent(input.intent, input.state, input.market);
      process.stdout.write(JSON.stringify(out));
    } else if (mode === "verify") {
      var text = fs.readFileSync(process.argv[3] || 0, "utf8");
      var v = await R.verifyChain(text);
      process.stdout.write(JSON.stringify(v));
      process.exit(v.ok ? 0 : 1);
    } else if (mode === "sha") {
      process.stdout.write(await R.sha256hex(fs.readFileSync(0, "utf8")));
    } else {
      console.error("usage: node demo.js eval < case.json | verify <log.jsonl> | sha");
      process.exit(2);
    }
  })().catch(function (e) { console.error(e.stack || e); process.exit(1); });
}
