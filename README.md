# Tiers Bot

A Discord bot for managing Minecraft PvP tier testing, evaluation tickets, waitlists, and rankings. Includes a Flask web server to display tier data.

## Project Structure

- `main.py` — Discord bot (discord.py) with slash commands for tier management
- `server.py` — Flask web server serving the tier rankings frontend
- `index.html` — Frontend HTML for displaying player rankings
- `requirements.txt` — Python dependencies
- `json/` — Directory containing all data files (config, users, tiers, etc.)

---

## main.py — Discord Bot

### Setup

1. Create a Discord bot at https://discord.com/developers/applications
2. Set `BOT_TOKEN` in `main.py` line 3908 (or use environment variables)
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `python main.py` or `python main.py -embed` to send static embeds on startup
5. Optional flags: `-debug` for debug logging

### Commands

#### General Commands (No permissions needed)

| Command | Description |
|---------|-------------|
| `/help` | Display all available commands organized by role |
| `/profile <user>` | View a user's Minecraft profile (UUID, region, rank, skin) |
| `/cooldown` | View your own cooldown status and rank info |
| `/leave` | Leave the active testing queue |

#### Configuration Commands (Administrator only)

| Command | Description |
|---------|-------------|
| `/config channel` | Configure text channels (request-test, waitlist, results, bot-logs, transcripts, tier lists, etc.) |
| `/config category` | Configure ticket categories (passed-eval, high-test-lt2, high-test-ht2, high-test-lt1, high-test-ht1) |
| `/config roles` | Configure Discord roles (staff, high_staff, tester, waitlist roles) |
| `/config tiers` | Configure tier roles (LT5 through HT1) |
| `/configquota <tests>` | Set monthly test quota for testers |

#### Tester Commands (Tester role)

| Command | Description |
|---------|-------------|
| `/start` | Mark yourself as an active tester for your region |
| `/stop` | Mark yourself as inactive |
| `/next` | Open a ticket with the next person in queue |
| `/add <member>` | Add a member to the current ticket |
| `/remove <member>` | Remove a member from the current ticket |
| `/close <tier?>` | Close the ticket with an optional tier result (creates transcript) |
| `/skip` | Skip and delete the current ticket (creates transcript) |
| `/exempt` | Prevent the ticket from auto-closing |
| `/unexempt` | Re-enable auto-closing for the ticket |
| `/passeval` | Mark evaluation as passed (promotes to LT3) |
| `/deadline <days>` | Set a deadline for the current ticket |
| `/list add <user> <region>` | Add a user to a tier list (auto-detects tier from role) |
| `/list remove <user>` | Remove a user from tier lists |

#### Staff Commands (Staff role)

All tester commands, plus:

| Command | Description |
|---------|-------------|
| `/testerstats <time>` | View tester statistics (alltime/month) |
| `/testerlb` | Display testing leaderboard |

#### High Staff Commands (High Staff role)

All staff commands, plus:

| Command | Description |
|---------|-------------|
| `/forceresult <member> <tier> <reason>` | Force assign a test result to a member |
| `/forcestopqueue <region>` | Force stop the testing queue for a region |
| `/forcetest <member> <tester>` | Force create a test ticket for a member |
| `/stats <member>` | View test count for a specific tester |
| `/cooldown set <member> <days> <reason?>` | Set a user's cooldown |
| `/cooldown reset <member> <reason?>` | Reset a user's cooldown |
| `/tester add <member>` | Assign tester role to a member |
| `/tester remove <member>` | Remove tester role from a member |

#### Restriction Key Commands (Restriction Key role)

| Command | Description |
|---------|-------------|
| `/restrict <igns> <discord_accounts> <reason> <time?> <appeal?>` | Restrict users with optional duration & appeal time |
| `/unrestrict <discord_accounts>` | Remove restriction from users |

#### Migration Key Commands (Migration Key role)

| Command | Description |
|---------|-------------|
| `/migrate <user> <tier> <server> <tier_from_server?>` | Migrate a user's tier from another server |

#### Whitelisted Commands

| Command | Description |
|---------|-------------|
| `/wipe` | Wipe all user data, tiers, cooldowns, and stats |
| `/uuid <username>` | Fetch UUID of a Minecraft account |

### Buttons/UI

- **Verify Account** button — Opens a modal to link Discord to Minecraft account
- **Enter Waitlist** button — Opens a modal to join the testing waitlist
- **Join Queue** button — Joins the active testing queue (when testers are online)
- **Claim Ticket** button — Claims an unassigned ticket

### Text Commands

| Command | Description |
|---------|-------------|
| `!format` | Generate a test result format template based on the ticket channel name |

---

## server.py — Flask Web Server

### Setup

```bash
pip install flask
python server.py
```

Then open `http://localhost:8000` in your browser.

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Serves the `index.html` frontend |
| `GET /vanilla`, `/uhc`, `/pot`, `/nethop`, `/smp`, `/sword`, `/axe`, `/mace` | SPA routes — same HTML, frontend handles routing |
| `GET /website_data.json` | Consolidated player/rank data for the frontend **(primary endpoint)** |
| `GET /users.json` | Legacy user data |
| `GET /tiers.json` | Legacy tier data |
| `GET /stats.json` | Legacy stats data |
| `GET /data/<filename>` | Compatibility alias for any allowed JSON file |

The server reads data from local JSON files. `main.py` generates `json/website_data.json` which `server.py` serves to the frontend.

### Data Flow

1. `main.py` creates/updates JSON files under `json/` directory
2. `server.py` reads those local JSON files and serves them over HTTP
3. `index.html` fetches `/website_data.json` and renders player rankings

---

## requirements.txt

```
discord.py>=2.3.0
pymongo>=4.0.0
python-dotenv>=1.0.0
requests>=2.31.0
flask>=2.0.0
```
