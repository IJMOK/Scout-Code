// Session slides for the projector. Each slide is one entry in SLIDES below: edit the
// words freely. `live: true` slides refresh every few seconds with the event's real data.

const HOST = location.host;
let live = { status: null, publish: null };

const SLIDES = [
  {
    id: "welcome",
    notes: "Welcome everyone. Introduce the leaders. Tonight is about making games WITH an AI, and finding out how it works and where it goes wrong. Nobody needs to know how to code.",
    render: () => `
      <div class="center">
        <div class="big-emoji">🎮🤖</div>
        <h1>${esc(live.status ? live.status.event_name : "Scout Code")}</h1>
        <p class="soft" style="font-size:1.3em">Tonight you'll build your own video game… with an AI as your team-mate.</p>
        <p class="soft">No coding experience needed.</p>
      </div>`,
  },
  {
    id: "plan",
    notes: "Run through the evening quickly. Point out there's time for playing each other's games at the end, and awards!",
    render: () => `
      <div class="kicker">Tonight</div>
      <h2>The plan</h2>
      <div class="cols">
        <div>
          <h3>🎯 Our aims</h3>
          <ul>
            <li>Build and improve a game by telling an AI what you want</li>
            <li>Find out how an <b>AI agent</b> works</li>
            <li>Use AI <b>safely</b> and spot when it gets things wrong</li>
            <li>Play each other's games and vote for the best</li>
          </ul>
        </div>
        <div class="box">
          <h3>⏱️ Timetable</h3>
          <ul style="list-style:none;padding:0">
            <li>👋 Welcome &amp; how it works · 15 min</li>
            <li>🔑 Join &amp; first change · 10 min</li>
            <li>🛠️ Build time · 75 min</li>
            <li>🌟 Polish &amp; publish · 10 min</li>
            <li>🕹️ Arcade: play &amp; vote · 25 min</li>
            <li>🏆 Awards &amp; reflection · 15 min</li>
          </ul>
        </div>
      </div>`,
  },
  {
    id: "what-is-ai",
    notes: "Keep this simple. The AI has learnt patterns from loads of text and code, and predicts what comes next. It sounds clever but it doesn't understand or know things like a person. Ask: who has used a chatbot before?",
    render: () => `
      <div class="kicker">First, what is AI?</div>
      <h2>A super-powered guessing machine 🔮</h2>
      <div class="cols">
        <div>
          <p>An AI like ours has looked at <b>huge amounts of text and code</b>, and learnt patterns from it.</p>
          <p>When you ask it something, it <b>predicts</b> what words or code should come next, one piece at a time.</p>
        </div>
        <div class="box">
          <p>✅ Great at patterns: it has "seen" lots of games</p>
          <p>❌ It doesn't <i>understand</i> like you do</p>
          <p>❌ It can be confidently wrong</p>
          <p>❌ It isn't a person, and doesn't know you</p>
        </div>
      </div>`,
  },
  {
    id: "chat-vs-agent",
    notes: "The key idea of the evening. A chatbot answers and stops: YOU have to check and try it. An agent works towards a goal in steps and checks its own work using tools. Our agent's tool is playing the game to see if it crashes.",
    render: () => `
      <div class="kicker">Chat vs agent</div>
      <h2>Two kinds of AI helper</h2>
      <div class="cols">
        <div class="box">
          <h3>💬 Chatbot</h3>
          <div class="flow"><span class="step">You ask</span><span class="arrow">→</span><span class="step">It answers</span><span class="arrow">→</span><span class="step">Done</span></div>
          <p class="soft">Like asking a friend a question. <b>You</b> have to check if the answer actually works.</p>
        </div>
        <div class="box good">
          <h3>🤖 Agent</h3>
          <div class="flow loop"><span class="step">Goal</span><span class="arrow">→</span><span class="step">Plan</span><span class="arrow">→</span><span class="step">Do it</span><span class="arrow">→</span><span class="step">Check its own work</span><span class="arrow">→</span><span class="step">Fix</span></div>
          <p class="soft">Works in steps, <b>uses tools</b> and tests its work, and keeps going until it's done.</p>
        </div>
      </div>
      <p class="center">Tonight's AI is an <b>agent</b>: its tool is <b>test-playing your game</b> to see if it works.</p>`,
  },
  {
    id: "our-agent",
    notes: "These are the exact steps they'll see light up on screen. Point out the Fixing step: sometimes the AI breaks the game, notices, and fixes its own mistake. That's the agent part.",
    render: () => `
      <div class="kicker">Our agent tonight</div>
      <h2>What happens when you ask for a change</h2>
      <div class="flow loop" style="font-size:1.2em;justify-content:center">
        <span class="step">⏳ Waiting</span><span class="arrow">→</span>
        <span class="step">🤔 Planning</span><span class="arrow">→</span>
        <span class="step">✍️ Writing code</span><span class="arrow">→</span>
        <span class="step">🧪 Testing</span><span class="arrow">→</span>
        <span class="step">🔧 Fixing a bug</span><span class="arrow">→</span>
        <span class="step">✅ Done</span>
      </div>
      <div class="cols3" style="margin-top:.8em">
        <div class="box"><h3>🤔 Plans</h3><p class="soft">Reads your whole game and decides what to change.</p></div>
        <div class="box"><h3>🧪 Tests</h3><p class="soft">Plays your new game for a few seconds, pressing the keys.</p></div>
        <div class="box"><h3>🔧 Fixes</h3><p class="soft">If it crashed, it reads the error and has another go.</p></div>
      </div>
      <p class="center">Then the lines it changed <b style="color:#2ed573">glow green</b> in the code.</p>`,
  },
  {
    id: "risks",
    dense: true,
    notes: "Go through each row. Emphasise: never type real names, addresses, school, or anything personal. Leaders can see every request. Nothing goes on the internet tonight. If anything worries you, tell a leader.",
    render: () => `
      <div class="kicker">Staying safe</div>
      <h2>The risks, and how we're handling them</h2>
      <table class="risks">
        <tr><th>Risk</th><th>What we're doing about it</th></tr>
        <tr><td>🤪 The AI gets things wrong</td><td>It tests its own work, <b>you</b> test it too, and <b>History</b> lets you undo anything</td></tr>
        <tr><td>🧠 It sounds clever, but it isn't a person</td><td><b>You're the boss.</b> It's fine to disagree with it or ignore it</td></tr>
        <tr><td>🔒 Personal information</td><td><b>Never type real names, addresses, schools or photos.</b> Use made-up team names</td></tr>
        <tr><td>😠 Unkind or rude content</td><td>A filter blocks it, and <b>leaders can see every request</b></td></tr>
        <tr><td>🌍 The internet</td><td>Tonight everything stays <b>in this room</b>: no internet, and games run in a safe box</td></tr>
      </table>
      <p class="center soft">Anything worries you, or seems weird? <b>Tell a leader.</b> You won't be in trouble.</p>`,
  },
  {
    id: "limits",
    notes: "Explain WHY we're using a small local AI: privacy, no accounts, free, and it shows how AI really works. The trade-off is it's slower and makes more mistakes than ChatGPT-style AIs. Big ideas = break them into small steps.",
    render: () => `
      <div class="kicker">Our set-up</div>
      <h2>A small AI, on purpose</h2>
      <div class="cols">
        <div>
          <p>Our AI runs on <b>two Raspberry Pis</b> 🍓🍓 right here, with no internet.</p>
          <div class="bar-chart">
            <div style="width:6%">Ours: ~3 billion</div>
            <div style="width:100%;background:#444">Big online AIs: hundreds of billions of "connections"</div>
          </div>
          <ul>
            <li>⏱️ About <b>30-60 seconds</b> per idea, sometimes more</li>
            <li>🚶 A <b>queue</b>: one idea per team at a time</li>
            <li>🤏 Best at <b>small, clear</b> changes</li>
          </ul>
        </div>
        <div class="box good">
          <h3>Why do it this way?</h3>
          <p>🔒 <b>Private</b>: nothing you type leaves this room</p>
          <p>🆓 <b>Free</b>, no accounts or sign-ups</p>
          <p>🔍 You can <b>see how AI really works</b>, mistakes and all</p>
          <p>🏕️ Works anywhere, even in a field!</p>
        </div>
      </div>`,
  },
  {
    id: "demo",
    notes: "Click 'Live demo' to open the studio as the leaders' team in a new tab, and do a first change like 'make the player a 🦖'. Show the steps lighting up, the green lines, then Play. Show History to undo. The demo team's games don't count for awards.",
    render: () => `
      <div class="kicker">How it works</div>
      <h2>Four steps</h2>
      <div class="cols" style="grid-template-columns:repeat(4,1fr);gap:.8em">
        <div><h3>1. Pick a game</h3><div class="mock"><div class="bar">Start a new game</div><div class="tiles"><span>🚀</span><span>🐸</span><span>🐍</span><span>🐭</span><span>🧺</span><span>🐤</span><span>🧱</span><span>☄️</span></div></div></div>
        <div><h3>2. Ask the AI</h3><div class="mock"><div class="bar">🤖 Ask the AI</div><div class="input"><span>make the player a 🦖</span><span class="go">Go!</span></div></div></div>
        <div><h3>3. Watch it work</h3><div class="mock"><div class="chips"><span>⏳</span><span>🤔</span><span>✍️ Writing</span><span>🧪</span><span>✅</span></div><div class="code" style="margin-top:.4em">player: "🚀",<br><span class="glow">player: "🦖",</span></div></div></div>
        <div><h3>4. Play &amp; check</h3><div class="mock"><div class="bar">▶️ Play · 🕘 History</div><div style="background:#0b0b2b;color:#fff;border-radius:.3em;text-align:center;font-size:2em">🦖 👾</div></div></div>
      </div>
      <p class="center" style="margin-top:.8em"><button class="btn primary big" id="live-demo">▶ Live demo</button></p>
      <p class="center soft">Highlight any code and press <b>💬 Explain this</b> to find out what it does.</p>`,
    after: () => { $("#live-demo").onclick = openDemo; },
  },
  {
    id: "ideas",
    notes: "The single most useful tip of the night: small ideas, one at a time. Big ones fail or take ages.",
    render: () => `
      <div class="kicker">Top tip</div>
      <h2>Small ideas work best 💡</h2>
      <div class="cols">
        <div class="box good">
          <h3>✅ Great</h3>
          <p>"Make the bombs red and twice as big"</p>
          <p>"Add a star that gives an extra life"</p>
          <p>"Make the enemies faster each level"</p>
        </div>
        <div class="box bad">
          <h3>❌ Too big</h3>
          <p>"Turn it into Minecraft"</p>
          <p>"Make it 3D with online multiplayer"</p>
          <p>"Add ten new levels, a shop and a boss"</p>
        </div>
      </div>
      <p class="center">One idea at a time. <b>Build it up step by step.</b> Didn't like it? Use <b>🕘 History</b> to go back.</p>`,
  },
  {
    id: "jobs",
    notes: "Assign roles in each team now. A leader will shout SWITCH every 15 minutes. Remind them: be kind, hands off other teams' laptops.",
    render: () => `
      <div class="kicker">Teamwork</div>
      <h2>Team jobs (swap every 15 minutes!)</h2>
      <div class="cols3">
        <div class="box"><div class="big-emoji" style="font-size:2em">🧑‍✈️</div><h3>Pilot</h3><p class="soft">Types the ideas to the AI.</p></div>
        <div class="box"><div class="big-emoji" style="font-size:2em">🧭</div><h3>Navigator</h3><p class="soft">Watches the code, finds the green lines, uses <b>Explain this</b>.</p></div>
        <div class="box"><div class="big-emoji" style="font-size:2em">🎮</div><h3>Tester</h3><p class="soft">Plays each new version. Better or worse?</p></div>
      </div>
      <p class="center">When a leader shouts <b>"SWITCH!"</b>, everyone moves one job along.</p>
      <p class="center soft">Be kind to other teams · Hands off other laptops · Stuck? Ask a leader.</p>`,
  },
  {
    id: "join",
    live: true,
    notes: "Leave this up while teams join. You can see teams appear live. Remind them to write their team PIN down: they'll need it if they swap laptops. Unpause the AI when everyone is in (press P).",
    render: () => {
      const s = live.status;
      const teams = s ? s.teams.filter(t => !t.demo) : [];
      return `
      <div class="center">
        <div class="kicker">Join now</div>
        <p>Open <span class="address">http://${esc(HOST)}</span> and type the code:</p>
        <div class="joincode-big">${esc(s ? s.join_code : "····")}</div>
        <p class="soft">Pick a team name (not your real names!) and an emoji. <b>Write down your team PIN.</b></p>
        <h3>${teams.length} team${teams.length === 1 ? "" : "s"} joined</h3>
        <div class="team-grid">${teams.map(t => `<span class="team-chip">${esc(t.emoji)} ${esc(t.name)}</span>`).join("")}</div>
        ${s && s.ai_paused ? '<p><span class="paused-banner">AI paused: press P to let teams start</span></p>' : ""}
      </div>`;
    },
  },
  {
    id: "build",
    live: true,
    notes: "S starts/pauses the timer, + and - change it by 5 minutes. Leave this up during build time. At 10 minutes left, warn everyone to start polishing and publishing.",
    render: () => {
      const s = live.status;
      const teams = s ? s.teams.filter(t => !t.demo) : [];
      const ideas = teams.reduce((n, t) => n + (t.successes || 0), 0);
      const published = s ? s.games.filter(g => !g.hidden && !g.demo).length : 0;
      return `
      <div class="center">
        <div class="kicker">Build time 🛠️</div>
        <div class="timer" id="timer">${timerText()}</div>
        <p class="soft" id="timer-hint">${timer.running ? "" : "Press S to start the timer"}</p>
        <div class="stats">
          <div><b>${teams.length}</b>teams</div>
          <div><b>${ideas}</b>ideas made real</div>
          <div><b>${s ? s.queue.filter(j => j.status === "queued").length : 0}</b>waiting for the AI</div>
          <div><b>${published}</b>games in the Arcade</div>
        </div>
        <p class="soft">Remember: small ideas · test it · History to undo · SWITCH jobs every 15 minutes</p>
      </div>`;
    },
  },
  {
    id: "pause",
    live: true,
    notes: "Use any time you need everyone's attention. P pauses the AI so nobody starts a new idea while you talk (anything already running finishes). Press P again to resume.",
    render: () => {
      const paused = live.status && live.status.ai_paused;
      return `
      <div class="center">
        <div class="big-emoji">✋</div>
        <h1>Eyes up front!</h1>
        <p>Hands off keyboards for a moment, please.</p>
        <p>${paused ? '<span class="paused-banner">⏸ AI paused</span>' : '<span class="running-banner">AI running</span>'}</p>
      </div>`;
    },
  },
  {
    id: "arcade",
    live: true,
    notes: "Make sure everyone has pressed Publish. Then they visit the Arcade from the studio's top bar, play every other team's game, give stars and a reaction, and vote in the three awards. Close voting from the dashboard before the awards.",
    render: () => {
      const s = live.status;
      const published = s ? s.games.filter(g => !g.hidden && !g.demo).length : 0;
      return `
      <div class="kicker">Arcade time 🕹️</div>
      <h2>Play everyone's games</h2>
      <div class="cols">
        <div>
          <ol>
            <li>Press <b>🌟 Publish</b> on your game (give it a great name!)</li>
            <li>Open the <b>🕹️ Arcade</b> from the top bar</li>
            <li>Play every other team's game</li>
            <li>Give ⭐ stars and a reaction 😂🤯🔥</li>
            <li>Vote: <b>🎉 Most Fun</b> · <b>🎨 Best Looking</b> · <b>💡 Most Creative</b></li>
          </ol>
          <p class="soft">You can't vote for your own game. Nice try 😄</p>
        </div>
        <div class="box center">
          <b style="font-size:3em;color:#ffd400">${published}</b>
          <p>game${published === 1 ? "" : "s"} in the Arcade</p>
          <p>${s && s.voting_frozen ? '<span class="paused-banner">🔒 Voting closed</span>' : '<span class="running-banner">Voting open</span>'}</p>
          <p><a class="btn" href="/awards" target="_blank">🏆 Open the awards screen</a></p>
        </div>
      </div>`;
    },
  },
  {
    id: "reflect",
    notes: "Pick two or three questions. Draw out: the AI made mistakes, who noticed and fixed them, and why testing matters.",
    render: () => `
      <div class="kicker">Before we go</div>
      <h2>Let's think about it 💭</h2>
      <ul style="font-size:1.1em">
        <li>What did the AI get <b>wrong</b>? How did you (or it) fix it?</li>
        <li>Find one line of code you now understand. What does it do?</li>
        <li>The AI <b>tested its own work</b>. Why does testing matter, even for people?</li>
        <li>Who was really in charge: <b>you or the AI</b>?</li>
        <li>Our AI ran on two tiny computers with no internet. What's good about that?</li>
      </ul>`,
  },
  {
    id: "thanks",
    notes: "Thank everyone. If games are going online, tell them the website and that it disappears after the set number of days. Shut down the Pis from the dashboard at the end.",
    render: () => {
      const p = live.publish;
      const mine = p && p.sessions.find(x => x.event_id && x.event_id === p.current_event_id && x.online);
      const days = p ? p.settings.expiry_days : 30;
      const site = p && p.site_url && p.settings.configured ? p.site_url : "";
      return `
      <div class="center">
        <div class="big-emoji">🎉</div>
        <h1>Thank you, game makers!</h1>
        ${site && mine ? `<p>Your games will be online for families to play for <b>${days} days</b>:</p>
          <p class="address">${esc(site)}</p>
          <p class="soft">(Your leaders will send the link home.)</p>`
        : `<p class="soft">Ask your leaders about playing your games at home.</p>`}
      </div>`;
    },
  },
];

// --------------------------------------------------------------------------- navigation

let index = Math.max(0, SLIDES.findIndex(s => "#" + s.id === location.hash));
let lastHtml = "";
const channel = "BroadcastChannel" in window ? new BroadcastChannel("scout-present") : null;
const presenter = new URLSearchParams(location.search).has("notes");

function show(i, fromChannel = false) {
  index = Math.min(Math.max(i, 0), SLIDES.length - 1);
  const slide = SLIDES[index];
  history.replaceState(null, "", (presenter ? "?notes" : "") + "#" + slide.id);
  lastHtml = "";
  draw(true);
  $("#counter").textContent = `${index + 1} / ${SLIDES.length}`;
  $("#notes-text").textContent = slide.notes || "";
  const next = SLIDES[index + 1];
  $("#notes-next").textContent = next ? `Next: ${next.id}` : "Last slide";
  if (channel && !fromChannel) channel.postMessage({ slide: index });
}

function draw(force = false) {
  const slide = SLIDES[index];
  const html = slide.render();
  if (!force && html === lastHtml) return;
  lastHtml = html;
  const el = $("#slide");
  if (force) {  // replay the entrance animation
    el.style.animation = "none";
    void el.offsetWidth;
    el.style.animation = "";
  }
  el.innerHTML = html;
  el.classList.toggle("dense", !!slide.dense);
  if (slide.after) slide.after();
  if (presenter) document.querySelector(".presenter-head").textContent = `${index + 1}/${SLIDES.length}: ${slide.id}`;
}

async function poll() {
  try {
    live.status = await api("/api/leader/status");
  } catch (err) {
    if (err.status === 401) location.href = "/leader";
    return;
  }
  if (SLIDES[index].live || !live.publish) {
    try { live.publish = await api("/api/leader/publish"); } catch (err) { /* optional */ }
  }
  if (SLIDES[index].live || SLIDES[index].id === "welcome" || SLIDES[index].id === "thanks") draw();
}

async function togglePause() {
  const paused = !(live.status && live.status.ai_paused);
  await api("/api/leader/settings", { method: "POST", body: { ai_paused: paused } });
  toast(paused ? "⏸ AI paused" : "▶️ AI running again");
  await poll();
}

async function openDemo() {
  const tab = window.open("about:blank", "_blank");
  try {
    await api("/api/leader/demo-team", { method: "POST" });
    tab.location = "/studio";
  } catch (err) { tab.close(); toast(err.message, true); }
}

// --------------------------------------------------------------------------- build timer (kept if the page reloads)

let timer = { total: 75 * 60, endsAt: null, left: 75 * 60, running: false };
try { Object.assign(timer, JSON.parse(localStorage.getItem("scout-timer") || "{}")); } catch (e) { /* ignore */ }

function secondsLeft() {
  return timer.running ? Math.max(0, Math.round((timer.endsAt - Date.now()) / 1000)) : timer.left;
}

function timerText() {
  const s = secondsLeft();
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function saveTimer() {
  try { localStorage.setItem("scout-timer", JSON.stringify(timer)); } catch (e) { /* ignore */ }
}

function timerKey(key) {
  if (key === "s") {
    if (timer.running) { timer.left = secondsLeft(); timer.running = false; }
    else { timer.endsAt = Date.now() + timer.left * 1000; timer.running = true; }
  } else {
    const delta = key === "+" || key === "=" ? 300 : -300;
    if (timer.running) timer.endsAt = Math.max(Date.now(), timer.endsAt + delta * 1000);
    else timer.left = Math.max(0, timer.left + delta);
  }
  saveTimer();
  lastHtml = "";
  draw();
}

setInterval(() => {
  const el = $("#timer");
  if (!el) return;
  const s = secondsLeft();
  el.textContent = timerText();
  el.classList.toggle("warn", s <= 600 && s > 120);
  el.classList.toggle("end", s <= 120);
}, 500);

// --------------------------------------------------------------------------- keys

document.addEventListener("keydown", e => {
  if (e.target.closest && e.target.closest("input, textarea")) return;
  const k = e.key;
  if (["ArrowRight", "PageDown", " "].includes(k)) { e.preventDefault(); show(index + 1); }
  else if (["ArrowLeft", "PageUp"].includes(k)) { e.preventDefault(); show(index - 1); }
  else if (k === "Home") show(0);
  else if (k === "End") show(SLIDES.length - 1);
  else if (k === "f" || k === "F") {
    if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {});
  } else if (k === "n" || k === "N") $("#notes").classList.toggle("hidden");
  else if (k === "w" || k === "W") window.open("/present?notes#" + SLIDES[index].id, "scout-notes", "width=900,height=700");
  else if (k === "b" || k === "B" || k === ".") $("#blank").classList.toggle("hidden");
  else if (k === "p" || k === "P") togglePause().catch(err => toast(err.message, true));
  else if (k === "d" || k === "D") window.open("/leader", "_blank");
  else if (SLIDES[index].id === "build" && ["s", "S", "+", "=", "-"].includes(k)) timerKey(k.toLowerCase());
});
document.addEventListener("fullscreenchange", () => document.body.classList.toggle("fullscreen", !!document.fullscreenElement));
$("#blank").onclick = () => $("#blank").classList.add("hidden");
window.addEventListener("hashchange", () => {
  const i = SLIDES.findIndex(s => "#" + s.id === location.hash);
  if (i >= 0 && i !== index) show(i);
});

// The notes window (W) follows the projector, and moving there moves the projector too.
if (channel) channel.onmessage = e => { if (typeof e.data.slide === "number") show(e.data.slide, true); };
if (presenter) {
  document.body.classList.add("presenter");
  $("#notes").classList.remove("hidden");
  const head = document.createElement("div");
  head.className = "presenter-head";
  document.body.prepend(head);
}

show(index);
poll();
setInterval(poll, 3000);
