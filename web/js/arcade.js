// The Arcade: play, rate and vote for everyone's published games.

const A = { info: null, games: [], team: null, open: null, frozen: false };

async function load() {
  const data = await api("/api/arcade");
  A.games = data.games;
  A.team = data.team;
  A.frozen = data.voting_frozen;
  $("#event-name").textContent = `🕹️ ${data.event_name}`;
  $("#team-label").textContent = data.team ? `${data.team.emoji} ${data.team.name}` : "";
  $("#voting-state").textContent = data.voting_frozen ? "🔒 Voting closed" : "";
  render();
}

function render() {
  $("#empty").classList.toggle("hidden", A.games.length > 0);
  $("#games").innerHTML = A.games.map(g => {
    const reactions = Object.entries(g.reactions).map(([r, n]) => `<span>${r} ${n}</span>`).join("");
    const mine = g.is_mine ? '<span class="badge">Your game</span>' : (g.my_rating ? '<span class="badge">✓ Rated</span>' : "");
    return `<div class="card game-card" data-game="${g.id}" tabindex="0">
      <h3 style="margin:0">${esc(g.title)}</h3>
      <div class="by">${esc(g.team_emoji)} ${esc(g.team_name)}</div>
      <div class="muted" style="font-size:14px">${esc(g.description)}</div>
      <div><span class="stars">${starsText(g.avg_stars)}</span> <span class="muted">${g.ratings ? `(${g.ratings})` : ""}</span> ${mine}</div>
      <div class="reactions">${reactions}</div>
    </div>`;
  }).join("");
  $all("[data-game]").forEach(el => {
    el.onclick = () => openGame(Number(el.dataset.game));
    el.onkeydown = e => { if (e.key === "Enter") openGame(Number(el.dataset.game)); };
  });
}

function openGame(id) {
  const g = A.games.find(x => x.id === id);
  if (!g) return;
  A.open = g;
  $("#play-title").textContent = g.title;
  $("#play-by").textContent = `by ${g.team_emoji} ${g.team_name}`;
  $("#play-desc").textContent = g.description;
  loadPlayer();
  renderRating();
  $("#play-modal").classList.remove("hidden");
}

function loadPlayer() {
  const g = A.open;
  const f = document.createElement("iframe");
  f.setAttribute("sandbox", "allow-scripts");
  f.setAttribute("title", g.title);
  f.src = `/play/${g.version_id}`;
  f.addEventListener("load", () => f.focus());
  $("#player").innerHTML = "";
  $("#player").appendChild(f);
}

function renderRating() {
  const g = A.open;
  const area = $("#rate-area");
  if (!A.team) { area.innerHTML = '<p class="muted"><a href="/login">Log in</a> to rate games.</p>'; return; }
  if (g.is_mine) { area.innerHTML = '<p class="muted">This is your game! See what everyone else thinks 😄</p>'; return; }
  if (A.frozen) { area.innerHTML = '<p class="muted">🔒 Voting has closed.</p>'; return; }

  const stars = [1, 2, 3, 4, 5].map(n =>
    `<button class="star-btn ${g.my_rating >= n ? "on" : ""}" data-stars="${n}" aria-label="${n} stars">★</button>`).join("");
  const reacts = (A.info.reactions || []).map(r => `<button class="btn small react-btn ${g.my_reaction === r ? "on" : ""}" data-react="${r}">${r}</button>`).join("");
  const votes = Object.entries(A.info.award_categories).map(([cat, label]) =>
    `<button class="btn small vote-btn ${g.my_votes.includes(cat) ? "on" : ""}" data-vote="${cat}">${label}</button>`).join("");
  area.innerHTML = `
    <div class="rate-row"><b>Your rating:</b> ${stars}</div>
    <div class="rate-row"><b>Reaction:</b> ${reacts}</div>
    <div class="rate-row"><b>Vote for an award:</b> ${votes} <span class="muted" style="font-size:13px">(one game per award, change any time)</span></div>`;

  $all("[data-stars]", area).forEach(b => b.onclick = () => rate(Number(b.dataset.stars), g.my_reaction));
  $all("[data-react]", area).forEach(b => b.onclick = () => {
    if (!g.my_rating) { toast("Give it some stars first! ⭐"); return; }
    rate(g.my_rating, b.dataset.react);
  });
  $all("[data-vote]", area).forEach(b => b.onclick = async () => {
    try {
      await api(`/api/arcade/${g.id}/vote`, { method: "POST", body: { category: b.dataset.vote } });
      b.classList.add("on");
      toast("Vote saved! 🗳️");
      await refreshOpen();
    } catch (err) { toast(err.message, true); }
  });
}

async function rate(stars, reaction) {
  try {
    await api(`/api/arcade/${A.open.id}/rate`, { method: "POST", body: { stars, reaction } });
    toast(`Thanks! You gave ${"⭐".repeat(stars)}`);
    await refreshOpen();
  } catch (err) { toast(err.message, true); }
}

async function refreshOpen() {
  const id = A.open.id;
  await load();
  A.open = A.games.find(x => x.id === id) || A.open;
  renderRating();
}

$("#btn-restart").onclick = loadPlayer;
$all("[data-close]").forEach(b => b.onclick = closeModal);
$("#play-modal").addEventListener("click", e => { if (e.target.id === "play-modal") closeModal(); });
function closeModal() {
  $("#play-modal").classList.add("hidden");
  $("#player").innerHTML = "";
  A.open = null;
}

(async () => {
  A.info = await api("/api/info");
  await load();
  // Keep the list fresh while nobody is playing.
  setInterval(() => { if (!A.open) load().catch(() => {}); }, 10000);
})().catch(err => toast(err.message, true));
