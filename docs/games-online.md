# Putting the games online for families

After a session, Scout Code can publish the scouts' games to a small website so families can play them at home. It uses **GitHub Pages**, which is free.

- **Each group uses its own website.** If another group or leader uses Scout Code, they follow this guide with *their own* GitHub account. Nothing is shared with anyone else's.
- **The website has:**
  - a home page listing your sessions;
  - each session's arcade, with the evening's awards;
  - on-screen buttons so games work on phones and tablets.
- **It's kept low-key and temporary:**
  - every page tells search engines not to list it;
  - each session has a hard-to-guess address;
  - sessions are **removed automatically** after the number of days you choose (30 by default);
  - you can take any session, or everything, offline from the dashboard at any time.
- **What goes online:** only games the teams **published to the Arcade**, and not ones a leader hid or left out. The leaders' demo team's games, team PINs and what the scouts typed to the AI never go online.

## Safeguarding first

Before anything goes online, the dashboard asks you to confirm three things:

1. **Parents and carers have agreed** to their young people's games being shared online. Follow your organisation's consent and safeguarding policies.
2. **No real names**: team names and game titles must not include anyone's real name. You can also switch on "Hide team names online", which shows "Team 1, Team 2…" instead.
3. **You've checked the preview**: use "Choose" in Past events to leave any game out.

## One-time set-up (about 10 minutes, on any computer)

### 1. Make a GitHub account and a repository
1. Sign up at github.com, ideally with a group or leader-team account rather than a personal one.
2. Click **+** → **New repository**.
3. Name it something like `scout-games`.
4. Choose **Public**. GitHub Pages is free for public repositories, and the site is "unlisted" by design, not secret.
5. Click **Create repository**. You don't need to add any files.

### 2. Make an access token for that repository only
1. GitHub → your picture → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. **Name:** "Scout Code Pi". **Expiration:** your choice (e.g. 1 year).
3. **Repository access:** **Only select repositories** → choose `scout-games`.
4. **Repository permissions:**
   - **Contents:** Read and write
   - **Pages:** Read and write
   - **Workflows:** Read and write (needed for automatic clean-up)
   - (Metadata: Read-only is added automatically.)
5. Click **Generate token** and copy it. It starts with `github_pat_`.

The token can only change that one repository. It's stored only on your basecamp Pi (in `/opt/scout/data/publish.json`, readable only by the Scout Code user), and the dashboard never shows it again.

### 3. Enter it on the leader dashboard
1. Leader dashboard → **🌐 Games online**. Fill in:
   - **Repository:** `your-account/scout-games`
   - **Access token:** paste it
   - **Website title** and **days** to keep each session.
2. Click **💾 Save settings**.

## After each session

1. **Connect the basecamp Pi to the internet.** Either plug the travel router's internet port into a home or hall router, or connect the Pi to Wi-Fi (`sudo nmtui`).
2. Open the leader dashboard → **🌐 Games online**:
   1. **🔌 Test connection**: it should say "Connected to …".
   2. **👀 Preview the site**: check every game. Use **Choose** in Past events to leave any out.
   3. Tick the three safeguarding boxes.
   4. **🌐 Put tonight's games online.**
3. **Wait a minute or two**, then use **📋 Copy** next to the session in **Past events** and paste the link into your message to parents.

The first time, Scout Code switches GitHub Pages on for you. If the status says it couldn't, open your repository on github.com → **Settings** → **Pages** → **Deploy from a branch** → branch **main**, folder **/ (root)** → **Save**, then press **🔄 Sync now**.

## Clearing down

- **Automatic:**
  - Each session disappears after its end date. A small daily job on GitHub removes it, even if the Pi is switched off.
  - The home page also hides it straight away.
  - The Pi removes expired sessions whenever it next syncs.
- **Manual:** untick **Online** for a session in Past events, or press **Take everything offline**, then **🔄 Sync now**.
- **Extend:** press **+30 days** next to a session, then sync.
- **Each sync replaces the whole website** with a single fresh copy, so removed sessions don't linger in the repository's history.

> GitHub pauses scheduled jobs in repositories that haven't changed for 60 days. Expired sessions are still hidden from the home page, and are deleted the next time the Pi syncs. To remove everything for good, you can also delete the repository on github.com.

## Not using GitHub?

**📦 Download website zip** gives the same website as a folder of files. You can upload it to any web host, for example Netlify Drop or your group's own web space. Automatic clean-up only works on GitHub, so remove sessions by uploading a new zip.

## Troubleshooting

| Message | What to do |
|---|---|
| Can't reach GitHub | The Pi isn't online. Check its cable or Wi-Fi. |
| GitHub didn't accept the token | It was mistyped or has expired. Make a new one and paste it in. |
| Can't find your-account/scout-games | Check the name, and that the token was given access to that repository. |
| GitHub refused the daily clean-up job | Give the token **Workflows: Read and write**, or untick automatic clean-up. |
| GitHub Pages isn't switched on | Follow the Settings → Pages steps above. |
