/* Renders the DSR console from window.PRP_DATA (written by demo/build.py from real API output). */
(function () {
  "use strict";

  var D = window.PRP_DATA;
  var DAY = 86400000;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var COLORS = {
    navy: "#1f3d63", navy2: "#2f5687", sand: "#d9c6a0", ok: "#3b7651", warn: "#a8670f",
    bad: "#a3392b", grey: "#8d8576", line: "#e4dccb", ink: "#23272e", muted: "#776f61", track: "#efe8da"
  };
  var LABEL = {
    gdpr: "GDPR", ccpa: "CCPA", access: "Access", deletion: "Deletion", correction: "Correction",
    opt_out: "Opt-out", received: "Received", verifying: "Verifying", verified: "Verified",
    in_progress: "In progress", extended: "Extended", fulfilled: "Fulfilled", denied: "Denied",
    on_time: "On time", at_risk: "At risk", breached: "Breached", met: "Met", missed: "Missed",
    pending: "Pending", confirmed: "Confirmed", failed: "Failed", exempt: "Exempt"
  };
  var ACTION = {
    "request.received": "Request received",
    "notice.acknowledgement_sent": "Acknowledgement sent",
    "verification.challenge_issued": "Verification code issued",
    "verification.passed": "Identity verified",
    "verification.failed": "Verification attempt failed",
    "verification.expired": "Code expired",
    "request.status_changed": "Status changed",
    "fanout.dispatched": "Dispatched to system",
    "fanout.confirmed": "System confirmed",
    "fanout.failed": "System reported failure",
    "fanout.retried": "Retried",
    "fanout.exempted": "Exemption recorded",
    "notice.completion_sent": "Completion notice sent",
    "notice.extension_sent": "Extension notice sent",
    "notice.denial_sent": "Denial notice sent",
    "consent.changed": "Consent changed",
    "request.contact_redacted": "Contact email redacted"
  };
  var FEATURED = [
    ["G1", "Deletion, fulfilled with exemption"],
    ["G8", "Breached: vendor lag"],
    ["G4", "Extended after failure"],
    ["C1", "CCPA deletion at risk"],
    ["C2", "Opt-out of sale/sharing"],
    ["G7", "Verification lockout"],
    ["C7", "Account mismatch"]
  ];

  var systems = {};
  D.systems.forEach(function (s) { systems[s.key] = s; });
  var asOf = parse(D.as_of);
  var selected = null;

  // ------------------------------------------------------------------ utils
  function parse(s) { return s ? new Date(s.length <= 10 ? s + "T00:00:00Z" : s + (s.endsWith("Z") ? "" : "Z")) : null; }
  function fmtD(d) { return d ? MONTHS[d.getUTCMonth()] + " " + d.getUTCDate() : "-"; }
  function fmtDY(d) { return d ? fmtD(d) + ", " + d.getUTCFullYear() : "-"; }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function fmtDT(d) { return d ? fmtD(d) + " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) : "-"; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function lab(k) { return LABEL[k] || k; }
  function chip(cls, text) { return '<span class="chip ' + esc(cls) + '">' + esc(text) + "</span>"; }
  function $(id) { return document.getElementById(id); }
  function days(a, b) { return Math.round((b - a) / DAY); }

  // ------------------------------------------------------------------ header + KPIs
  function renderHeader() {
    $("asof").textContent = "As of " + fmtDY(asOf) + " " + pad(asOf.getUTCHours()) + ":00 UTC";
    var v = D.audit_verify;
    var el = $("chain");
    el.textContent = v.ok
      ? "Audit chain verified: " + v.events + " events, head " + v.head.slice(0, 8)
      : "Audit chain FAILED at event " + v.first_bad_seq;
    el.className = "chain" + (v.ok ? " ok" : "");
  }

  function renderKpis() {
    var db = D.dashboard;
    var s = db.open_sla;
    var open = s.on_time + s.at_risk + s.breached;
    var closed = db.closed.length;
    var met = db.closed.filter(function (r) { return r.sla === "met"; }).length;
    var w = 100;
    var bar =
      '<svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">' +
      seg(0, s.on_time / open * w, COLORS.ok) +
      seg(s.on_time / open * w, s.at_risk / open * w, COLORS.warn) +
      seg((s.on_time + s.at_risk) / open * w, s.breached / open * w, COLORS.bad) + "</svg>";
    function seg(x, wd, c) { return wd > 0 ? '<rect x="' + x + '" y="0" width="' + wd + '" height="10" fill="' + c + '"/>' : ""; }
    var items = [
      ["", "Open requests", open, bar],
      ["ok", "On time", s.on_time, '<div class="hint">inside window</div>'],
      ["warn", "At risk", s.at_risk, '<div class="hint">final quarter or blocked</div>'],
      ["bad", "Breached", s.breached, '<div class="hint">past statutory due date</div>'],
      ["", "Closed on time", met + "/" + closed, '<div class="hint">' + Math.round(met / closed * 100) + "% of closed requests</div>"]
    ];
    $("kpis").innerHTML = items.map(function (k) {
      return '<div class="kpi ' + k[0] + '"><div class="label">' + k[1] + '</div><div class="value">' + k[2] + "</div>" + k[3] + "</div>";
    }).join("");
  }

  // ------------------------------------------------------------------ queue
  function qrow(r) {
    var left = r.days_remaining;
    var leftTxt = left == null ? (r.closed_at ? fmtD(parse(r.closed_at)) : "") : (left < 0 ? left + "d" : left + "d");
    var blocked = r.blocked_systems.length ? "Blocked: " + r.blocked_systems.join(", ") : (r.denial_reason ? r.denial_reason.replace(/_/g, " ") : "");
    return '<button class="qrow" data-id="' + esc(r.id) + '">' +
      '<span class="qid">' + esc(r.id) + "</span>" +
      '<span class="qtype">' + chip("rg", lab(r.regime)) + " " + esc(lab(r.type)) + (r.extended ? " <small>(ext.)</small>" : "") + "</span>" +
      '<span class="qstatus">' + chip("status", lab(r.status)) + "</span>" +
      '<span class="qsla">' + chip(r.sla, lab(r.sla)) + "</span>" +
      '<span class="qdue">' + fmtD(parse(r.due_date)) + "</span>" +
      '<span class="qleft' + (left != null && left < 0 ? " neg" : "") + '">' + esc(leftTxt) + "</span>" +
      '<span class="qblocked">' + esc(blocked) + "</span></button>";
  }

  function renderQueue() {
    $("queue-list").innerHTML = D.dashboard.queue.map(qrow).join("");
    $("closed-list").innerHTML = D.dashboard.closed.map(qrow).join("");
    $("closed-count").textContent = "(" + D.dashboard.closed.length + ")";
    Array.prototype.forEach.call(document.querySelectorAll(".qrow"), function (b) {
      b.addEventListener("click", function () {
        select(b.getAttribute("data-id"));
        $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  // ------------------------------------------------------------------ detail
  function renderFeatured() {
    $("featured").innerHTML = FEATURED.map(function (f) {
      var id = D.cases[f[0]];
      return '<button role="listitem" data-id="' + esc(id) + '" aria-pressed="false">' + esc(f[1]) + "</button>";
    }).join("");
    Array.prototype.forEach.call($("featured").querySelectorAll("button"), function (b) {
      b.addEventListener("click", function () { select(b.getAttribute("data-id")); });
    });
  }

  function select(id) {
    selected = id;
    Array.prototype.forEach.call(document.querySelectorAll(".qrow"), function (b) {
      b.classList.toggle("selected", b.getAttribute("data-id") === id);
    });
    Array.prototype.forEach.call($("featured").querySelectorAll("button"), function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-id") === id ? "true" : "false");
    });
    renderDetail();
  }

  function fact(k, v) { return '<div class="fact"><dt>' + esc(k) + "</dt><dd>" + v + "</dd></div>"; }

  function renderDetail() {
    var r = D.requests[selected];
    var ev = D.audit[selected];
    var extended = !!r.extended_at;
    var dueTxt = fmtDY(parse(r.due_at)) + (extended ? ' <span class="small">(was ' + fmtD(parse(r.original_due_at)) + ")</span>" : "");
    var contact = r.redacted_at ? '<span class="small">redacted ' + fmtD(parse(r.redacted_at)) + "</span>" : esc(r.contact_email_masked || "-");
    var outcome = r.denial_reason
      ? esc(r.denial_reason.replace(/_/g, " ")) + '<br><span class="small">' + esc(r.denial_detail) + "</span>"
      : (r.closed_at ? "Fulfilled " + fmtDT(parse(r.closed_at)) : "Open");
    var html =
      '<div class="dhead"><span class="did">' + esc(r.id) + "</span>" +
      chip("rg", lab(r.regime)) + chip("status", lab(r.request_type)) + chip("status", lab(r.status)) + chip(r.sla, lab(r.sla)) + "</div>" +
      '<dl class="facts">' +
      fact("Received", fmtDT(parse(r.received_at))) +
      fact("Verification tier", esc(r.verification_tier.replace("_", " "))) +
      fact("Verified", fmtDT(parse(r.verified_at))) +
      fact("Fulfillment started", fmtDT(parse(r.started_at))) +
      fact("Statutory due", dueTxt) +
      fact("Deadline basis", esc(r.deadline_basis)) +
      fact("Outcome", outcome) +
      fact("Contact", contact) +
      (extended ? fact("Extension reason", esc(r.extension_reason)) : "") +
      "</dl>" +
      '<div class="timeline" id="tl"></div>' +
      '<div class="legend">' +
      '<span><i style="background:' + COLORS.sand + '"></i>Verification</span>' +
      '<span><i style="background:' + COLORS.navy + '"></i>Case open</span>' +
      '<span><i style="background:' + COLORS.ok + '"></i>System confirmed</span>' +
      '<span><i style="background:#c9c1b1"></i>Awaiting system</span>' +
      '<span><i style="background:' + COLORS.bad + '"></i>Failure</span>' +
      '<span><i style="background:' + COLORS.grey + '"></i>Exempt</span>' +
      "</div>" +
      '<div class="dgrid"><div>' + tasksTable(r) + "</div><div>" + trail(ev) + "</div></div>";
    $("detail-body").innerHTML = html;
    drawTimeline(r, ev);
  }

  function tasksTable(r) {
    if (!r.tasks.length) {
      return '<h3 class="h3" style="margin-top:0">Downstream systems</h3><p class="small">No fan-out yet. Systems are only contacted after identity is verified and a case owner starts fulfillment.</p>';
    }
    var rows = r.tasks.map(function (t) {
      var s = systems[t.system_key] || {};
      var note = t.confirmation_ref ? '<span class="mono">' + esc(t.confirmation_ref) + "</span>" : esc(t.detail || "");
      if (t.status === "exempt" || t.status === "failed") note = esc(t.detail || "");
      return "<tr><td><b>" + esc(s.name || t.system_key) + '</b><br><span class="small">' + esc(s.owner || "") + (s.operated_by === "vendor" ? " (vendor)" : "") + "</span></td>" +
        "<td>" + esc(t.action) + "</td><td>" + chip(t.status, lab(t.status)) + (t.attempts > 1 ? '<br><span class="small">' + t.attempts + " attempts</span>" : "") + "</td>" +
        '<td class="num small">' + fmtD(parse(t.due_at)) + "</td>" +
        '<td class="small">' + (t.resolved_at ? fmtD(parse(t.resolved_at)) + "<br>" : "") + note + "</td></tr>";
    }).join("");
    return '<h3 class="h3" style="margin-top:0">Downstream systems</h3><div class="table-wrap"><table><thead><tr><th>System</th><th>Action</th><th>Status</th><th>Confirm by</th><th>Evidence</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  function detailText(e) {
    var d = e.details || {};
    if (e.action === "request.status_changed") {
      var extra = Object.keys(d).filter(function (k) { return k !== "from" && k !== "to"; })
        .map(function (k) { return k + ": " + d[k]; }).join(", ");
      return lab(d.from) + " to " + lab(d.to) + (extra ? " (" + extra + ")" : "");
    }
    return Object.keys(d).map(function (k) {
      var v = d[k];
      if (Array.isArray(v)) v = v.join(" + ");
      return k.replace(/_/g, " ") + ": " + v;
    }).join(", ");
  }

  function trail(ev) {
    var items = ev.map(function (e) {
      var cls = /failed|expired/.test(e.action) ? " fail" : (/confirmed|passed/.test(e.action) || (e.details && e.details.to === "fulfilled") ? " ok" : "");
      return '<li><span class="seq">#' + e.seq + "</span><div>" +
        '<div class="act' + cls + '">' + esc(ACTION[e.action] || e.action) + ' <span class="when">' + fmtDT(parse(e.at)) + " by " + esc(e.actor) + "</span></div>" +
        '<div class="det">' + esc(detailText(e)) + "</div>" +
        '<div class="hash">prev ' + esc(e.prev_hash.slice(0, 10)) + " > hash " + esc(e.hash.slice(0, 10)) + "</div></div></li>";
    }).join("");
    var subj = ev.length ? ev[0].subject_ref.slice(0, 12) : "";
    return '<div class="aud-head"><h3 class="h3" style="margin-top:0">Audit trail</h3><span class="small">subject ref <span class="mono">' + esc(subj) + "...</span> (keyed hash, no email stored)</span></div>" +
      '<ol class="trail">' + items + "</ol>";
  }

  // Swimlane timeline: verification, case, and one lane per downstream system.
  function drawTimeline(r, ev) {
    var box = $("tl");
    var W = Math.max(320, Math.round(box.clientWidth - 12));
    var narrow = W < 560;
    var labelW = narrow ? 104 : 224;
    var padR = 16, top = 40, laneH = narrow ? 26 : 28;
    var received = parse(r.received_at);
    var t0 = new Date(Date.UTC(received.getUTCFullYear(), received.getUTCMonth(), received.getUTCDate()));
    var due = parse(r.due_at), origDue = parse(r.original_due_at);
    var closed = parse(r.closed_at);
    var end = Math.max(due.getTime(), (closed || asOf).getTime(), asOf.getTime()) + 2 * DAY;
    var tEnd = new Date(end);
    function x(d) { return labelW + (d - t0) / (tEnd - t0) * (W - labelW - padR); }

    var dispatched = {}, failures = [];
    ev.forEach(function (e) {
      if (e.action === "fanout.dispatched" && !dispatched[e.details.system]) dispatched[e.details.system] = parse(e.at);
      if (e.action === "fanout.failed") failures.push({ sys: e.details.system, at: parse(e.at) });
    });

    var lanes = [{ key: "_verify", label: "Identity verification" }, { key: "_case", label: "Case" }];
    r.tasks.forEach(function (t) {
      var s = systems[t.system_key];
      lanes.push({ key: t.system_key, label: narrow ? t.system_key : (s ? s.name : t.system_key), task: t });
    });
    var H = top + lanes.length * laneH + 14;
    var out = [];
    out.push('<svg viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="Timeline for ' + esc(r.id) + '" font-family="-apple-system, Segoe UI, Roboto, Arial, sans-serif">');

    // weekly ticks
    var spanDays = days(t0, tEnd);
    var step = spanDays > 70 ? 14 : 7;
    if (narrow && spanDays > 40) step = spanDays > 90 ? 28 : 14;
    for (var i = 0; i <= spanDays; i += step) {
      var d = new Date(t0.getTime() + i * DAY);
      var tx = x(d);
      out.push('<line x1="' + tx + '" x2="' + tx + '" y1="' + (top - 8) + '" y2="' + (H - 8) + '" stroke="' + COLORS.line + '" stroke-width="1"/>');
      out.push('<text x="' + tx + '" y="' + (top - 14) + '" font-size="11" fill="' + COLORS.muted + '" text-anchor="middle">' + fmtD(d) + "</text>");
    }

    // lanes
    lanes.forEach(function (l, idx) {
      var y = top + idx * laneH;
      var cy = y + laneH / 2;
      out.push('<rect x="' + labelW + '" y="' + (y + 4) + '" width="' + (W - labelW - padR) + '" height="' + (laneH - 8) + '" fill="' + COLORS.track + '" rx="3" opacity="' + (idx % 2 ? 0.55 : 0.9) + '"/>');
      out.push('<text x="' + (labelW - 8) + '" y="' + (cy + 4) + '" font-size="' + (narrow ? 10.5 : 12) + '" fill="' + COLORS.ink + '" text-anchor="end">' + esc(l.label) + "</text>");
      var bh = laneH - 14, by = y + 7;
      if (l.key === "_verify") {
        var vEnd = parse(r.verified_at) || closed || asOf;
        out.push(bar(x(received), x(vEnd), by, bh, COLORS.sand));
        if (r.verified_at) out.push(diamond(x(parse(r.verified_at)), cy, COLORS.navy));
        ev.filter(function (e) { return e.action === "verification.failed"; }).forEach(function (e) {
          out.push(cross(x(parse(e.at)), cy, COLORS.bad));
        });
      } else if (l.key === "_case") {
        if (r.started_at) out.push(bar(x(parse(r.started_at)), x(closed || asOf), by, bh, COLORS.navy));
        if (closed) out.push(dot(x(closed), cy, r.status === "denied" ? COLORS.bad : COLORS.ok));
      } else {
        var t = l.task;
        var s0 = dispatched[l.key] || parse(t.dispatched_at);
        var s1 = parse(t.resolved_at) || closed || asOf;
        var col = t.status === "confirmed" ? COLORS.ok : t.status === "exempt" ? COLORS.grey : t.status === "failed" ? COLORS.bad : "#c9c1b1";
        out.push(bar(x(s0), x(s1), by, bh, col));
        failures.filter(function (f) { return f.sys === l.key; }).forEach(function (f) { out.push(cross(x(f.at), cy, COLORS.bad)); });
        if (t.resolved_at && t.status === "confirmed") out.push(dot(x(s1), cy, COLORS.ok));
      }
    });

    // markers
    function vline(d, color, dash, text, anchor) {
      var vx = x(d);
      out.push('<line x1="' + vx + '" x2="' + vx + '" y1="' + (top - 6) + '" y2="' + (H - 6) + '" stroke="' + color + '" stroke-width="1.6"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") + "/>");
      out.push('<text x="' + (vx + (anchor === "end" ? -4 : 4)) + '" y="' + (H - 1) + '" font-size="10.5" font-weight="600" fill="' + color + '" text-anchor="' + (anchor || "start") + '">' + esc(text) + "</text>");
    }
    if (r.extended_at) vline(origDue, COLORS.warn, "4 3", narrow ? "orig." : "original due", "end");
    vline(due, COLORS.bad, null, "due " + fmtD(due), r.extended_at ? "start" : "end");
    if (!closed || asOf - closed < 4 * DAY) vline(asOf, COLORS.navy2, "2 3", "today", "start");
    out.push("</svg>");
    box.innerHTML = out.join("");

    function bar(a, b, y, h, c) { return '<rect x="' + a + '" y="' + y + '" width="' + Math.max(3, b - a) + '" height="' + h + '" rx="3" fill="' + c + '"/>'; }
    function dot(cx, cy, c) { return '<circle cx="' + cx + '" cy="' + cy + '" r="4.5" fill="#fffdf8" stroke="' + c + '" stroke-width="2.2"/>'; }
    function diamond(cx, cy, c) { return '<path d="M' + cx + " " + (cy - 6) + " L" + (cx + 6) + " " + cy + " L" + cx + " " + (cy + 6) + " L" + (cx - 6) + " " + cy + ' Z" fill="' + c + '"/>'; }
    function cross(cx, cy, c) { return '<path d="M' + (cx - 4) + " " + (cy - 4) + " L" + (cx + 4) + " " + (cy + 4) + " M" + (cx + 4) + " " + (cy - 4) + " L" + (cx - 4) + " " + (cy + 4) + '" stroke="' + c + '" stroke-width="2.4" stroke-linecap="round"/>'; }
  }

  // ------------------------------------------------------------------ regulations
  function rulesFromData() {
    var seen = {};
    Object.keys(D.requests).forEach(function (id) {
      var r = D.requests[id];
      var k = r.regime + "|" + r.request_type;
      if (seen[k]) return;
      var rec = parse(r.received_at), od = parse(r.original_due_at.slice(0, 10));
      seen[k] = { regime: r.regime, type: r.request_type, basis: r.deadline_basis, window: days(new Date(Date.UTC(rec.getUTCFullYear(), rec.getUTCMonth(), rec.getUTCDate())), od), extendable: r.extendable };
    });
    return Object.keys(seen).sort().map(function (k) { return seen[k]; });
  }

  function renderRegulations() {
    var br = D.dashboard.by_regime;
    var ruleText = {
      gdpr: "One month from receipt, extendable by two further months with notice and reasons inside the first month (Art. 12(3)).",
      ccpa: "45 days to know, delete, or correct, extendable once by 45 with notice (Civ. Code 1798.130(a)(2)). Opt-out: 15 business days (11 CCR 7026(f))."
    };
    var windows = { gdpr: 31, ccpa: 45 };
    $("reg-cards").innerHTML = Object.keys(br).sort().reverse().map(function (k) {
      var s = br[k];
      var rate = s.on_time_rate == null ? "-" : Math.round(s.on_time_rate * 100) + "%";
      return '<div class="reg"><h3>' + lab(k) + '</h3><p class="rule">' + ruleText[k] + "</p>" +
        '<div class="nums">' +
        "<div><b>" + s.total + "</b><span>requests</span></div>" +
        "<div><b>" + s.open + "</b><span>open</span></div>" +
        "<div><b>" + rate + "</b><span>closed on time</span></div>" +
        "<div><b>" + s.extended + "</b><span>extended</span></div>" +
        "<div><b>" + s.breached_open + "</b><span>breached open</span></div>" +
        "</div>" + closeChart(s, windows[k]) + typeChart(s.by_type) + "</div>";
    }).join("");

    var rules = rulesFromData();
    $("rules").innerHTML = "<table><thead><tr><th>Regime</th><th>Type</th><th>Window (this sample)</th><th>Extension</th><th>Basis recorded on the request</th></tr></thead><tbody>" +
      rules.map(function (r) {
        return "<tr><td>" + lab(r.regime) + "</td><td>" + lab(r.type) + '</td><td class="num">' + r.window + " days</td><td>" +
          (r.extendable ? (r.regime === "gdpr" ? "+2 months" : "+45 days") : "None") + '</td><td class="small">' + esc(r.basis) + "</td></tr>";
      }).join("") + "</tbody></table>";

    $("systems").innerHTML = "<table><thead><tr><th>System</th><th>Owner</th><th>Operated by</th><th>Acts on</th><th>Confirm within</th></tr></thead><tbody>" +
      D.systems.map(function (s) {
        return "<tr><td><b>" + esc(s.name) + '</b><br><span class="mono">' + esc(s.key) + "</span></td><td>" + esc(s.owner) + "</td><td>" + esc(s.operated_by) +
          '</td><td class="small">' + s.supports.map(lab).join(", ") + '</td><td class="num">' + s.confirmation_sla_days + " days</td></tr>";
      }).join("") + "</tbody></table>";
  }

  function closeChart(s, windowDays) {
    if (s.median_days_to_close == null) return "";
    var W = 420, H = 58, L = 8, R = 8, max = Math.max(windowDays, s.max_days_to_close) * 1.08;
    function x(v) { return L + v / max * (W - L - R); }
    var g = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Days to close versus statutory window">' +
      '<rect x="' + L + '" y="18" width="' + (x(windowDays) - L) + '" height="12" rx="3" fill="#e3e9f1"/>' +
      '<line x1="' + x(windowDays) + '" x2="' + x(windowDays) + '" y1="12" y2="36" stroke="' + COLORS.bad + '" stroke-width="1.6"/>' +
      '<text x="' + (x(windowDays) - 4) + '" y="10" font-size="11" fill="' + COLORS.bad + '" text-anchor="end">window ~' + windowDays + "d</text>" +
      '<circle cx="' + x(s.median_days_to_close) + '" cy="24" r="5.5" fill="' + COLORS.navy + '"/>' +
      '<text x="' + x(s.median_days_to_close) + '" y="50" font-size="11" fill="' + COLORS.navy + '" text-anchor="middle">median ' + s.median_days_to_close + "d</text>" +
      '<path d="M' + (x(s.max_days_to_close) - 5) + " 19 L" + (x(s.max_days_to_close) + 5) + " 29 M" + (x(s.max_days_to_close) + 5) + " 19 L" + (x(s.max_days_to_close) - 5) + ' 29" stroke="' + (s.max_days_to_close > windowDays ? COLORS.bad : COLORS.ink) + '" stroke-width="2.2" stroke-linecap="round"/>' +
      '<text x="' + Math.min(x(s.max_days_to_close), W - 30) + '" y="' + (Math.abs(s.max_days_to_close - s.median_days_to_close) < max * 0.18 ? 10 : 50) + '" font-size="11" fill="' + COLORS.ink + '" text-anchor="middle">max ' + s.max_days_to_close + "d</text>" +
      "</svg>";
    return g + '<p class="cap">Days from receipt to closure for closed requests, against the base window.</p>';
  }

  function typeChart(byType) {
    var keys = ["access", "deletion", "correction", "opt_out"];
    var max = Math.max.apply(null, keys.map(function (k) { return byType[k] || 0; }).concat([1]));
    var W = 420, rowH = 20, H = keys.length * rowH + 6, L = 82;
    var g = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Requests by type" style="margin-top:10px">';
    keys.forEach(function (k, i) {
      var v = byType[k] || 0, y = i * rowH + 3, w = v / max * (W - L - 40);
      g += '<text x="' + (L - 8) + '" y="' + (y + 12) + '" font-size="12" fill="' + COLORS.ink + '" text-anchor="end">' + lab(k) + "</text>" +
        '<rect x="' + L + '" y="' + (y + 2) + '" width="' + Math.max(w, 1) + '" height="12" rx="3" fill="' + COLORS.navy2 + '"/>' +
        '<text x="' + (L + w + 6) + '" y="' + (y + 12) + '" font-size="12" fill="' + COLORS.ink + '">' + v + "</text>";
    });
    return g + "</svg>";
  }

  // ------------------------------------------------------------------ collection gate
  function renderPurposes() {
    var stats = {};
    D.collection.forEach(function (c) { stats[c.purpose] = c; });
    $("purposes").innerHTML = "<table><thead><tr><th>Purpose</th><th>Basis</th><th>Default</th><th>Program state</th><th>Accepted</th><th>Refused</th><th>Share refused</th></tr></thead><tbody>" +
      D.purposes.map(function (p) {
        var s = stats[p.key] || { accepted: 0, refused: {} };
        var refused = Object.keys(s.refused).reduce(function (a, k) { return a + s.refused[k]; }, 0);
        var total = s.accepted + refused;
        var reasons = Object.keys(s.refused).map(function (k) { return k.replace(/_/g, " ") + " " + s.refused[k]; }).join(", ");
        var w = total ? refused / total * 80 : 0;
        var mini = '<svg viewBox="0 0 80 10" width="80" height="10" aria-hidden="true"><rect width="80" height="10" rx="2" fill="#e2efe5"/>' +
          (w ? '<rect width="' + w + '" height="10" rx="2" fill="' + COLORS.bad + '"/>' : "") + "</svg>";
        return "<tr><td><b>" + esc(p.key) + '</b><br><span class="small">' + esc(p.description) + "</span></td>" +
          '<td class="small">' + esc(p.lawful_basis.replace(/_/g, " ")) + "</td><td>" + (p.default_granted ? "On" : "Off") + "</td>" +
          "<td>" + (p.halted ? chip("breached", "Halted") + '<br><span class="small">' + esc(p.halt_reason) + "</span>" : chip("on_time", "Collecting if allowed")) + "</td>" +
          '<td class="num">' + s.accepted + '</td><td class="num">' + refused + (reasons ? '<br><span class="small">' + esc(reasons) + "</span>" : "") + "</td>" +
          "<td>" + (total ? mini : '<span class="small">no traffic</span>') + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  // ------------------------------------------------------------------ boot
  renderHeader();
  renderKpis();
  renderQueue();
  renderFeatured();
  renderRegulations();
  renderPurposes();
  select(D.cases.G1);

  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (selected) drawTimeline(D.requests[selected], D.audit[selected]); }, 120);
  });
})();
