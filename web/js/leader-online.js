// Leader dashboard: putting games online, past events, and the session/demo buttons.

let P = null;            // last /api/leader/publish response
let formLoaded = false;  // don't overwrite what a leader is typing

async function loadPublish() {
  try {
    P = await api("/api/leader/publish");
  } catch (err) { return; }
  renderPublish();
}

function renderPublish() {
  const s = P.settings;
  if (!formLoaded) {
    $("#on-repo").value = s.repo;
    $("#on-title").value = s.site_title;
    $("#on-days").value = s.expiry_days;
    $("#on-hide-names").checked = s.hide_team_names;
    $("#on-auto-expire").checked = s.auto_expire;
    $all(".on-check").forEach(c => c.checked = s.checklist_done);
    formLoaded = true;
  }
  $("#on-token-hint").textContent = s.token_hint ? `(saved: ${s.token_hint})` : "";

  const st = P.status;
  const el = $("#on-status");
  el.className = "sync-status " + st.state;
  el.textContent = st.message || (s.configured ? "Ready. Nothing uploaded yet in this session." : "Not set up yet.");

  const live = P.sessions.some(x => x.live);
  $("#on-site").classList.toggle("hidden", !P.site_url);
  $("#on-site-link").href = $("#on-site-link").textContent = P.site_url;
  $("#nav-site").classList.toggle("hidden", !(P.site_url && live));
  $("#nav-site").href = P.site_url || "#";

  const fmt = t => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  $("#archives").innerHTML = P.sessions.length ? P.sessions.map(a => {
    const name = encodeURIComponent(a.name);
    const thisEvent = a.event_id && a.event_id === P.current_event_id ? ' <span class="badge">this event</span>' : "";
    const until = a.online ? `${a.expired ? "⌛ expired " : ""}${fmt(a.expires)} <button class="btn small" data-extend="${name}">+${s.expiry_days} days</button>` : "";
    const link = a.live && a.url ? `<button class="btn small" data-copy="${esc(a.url)}">📋 Copy</button>` : "";
    return `<tr>
      <td>${esc(a.event_name)}${thisEvent}</td>
      <td>${new Date(a.archived_at * 1000).toLocaleString()}</td>
      <td>${a.teams}</td><td>${a.games} (${a.published} published)
        ${a.published ? `<button class="btn small" data-choose="${name}" title="Choose which games go online">choose</button>` : ""}</td>
      <td><a href="/api/leader/archives/${name}/games.zip">💾 games.zip</a>
        · <a href="/api/leader/archives/${name}/scout.db" title="Full backup, for restoring">backup</a></td>
      <td><label class="check" style="margin:0"><input type="checkbox" data-online="${name}" ${a.online ? "checked" : ""}> ${a.live ? "🌐 online" : "offline"}</label></td>
      <td>${until}</td>
      <td>${link}</td></tr>`;
  }).join("") : '<tr><td colspan="8" class="muted">None yet</td></tr>';

  $all("[data-online]").forEach(c => c.onchange = () =>
    publishAction(`/api/leader/publish/sessions/${c.dataset.online}`, { online: c.checked },
      c.checked ? "Marked to go online: press Sync now when the Pi has internet." : "Marked offline: press Sync now to remove it."));
  $all("[data-extend]").forEach(b => b.onclick = () =>
    publishAction(`/api/leader/publish/sessions/${b.dataset.extend}`, { expires_in_days: P.settings.expiry_days }, "New end date set. Sync to update the website."));
  $all("[data-copy]").forEach(b => b.onclick = () => copyText(b.dataset.copy));
  $all("[data-choose]").forEach(b => b.onclick = () => chooseGames(b.dataset.choose));
}

async function publishAction(path, body, message) {
  try {
    const res = await api(path, { method: "POST", body });
    if (message) toast(message);
    await loadPublish();
    return res;
  } catch (err) { toast(err.message, true); }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Link copied: paste it into your message to parents.");
  } catch (err) {
    prompt("Copy this link:", text);  // clipboard needs https; this always works
  }
}

async function chooseGames(name) {
  const session = P.sessions.find(x => encodeURIComponent(x.name) === name);
  const games = await api(`/api/leader/publish/sessions/${name}/games`);
  const excluded = new Set(session.excluded || []);
  $("#choose-title").textContent = `Which games from “${session.event_name}” go online?`;
  $("#choose-list").innerHTML = games.map(g => `<label class="check">
      <input type="checkbox" data-game="${g.id}" ${excluded.has(g.id) ? "" : "checked"}>
      ${esc(g.title)} <span class="muted">by ${esc(g.team_emoji)} ${esc(g.team_name)}</span></label>`).join("")
    || '<p class="muted">No published games.</p>';
  $("#choose-modal").classList.remove("hidden");
  $("#choose-save").onclick = async () => {
    const out = $all("[data-game]", $("#choose-list")).filter(c => !c.checked).map(c => Number(c.dataset.game));
    await publishAction(`/api/leader/publish/sessions/${name}`, { excluded: out }, "Saved. Sync to update the website.");
    $("#choose-modal").classList.add("hidden");
  };
}
$("#choose-cancel").onclick = () => $("#choose-modal").classList.add("hidden");

function formBody() {
  return {
    repo: $("#on-repo").value.trim(),
    token: $("#on-token").value.trim(),
    site_title: $("#on-title").value.trim() || "Our Scout Code games",
    expiry_days: Number($("#on-days").value) || 30,
    hide_team_names: $("#on-hide-names").checked,
    auto_expire: $("#on-auto-expire").checked,
    checklist_done: $all(".on-check").every(c => c.checked),
  };
}

async function saveSettings(quiet = false) {
  try {
    await api("/api/leader/publish/settings", { method: "POST", body: formBody() });
    $("#on-token").value = "";
    if (!quiet) toast("Settings saved.");
    await loadPublish();
    return true;
  } catch (err) { toast(err.message, true); return false; }
}

$("#online-form").onsubmit = e => { e.preventDefault(); saveSettings(); };

$("#on-test").onclick = async () => {
  if (!(await saveSettings(true))) return;
  const res = await api("/api/leader/publish/test", { method: "POST" });
  toast((res.ok ? "✅ " : "⚠️ ") + res.message, !res.ok);
};

$("#on-preview").onclick = async () => {
  await saveSettings(true);
  const res = await api("/api/leader/publish/preview", { method: "POST" });
  window.open(res.url, "_blank");
};

$("#on-tonight").onclick = async () => {
  if (!(await saveSettings(true))) return;
  if (!P.settings.checklist_done) { toast("Tick the three boxes under 'Before anything goes online' first.", true); return; }
  await publishAction("/api/leader/publish/tonight", {}, "Tonight's games are saved and marked to go online.");
  await publishAction("/api/leader/publish/sync", {});
};

$("#on-sync").onclick = async () => {
  if (!(await saveSettings(true))) return;
  publishAction("/api/leader/publish/sync", {});
};

$("#on-offline").onclick = () => {
  if (!confirm("Take every session off the website? (They stay saved on this Pi.)")) return;
  publishAction("/api/leader/publish/offline", {}, "Taking everything offline…");
};

$("#on-site-copy").onclick = () => copyText(P.site_url);

$("#btn-demo").onclick = async () => {
  const tab = window.open("about:blank", "_blank");  // open now so pop-up blockers allow it
  try {
    await api("/api/leader/demo-team", { method: "POST" });
    tab.location = "/studio";
  } catch (err) { tab.close(); toast(err.message, true); }
};

setInterval(() => { if (P && !$("#dash").classList.contains("hidden")) loadPublish(); }, 5000);
