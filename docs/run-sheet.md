# Run sheet: 2½ hour session

**Group:** 6-12 Scouts aged 10-14, in teams of 2-3 per laptop.
**Leaders:** at least 2. One runs the front, one floats and watches the dashboard.

## Before they arrive (30 min)

- [ ] Power up the router, then both Pis, **at least 20 minutes before** scouts arrive.
- [ ] Open `/leader` on the leader laptop. Check both workers are 🟢 and show **🔥 Warm ✓**, then set the **event name**. Warming up pre-loads the starter games so first requests are fast. It starts by itself; press **🔥 Warm up AI** if a Pi was restarted.
- [ ] Put `/leader` on the projector so the **join code** and the address (`http://scout.local` or the IP) are visible.
- [ ] Open `/studio` on each laptop's browser, so it lands on the join page.
- [ ] **Pause the AI** until the build starts, so nobody starts early.

## Timetable

| Time | What | Notes |
|---|---|---|
| 0:00 | **Welcome + "What is an AI agent?"** (10 min) | Script below. Live demo on the projector with your own team. |
| 0:10 | **Team jobs + rules** (5 min) | Roles below. Swap roles every 15 minutes, when a leader calls "**Switch!**" |
| 0:15 | **Join + pick a starter** (10 min) | Unpause the AI. Everyone's first change: swap the player emoji (e.g. "make the player a 🦖"). Quick and nearly always works. |
| 0:25 | **Build time** (75 min) | Leaders circulate. Prompt with "what's your next idea?", "can you find the line that changed?", "press Explain on it". |
| 1:40 | **Polish + publish** (10 min) | Leader shouts the 10-minute warning at 1:30. Everyone must publish. A good title and a one-line "how to play" matter! |
| 1:50 | **Arcade** (25 min) | Teams play every other team's game, give stars and a reaction, and vote for the awards. They can't vote for their own. |
| 2:15 | **Close voting → Awards** (10 min) | Dashboard: 🔒 Close voting, then 🏆 Reveal awards. Show `/awards` and click each card to reveal it. |
| 2:25 | **Reflection** (5 min) | Questions below. Download the zip for USB sticks. |

## Team jobs

- **🧑‍✈️ Pilot**: types the ideas to the AI.
- **🧭 Navigator**: watches the code panel and finds what changed. Uses *Explain this* and tells the team what it means.
- **🎮 Tester**: plays each new version and decides if it's better. If not, uses **History** to go back.

## Script: "What is an AI agent?" (10 min)

> *"Who's used an AI chatbot? You ask, it answers. Today we're using something a bit different: an **AI agent**. An agent doesn't just answer, it **does a job in steps**, a bit like you following a recipe."*

Demo on the projector. Ask for something like "make the enemies pink and faster", and point out each step as it lights up:

1. **🤔 Planning**: it reads the whole game and decides what to change.
2. **✍️ Writing code**: you can watch it type! It only changes a few lines.
3. **🧪 Testing**: it **plays the game** itself, in that little window, to check nothing's broken.
4. **🔧 Fixing a bug**: if the game crashed, it reads the error and tries to fix its own mistake.
5. **✅ Done**: the green lines show exactly what it changed.

> *"This AI is running on these two little computers here, the Raspberry Pis. It's not on the internet at all! It's quite a small AI, so it's not perfect. It makes mistakes, and it's slow if you ask for something huge. **Small, clear ideas work best.** You are the boss: if you don't like what it did, use History to go back."*

**Tips for good requests** (put them on a slide):
- ✅ "Make the bombs red and twice as big"
- ✅ "Add a power-up star that gives an extra life"
- ❌ "Make it into Minecraft" (way too big!)
- 💡 One idea at a time. Build up step by step.

## While they build: things leaders can watch for

- **Dashboard → Recent AI requests**: a team with lots of ❌ might be asking for things that are too big. Help them break the idea into small steps.
- **A long queue**: remind teams waiting in the queue to visit the Arcade or read their code with *Explain this*.
- **⚠️ hot** on a worker: give the Pis more air.
- **An unkind game or title**: dashboard → Games → **Hide**.

## Reflection questions (pick 2-3)

1. What did the AI get wrong? How did you (or it) fix it?
2. Find one line of code you now understand. What does it do?
3. The AI tested its own work. Why is testing important, even for people?
4. Who was really in charge: you or the AI?
5. This AI ran on two tiny computers with no internet. What's good about that? (Privacy, works anywhere, no cost.)

## Badges

This session covers making a digital project, testing it, and sharing it with others. Check the current requirements of your association's digital and technology badges (for example, Scouts UK's *Digital Maker* staged activity badge) to see which stages it can count towards.

## Afterwards

- Dashboard → **💾 Download all games**. Each game is a single HTML file that works on any computer, even offline. Share the zip, or copy it onto USB sticks.
- Keep `/opt/scout/data/scout.db` if you want the history. Move it aside to start fresh for the next event.
