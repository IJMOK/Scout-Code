// The Studio: play the game, ask the AI for changes, watch it work, read the code.

const S = {
  team: null,
  gameId: null,
  game: null,
  code: "",
  versionId: null,
  busy: false,
  explainText: "",
  tested: new Set(),
  fixing: false,
  events: null,
};

const STEPS = [
  ["queue", "⏳ Waiting"],
  ["think", "🤔 Planning"],
  ["write", "✍️ Writing code"],
  ["test", "🧪 Testing"],
  ["fix", "🔧 Fixing a bug"],
  ["done", "✅ Done"],
];

// ------------------------------------------------------------------ start up

async function init() {
  const info = await api("/api/info");
  if (!info.team) { location.href = "/login"; return; }
  S.team = info.team;
  $("#team-label").textContent = `${info.team.emoji} ${info.team.name}`;
  if (info.ai_paused) $("#ai-state").textContent = "😴 The AI is having a break";

  const id = Number(new URLSearchParams(location.search).get("game"));
  if (id) {
    await openGame(id);
    connectEvents();
  } else {
    await showPicker(info.starters);
  }
}

async function showPicker(starters) {
  $("#picker").classList.remove("hidden");
  const me = await api("/api/me");
  if (me.games.length) {
    $("#my-games-section").classList.remove("hidden");
    $("#my-games").innerHTML = me.games.map(g => {
      const s = starters.find(x => x.id === g.starter) || { emoji: "🎮" };
      return `<a class="card starter" href="/studio?game=${g.id}" style="text-decoration:none">
        <div class="emoji">${s.emoji}</div><h3>${esc(g.title)}</h3>
        ${g.published ? '<span class="badge">🌟 In the Arcade</span>' : '<span class="muted">Keep building →</span>'}</a>`;
    }).join("");
  }
  $("#starters").innerHTML = starters.map(s => `
    <button class="card starter" data-starter="${s.id}">
      <div class="emoji">${s.emoji}</div><h3>${esc(s.title)}</h3><div class="muted">${esc(s.blurb)}</div>
    </button>`).join("");
  $all("[data-starter]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await api("/api/games", { method: "POST", body: { starter: b.dataset.starter } });
      location.href = `/studio?game=${res.id}`;
    } catch (err) { toast(err.message, true); b.disabled = false; }
  });
}

async function openGame(id) {
  const data = await api(`/api/games/${id}`);
  S.gameId = id;
  S.game = data.game;
  $("#studio").classList.remove("hidden");
  $("#btn-history").classList.remove("hidden");
  $("#btn-publish").classList.remove("hidden");
  $("#game-title").textContent = "· " + data.game.title;
  document.title = `${data.game.title} · Scout Code`;

  $("#ideas").innerHTML = data.ideas.map(i => `<button class="idea" type="button">💡 ${esc(i)}</button>`).join("");
  $all(".idea").forEach(b => b.onclick = () => {
    $("#ask-input").value = b.textContent.replace(/^💡\s*/, "");
    $("#ask-input").focus();
  });

  showVersion(data.current.id, data.current.code, null);
  syncJobState(data);
}

// Pick up where we left off (page reload, or the live connection dropped).
function syncJobState(data) {
  const job = data.active_job;
  if (job) {
    setBusy(true);
    showAgent();
    if (job.status === "queued") setStep("queue", "Waiting for a free AI…");
    if (job.status === "running") setStep("write", "The AI is working on your idea…");
  }
  if (data.pending_test_version_id) runTest(data.pending_test_version_id);
  if (!job && !data.pending_test_version_id && S.busy) setBusy(false);
  if (data.current.id !== S.versionId) showVersion(data.current.id, data.current.code, S.code);
}

function showVersion(versionId, code, prevCode) {
  S.versionId = versionId;
  S.code = code;
  loadPlayer();
  const result = CodeView.render($("#code"), code, prevCode);
  return result;
}

function loadPlayer() {
  const wrap = $("#play-wrap");
  wrap.innerHTML = "";
  const f = document.createElement("iframe");
  f.setAttribute("sandbox", "allow-scripts");
  f.setAttribute("title", "Your game");
  f.src = `/play/${S.versionId}`;
  wrap.appendChild(f);
  f.addEventListener("load", () => f.focus());
}

// ------------------------------------------------------------------ live events

function connectEvents() {
  let connectedBefore = false;
  const es = new EventSource("/api/events");
  S.events = es;
  es.onopen = async () => {
    if (connectedBefore) {
      try { syncJobState(await api(`/api/games/${S.gameId}`)); } catch (e) { /* try again next time */ }
    }
    connectedBefore = true;
  };
  es.onmessage = ev => handleEvent(JSON.parse(ev.data));
}

function handleEvent(ev) {
  // Explain jobs stream into the speech bubble; everything else is the agent panel.
  const isExplain = ev.kind === "explain";

  if (ev.type === "token") {
    if (isExplain) {
      S.explainText += ev.text;
      $("#explain-text").textContent = S.explainText;
    } else {
      const nb = $("#notebook");
      nb.textContent += ev.text;
      nb.scrollTop = nb.scrollHeight;
    }
    return;
  }
  if (ev.type === "explain") {
    $("#explain-text").textContent = "💬 " + ev.text;
    return;
  }
  if (ev.type === "position") {
    if (isExplain) return;
    const wait = ev.eta < 60 ? "less than a minute" : `about ${Math.round(ev.eta / 60)} min`;
    setStep("queue", `You're number ${ev.position} in the queue (${wait}). Why not play someone's game in the Arcade?`);
    return;
  }
  if (ev.type !== "job" || isExplain) return;

  showAgent();
  switch (ev.stage) {
    case "queued":
      setBusy(true);
      setStep("queue", ev.message || "Waiting for a free AI…");
      break;
    case "thinking":
      $("#notebook").textContent = "";
      setStep("think", "Reading your game and making a plan…");
      break;
    case "writing":
      setStep("write", "Writing the code changes…");
      break;
    case "testing":
      if (ev.plan) setStep("test", `Plan: ${ev.plan}`);
      runTest(ev.version_id);
      break;
    case "fixing":
      setStep("fix", ev.retry
        ? "The AI's first try didn't fit your game, so it's having another go…"
        : `Found a bug 🐛 (${ev.message}). The AI is fixing it…`);
      break;
    case "done":
      finishJob(ev.version_id, ev.plan);
      break;
    case "gave_up":
    case "failed":
    case "cancelled":
      setStep(null, ev.message || "That didn't work.", "bad");
      setBusy(false);
      break;
  }
}

async function runTest(versionId) {
  if (S.tested.has(versionId)) return;
  S.tested.add(versionId);
  showAgent();
  setStep("test", "Test-playing the new version…");
  try {
    const v = await api(`/api/versions/${versionId}`);
    if (v.status !== "testing") return;
    $("#test-box").classList.remove("hidden");
    const result = await GameTester.test(v.code, $("#test-holder"));
    $("#test-box").classList.add("hidden");
    await api(`/api/versions/${versionId}/test`, { method: "POST", body: result });
  } catch (err) {
    $("#test-box").classList.add("hidden");
    toast(err.message, true);
  }
}

async function finishJob(versionId, plan) {
  const v = await api(`/api/versions/${versionId}`);
  const prev = S.code;
  const changed = showVersion(v.id, v.code, prev);
  const glow = changed.added ? ` (${changed.added} line${changed.added === 1 ? "" : "s"} changed: look for the green glow in the code)` : "";
  setStep("done", `✅ Done! ${plan || ""}${glow}`, "good");
  setBusy(false);
}

// ------------------------------------------------------------------ agent panel

function showAgent() { $("#agent").classList.remove("hidden"); }

function setStep(stepId, message, tone = "") {
  if (stepId === "fix") S.fixing = true;
  const visible = STEPS.filter(([id]) => id !== "fix" || S.fixing);
  const idx = visible.findIndex(([id]) => id === stepId);
  $("#steps").innerHTML = visible.map(([id, label], i) => {
    let cls = "step";
    if (idx !== -1 && (i < idx || (i === idx && id === "done"))) cls += " did";
    else if (i === idx) cls += " now";
    return `<span class="${cls}">${label}</span>`;
  }).join("");
  const msg = $("#agent-msg");
  msg.textContent = message || "";
  msg.className = "agent-msg" + (tone ? " " + tone : "");
  msg.scrollIntoView({ block: "nearest" });
}

function setBusy(busy) {
  S.busy = busy;
  $("#ask-btn").disabled = busy;
  $("#ask-btn").textContent = busy ? "Working…" : "Go!";
  if (!busy) S.fixing = false;
}

// ------------------------------------------------------------------ actions

$("#ask-form").onsubmit = async e => {
  e.preventDefault();
  const request = $("#ask-input").value.trim();
  if (request.length < 3) { toast("Tell the AI what you'd like to change!", true); return; }
  try {
    setBusy(true);
    showAgent();
    $("#notebook").textContent = "";
    setStep("queue", "Sending your idea to the AI…");
    await api(`/api/games/${S.gameId}/ask`, { method: "POST", body: { request } });
    $("#ask-input").value = "";
  } catch (err) {
    setBusy(false);
    setStep(null, err.message, "bad");
    toast(err.message, true);
  }
};

$("#ask-input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); }
});

$("#btn-explain").onclick = async () => {
  const snippet = CodeView.selection($("#code")) || CodeView.changedText($("#code"));
  if (!snippet) { toast("Highlight some code with your mouse first, then press Explain!"); return; }
  $("#explain").classList.remove("hidden");
  S.explainText = "💬 ";
  $("#explain-text").textContent = "🤔 Thinking about that code…";
  try {
    await api(`/api/games/${S.gameId}/explain`, { method: "POST", body: { snippet } });
  } catch (err) {
    $("#explain-text").textContent = err.message;
  }
};
$("#explain-close").onclick = () => $("#explain").classList.add("hidden");

$("#btn-restart").onclick = loadPlayer;

$("#btn-logout").onclick = async () => {
  await api("/api/logout", { method: "POST" });
  location.href = "/login";
};

// History
$("#btn-history").onclick = async () => {
  const data = await api(`/api/games/${S.gameId}`);
  const icons = { ok: "✅", broken: "🐛", testing: "🧪" };
  $("#history-list").innerHTML = data.versions.slice().reverse().map(v => {
    const current = v.id === data.current.id;
    const what = v.request ? `“${esc(v.request)}”` : esc(v.plan);
    const plan = v.request && v.plan ? `<br><span class="muted">${esc(v.plan)}</span>` : "";
    const btn = v.status === "ok" && !current ? `<button class="btn small" data-restore="${v.id}">Go back to this</button>` : "";
    return `<li>${icons[v.status] || ""} ${what}${plan} ${current ? '<span class="badge">You are here</span>' : ""} ${btn}</li>`;
  }).join("");
  $all("[data-restore]").forEach(b => b.onclick = async () => {
    try {
      await api(`/api/games/${S.gameId}/restore`, { method: "POST", body: { version_id: Number(b.dataset.restore) } });
      const fresh = await api(`/api/games/${S.gameId}`);
      showVersion(fresh.current.id, fresh.current.code, S.code);
      $("#history-modal").classList.add("hidden");
      toast("Gone back in time! ⏪");
    } catch (err) { toast(err.message, true); }
  });
  $("#history-modal").classList.remove("hidden");
};

// Publish
$("#btn-publish").onclick = async () => {
  const data = await api(`/api/games/${S.gameId}`);
  $("#pub-title").value = data.game.title;
  $("#pub-desc").value = data.game.description || "";
  $("#btn-unpublish").classList.toggle("hidden", !data.game.published_version_id);
  $("#publish-modal").classList.remove("hidden");
};
$("#publish-form").onsubmit = async e => {
  e.preventDefault();
  try {
    await api(`/api/games/${S.gameId}/publish`, { method: "POST", body: {
      title: $("#pub-title").value, description: $("#pub-desc").value, published: true,
    }});
    $("#game-title").textContent = "· " + $("#pub-title").value;
    $("#publish-modal").classList.add("hidden");
    toast("🌟 Your game is in the Arcade!");
  } catch (err) { toast(err.message, true); }
};
$("#btn-unpublish").onclick = async () => {
  await api(`/api/games/${S.gameId}/publish`, { method: "POST", body: { title: $("#pub-title").value || "Game", published: false } });
  $("#publish-modal").classList.add("hidden");
  toast("Taken out of the Arcade.");
};

$all("[data-close]").forEach(b => b.onclick = () => b.closest(".modal-back").classList.add("hidden"));
$all(".modal-back").forEach(m => m.addEventListener("click", e => { if (e.target === m) m.classList.add("hidden"); }));

init().catch(err => toast(err.message, true));
