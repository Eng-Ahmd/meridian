async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${body}`);
  }
  return res.json();
}

const moneyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const money = (n) => {
  const v = Number(n);
  return Number.isFinite(v) ? moneyFmt.format(v) : "—";
};

function pill(status) {
  const el = document.createElement("span");
  el.className = `pill ${status}`;
  el.textContent = String(status).replace(/_/g, " ");
  return el;
}

function td(text) {
  const c = document.createElement("td");
  c.textContent = text ?? "";
  return c;
}

async function loadSummary() {
  // Latest *succeeded* run: a failed run carries only {error} and must not
  // break the dashboard (P1-10).
  const runs = await api("/v1/runs?limit=20");
  const latest = runs.find(
    (r) => r.status === "succeeded" && r.summary && r.summary.skus_planned !== undefined
  );
  if (!latest) return;
  const s = latest.summary;
  document.getElementById("summary").classList.remove("hidden");
  document.getElementById("narrative").textContent = s.narrative || "";
  const kpis = [
    [String(s.skus_planned ?? "—"), "SKUs planned"],
    [String(s.orders_proposed ?? "—"), "Orders proposed"],
    [money(s.total_proposed_spend), "Proposed spend"],
    [String(s.pos_needing_approval ?? "—"), "POs need approval"],
    [String((s.skus_at_stockout_risk || []).length), "At stockout risk"],
  ];
  const box = document.getElementById("kpis");
  box.replaceChildren();
  for (const [v, l] of kpis) {
    const card = document.createElement("div");
    card.className = "kpi";
    const vv = document.createElement("div");
    vv.className = "v";
    vv.textContent = v;
    const ll = document.createElement("div");
    ll.className = "l";
    ll.textContent = l;
    card.append(vv, ll);
    box.append(card);
  }
}

async function loadApprovals() {
  const rows = await api("/v1/decisions?status=needs_approval");
  const tb = document.querySelector("#approvals-table tbody");
  tb.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const c = document.createElement("td");
    c.colSpan = 7;
    c.className = "empty";
    c.textContent = "No pending approvals.";
    tr.append(c);
    tb.append(tr);
    return;
  }
  for (const d of rows) {
    const tr = document.createElement("tr");
    tr.append(
      td(String(d.id)),
      td(d.sku_id),
      td(String(d.quantity)),
      td(d.extra?.supplier_id ?? ""),
      td(money(d.total_cost)),
      td(d.rationale)
    );
    const act = document.createElement("td");
    act.style.whiteSpace = "nowrap";
    for (const [label, cls, name] of [
      ["Approve", "btn approve", "approve"],
      ["Reject", "btn reject", "reject"],
    ]) {
      const b = document.createElement("button");
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", () => decide(d.id, name));
      act.append(b);
    }
    tr.append(act);
    tb.append(tr);
  }
}

async function decide(id, act) {
  const by = prompt("Your name (recorded in the audit trail):", "planner");
  if (!by || !by.trim()) return;
  await api(`/v1/decisions/${id}/${act}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decided_by: by.trim() }),
  });
  await loadApprovals();
}

async function loadInventory() {
  const rows = await api("/v1/inventory");
  const tb = document.querySelector("#inventory-table tbody");
  tb.replaceChildren();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.append(
      td(r.sku_id),
      td(r.name),
      td(r.category),
      td(String(r.on_hand ?? "")),
      td(String(r.on_order ?? "")),
      td(r.lead_time_days != null ? `${r.lead_time_days}d` : "")
    );
    tb.append(tr);
  }
}

async function loadRuns() {
  const runs = await api("/v1/runs?limit=10");
  const tb = document.querySelector("#runs-table tbody");
  tb.replaceChildren();
  for (const r of runs) {
    const s = r.summary || {};
    const tr = document.createElement("tr");
    const idc = document.createElement("td");
    const code = document.createElement("code");
    code.textContent = r.id;
    idc.append(code);
    const stc = document.createElement("td");
    stc.append(pill(r.status));
    const dtc = document.createElement("td");
    dtc.textContent = new Date(r.started_at).toLocaleString();
    tr.append(
      idc,
      stc,
      dtc,
      td(s.orders_proposed ?? "-"),
      td(s.total_proposed_spend != null ? money(s.total_proposed_spend) : "-")
    );
    tb.append(tr);
  }
}

document.getElementById("run-btn").addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    await api("/v1/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    await refresh();
  } catch (err) {
    alert("Run failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run planning";
  }
});

async function refresh() {
  await Promise.all([loadSummary(), loadApprovals(), loadInventory(), loadRuns()]);
}
refresh();
