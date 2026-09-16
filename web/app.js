async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${body}`);
  }
  return res.json();
}

const money = (n) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

function pill(status) {
  return `<span class="pill ${status}">${status.replace(/_/g, " ")}</span>`;
}

async function loadSummary() {
  const runs = await api("/v1/runs?limit=1");
  if (!runs.length) return;
  const latest = runs[0];
  if (latest.status !== "succeeded") return;
  const s = latest.summary;
  document.getElementById("summary").classList.remove("hidden");
  document.getElementById("narrative").textContent = s.narrative || "";
  const kpis = [
    [s.skus_planned, "SKUs planned"],
    [s.orders_proposed, "Orders proposed"],
    [money(s.total_proposed_spend), "Proposed spend"],
    [s.pos_needing_approval, "POs need approval"],
    [s.skus_at_stockout_risk.length, "At stockout risk"],
  ];
  document.getElementById("kpis").innerHTML = kpis
    .map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`)
    .join("");
}

async function loadApprovals() {
  const rows = await api("/v1/decisions?status=needs_approval");
  const tb = document.querySelector("#approvals-table tbody");
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="7" class="empty">No pending approvals.</td></tr>`;
    return;
  }
  tb.innerHTML = rows
    .map(
      (d) => `<tr>
        <td>${d.id}</td>
        <td>${d.sku_id}</td>
        <td>${d.quantity}</td>
        <td>${d.extra.supplier_id || ""}</td>
        <td>${money(d.total_cost)}</td>
        <td>${d.rationale}</td>
        <td style="white-space:nowrap">
          <button class="btn approve" data-act="approve" data-id="${d.id}">Approve</button>
          <button class="btn reject" data-act="reject" data-id="${d.id}">Reject</button>
        </td>
      </tr>`
    )
    .join("");
  tb.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => decide(b.dataset.id, b.dataset.act))
  );
}

async function decide(id, act) {
  const by = prompt("Your name (recorded in the audit trail):", "planner");
  if (!by) return;
  await api(`/v1/decisions/${id}/${act}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decided_by: by }),
  });
  await loadApprovals();
}

async function loadInventory() {
  const rows = await api("/v1/inventory");
  document.querySelector("#inventory-table tbody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.sku_id}</td><td>${r.name}</td><td>${r.category}</td>
        <td>${r.on_hand}</td><td>${r.on_order}</td><td>${r.lead_time_days}d</td>
      </tr>`
    )
    .join("");
}

async function loadRuns() {
  const runs = await api("/v1/runs?limit=10");
  document.querySelector("#runs-table tbody").innerHTML = runs
    .map((r) => {
      const s = r.summary || {};
      return `<tr>
        <td><code>${r.id}</code></td>
        <td>${pill(r.status)}</td>
        <td>${new Date(r.started_at).toLocaleString()}</td>
        <td>${s.orders_proposed ?? "-"}</td>
        <td>${s.total_proposed_spend != null ? money(s.total_proposed_spend) : "-"}</td>
      </tr>`;
    })
    .join("");
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
