// Leader dashboard: health of the Pis, the queue, teams and games.

let L = null;

async function refresh() {
  try {
    L = await api("/api/leader/status");
  } catch (err) {
    if (err.status === 401) { showLogin(); return; }
    throw err;
  }
  $("#login").classList.add("hidden");
  $("#dash").classList.remove("hidden");
  render();
}

function showLogin() {
  $("#dash").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#pin").focus();
}

function secs(a, b) {
  if (!a) return "";
  const s = Math.round((b || Date.now() / 1000) - a);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function render() {
  $("#join-code").textContent = L.join_code;
  $("#portal-url").textContent = location.host;
  if (document.activeElement !== $("#event-name")) $("#event-name").value = L.event_name;
  $("#t-ai").textContent = L.ai_paused ? "▶️ Resume AI" : "⏸️ Pause AI";
  $("#t-ai").classList.toggle("primary", L.ai_paused);
  $("#t-vote").textContent = L.voting_frozen ? "🔓 Re-open voting" : "🔒 Close voting";
  $("#t-awards").textContent = L.awards_revealed ? "🙈 Hide awards" : "🏆 Reveal awards";
  $("#avg").textContent = `Average AI job: ${L.average_job_seconds}s${L.mock ? " · ⚠️ MOCK AI (development mode)" : ""}`;

  $("#workers").innerHTML = L.workers.map(w => {
    const st = w.stats || {};
    const temp = st.temp_c != null ? `${st.temp_c}°C` : "?";
    const hot = st.temp_c >= 80 ? " ⚠️ hot!" : "";
    const throttled = st.throttled ? " ⚠️ throttled" : "";
    return `<div class="worker">
      <b><span class="dot ${w.healthy ? "ok" : ""}"></span> ${esc(w.name)}</b>
      <div>${w.busy_job ? `Working on job #${w.busy_job}` : (w.healthy ? "Ready" : "Not responding")}</div>
      <div class="muted" style="font-size:14px">🌡️ ${temp}${hot}${throttled} · ⚡ ${w.tokens_per_sec || "-"} tok/s · ${w.jobs_done} jobs
      ${st.load != null ? `· load ${st.load}` : ""} ${st.mem_used_pct != null ? `· mem ${st.mem_used_pct}%` : ""}</div>
    </div>`;
  }).join("");

  $("#queue").innerHTML = L.queue.length ? L.queue.map(j => `<tr>
      <td>${esc(j.team_emoji)} ${esc(j.team_name)}</td><td>${j.kind}</td>
      <td><span class="status-pill ${j.status}">${j.status}</span> ${j.worker ? esc(j.worker) : ""} ${secs(j.started_at || j.created_at)}</td>
      <td><button class="btn small danger" data-cancel="${j.id}">Stop</button></td></tr>`).join("")
    : '<tr><td colspan="4" class="muted">Nothing waiting 🎉</td></tr>';

  $("#teams").innerHTML = L.teams.map(t => `<tr>
      <td>${esc(t.emoji)} ${esc(t.name)}</td><td><code>${esc(t.pin)}</code></td><td>${t.games}</td>
      <td>${t.successes}/${t.requests}</td>
      <td><button class="btn small" data-reset="${t.id}">New PIN</button></td></tr>`).join("");

  $("#recent").innerHTML = L.recent_jobs.map(j => `<tr>
      <td>${j.id}</td><td>${esc(j.team_emoji)} ${esc(j.team_name)}</td>
      <td>${j.kind === "explain" ? "<i>explain code</i>" : esc(j.request)}</td>
      <td>${esc(j.plan || j.message).slice(0, 160)}</td>
      <td><span class="status-pill ${j.status}">${j.kind}: ${j.status}</span></td>
      <td>${esc(j.worker || "")}</td><td>${secs(j.started_at, j.finished_at)}</td></tr>`).join("");

  const pub = Object.fromEntries(L.games.map(g => [g.id, g]));
  $("#games").innerHTML = L.all_games.map(g => {
    const p = pub[g.id];
    const vid = g.published_version_id || g.current_version_id;
    return `<tr>
      <td><a href="/play/${vid}" target="_blank">${esc(g.title)}</a></td>
      <td>${esc(g.team_emoji)} ${esc(g.team_name)}</td>
      <td>${g.published_version_id ? (g.hidden ? "🙈 hidden" : "🌟 published") : "draft"}</td>
      <td>${p && p.ratings ? `${starsText(p.avg_stars)} (${p.ratings})` : ""}</td>
      <td><button class="btn small" data-hide="${g.id}" data-hidden="${g.hidden ? 0 : 1}">${g.hidden ? "Show" : "Hide"}</button></td></tr>`;
  }).join("");

  $all("[data-cancel]").forEach(b => b.onclick = () => post(`/api/leader/jobs/${b.dataset.cancel}/cancel`));
  $all("[data-hide]").forEach(b => b.onclick = () => post(`/api/leader/games/${b.dataset.hide}/hide`, { hidden: b.dataset.hidden === "1" }));
  $all("[data-reset]").forEach(b => b.onclick = async () => {
    if (!confirm("Give this team a new PIN? Their laptop will need to log in again.")) return;
    const res = await post(`/api/leader/teams/${b.dataset.reset}/reset-pin`);
    if (res) toast(`New PIN: ${res.pin}`);
  });
}

async function post(path, body = {}) {
  try {
    const res = await api(path, { method: "POST", body });
    await refresh();
    return res;
  } catch (err) { toast(err.message, true); }
}

$("#login").onsubmit = async e => {
  e.preventDefault();
  try {
    await api("/api/leader/login", { method: "POST", body: { pin: $("#pin").value } });
    await refresh();
  } catch (err) { toast(err.message, true); }
};

$("#t-ai").onclick = () => post("/api/leader/settings", { ai_paused: !L.ai_paused });
$("#t-vote").onclick = () => post("/api/leader/settings", { voting_frozen: !L.voting_frozen });
$("#t-awards").onclick = () => post("/api/leader/settings", { awards_revealed: !L.awards_revealed });
$("#btn-newcode").onclick = () => post("/api/leader/join-code");
$("#btn-name").onclick = () => post("/api/leader/settings", { event_name: $("#event-name").value });

refresh().catch(err => toast(err.message, true));
setInterval(() => { if (!$("#dash").classList.contains("hidden")) refresh().catch(() => {}); }, 3000);
