import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import requests
import datetime
import asyncio
import io
import sys
import re
from typing import Optional, List

# Debug mode flag
DEBUG_MODE = '-debug' in sys.argv

def debug_print(message: str):
    """Print debug message only if DEBUG_MODE is enabled"""
    if DEBUG_MODE:
        print(f"DEBUG: {message}")

def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r') as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

SEND_EMBEDS_ON_STARTUP = False

def load_tiers_from_json():
    """Load all tiers from local JSON file"""
    return load_json(TIERS_FILE)

def save_tiers_to_json(user_id, tier_data):
    """Save a single user's tier data to local JSON file"""
    tiers = load_json(TIERS_FILE)
    tiers[user_id] = tier_data
    save_json(TIERS_FILE, tiers)

def load_restrictions_from_json():
    """Load restrictions from JSON and migrate old flat format to active/history structure."""
    data = load_json(RESTRICTIONS_FILE)
    if not isinstance(data, dict):
        return {"active": {}, "history": []}
    if "active" in data and "history" in data:
        if not isinstance(data["active"], dict):
            data["active"] = {}
        if not isinstance(data["history"], list):
            data["history"] = []
        return data
    # Migrate old restriction format (flat dict keyed by user ID)
    migrated = {"active": {}, "history": []}
    for discord_id, record in data.items():
        if not discord_id.isdigit():
            continue
        if not isinstance(record, dict):
            continue
        record = dict(record)
        record["active"] = True
        if "restricted_at" not in record:
            record["restricted_at"] = datetime.datetime.now().isoformat()
        migrated["active"][discord_id] = record
        history_record = dict(record)
        history_record["user_id"] = discord_id
        migrated["history"].append(history_record)
    save_json(RESTRICTIONS_FILE, migrated)
    return migrated

def parse_discord_account_ids(discord_accounts: str) -> List[str]:
    """Parse comma-separated Discord IDs or mentions into a list of ID strings."""
    inputs = [item.strip() for item in discord_accounts.split(",") if item.strip()]
    result = []
    for input_value in inputs:
        match = re.search(r"<@!?(\d+)>", input_value)
        if match:
            discord_id = match.group(1)
        else:
            digits_match = re.search(r"(\d{17,20})", input_value)
            discord_id = digits_match.group(1) if digits_match else input_value
        if discord_id.isdigit():
            result.append(discord_id)
    return result

CONFIG_FILE = 'json/config.json'
USERS_FILE = 'json/users.json'
COOLDOWNS_FILE = 'json/cooldowns.json'
TIERS_FILE = 'json/tiers.json'
SESSIONS_FILE = 'json/sessions.json'
EVAL_TICKETS_FILE = 'json/eval.json'
HIGH_TICKETS_FILE = 'json/high.json'
TIER_LISTS_FILE = 'json/tier_lists.json'
RESTRICTIONS_FILE = 'json/restrictions.json'
BLACK = discord.Color.from_rgb(135, 206, 250)

def black_embed(description=None, title=None):
    embed = discord.Embed(description=description, title=title, color=BLACK)
    return embed

config = load_json(CONFIG_FILE)
users = load_json(USERS_FILE)
cooldowns = load_json(COOLDOWNS_FILE)
tiers = {}
eval_tickets = load_json(EVAL_TICKETS_FILE)
high_tickets = load_json(HIGH_TICKETS_FILE)
tier_lists = load_json(TIER_LISTS_FILE)
restrictions = load_restrictions_from_json()

# --- Autocomplete Utilities ---

TIERS = ["HT1", "LT1", "HT2", "LT2", "HT3", "LT3", "HT4", "LT4", "HT5", "LT5"]
REGIONS = ["NA", "EU", "AS", "AU"]

# Tier lists configuration
TIER_LIST_TIERS = ["ht3", "lt2", "ht2", "lt1"]
TIER_LIST_REGIONS = {
    "nae": "NA EAST",
    "nac": "NA CENTRAL", 
    "naw": "NA WEST",
    "eu": "EUROPE",
    "as": "ASIA",
    "au": "AUSTRALIA"
}

RANK_NAMES = {
    "LT5": "Low Tier 5", "HT5": "High Tier 5",
    "LT4": "Low Tier 4", "HT4": "High Tier 4",
    "LT3": "Low Tier 3", "HT3": "High Tier 3",
    "LT2": "Low Tier 2", "HT2": "High Tier 2",
    "LT1": "Low Tier 1", "HT1": "High Tier 1",
    "Unranked": "Unranked"
}

EMOJIS = ["👑", "🥳", "😱", "😭", "😂", "💀"]

def validate_tier(tier):
    """Validate that tier is in the allowed TIERS list"""
    if tier is None:
        return None
    tier_upper = tier.upper()
    if tier_upper not in TIERS:
        return None
    return tier_upper

def update_peak_tier(user_id, new_rank):
    """Update user's peak tier if new rank is higher than current peak"""
    if user_id not in tiers:
        return
    
    current_peak = tiers[user_id].get("peak_tier", "Unranked")
    
    # If user doesn't have a peak tier yet, set it to current rank
    if current_peak == "Unranked":
        tiers[user_id]["peak_tier"] = new_rank
        return
    
    # Check if new rank is higher than current peak tier
    # Higher tiers have lower index in TIERS list (HT1 at index 0 is highest, LT5 at index 9 is lowest)
    try:
        current_peak_index = TIERS.index(current_peak)
        new_rank_index = TIERS.index(new_rank)
        
        if new_rank_index < current_peak_index:
            tiers[user_id]["peak_tier"] = new_rank
    except ValueError:
        # If either rank is not in TIERS list, don't update peak
        pass

def initialize_peak_tiers():
    """Initialize peak tiers for existing users who don't have them set"""
    initialized_count = 0
    for user_id, user_data in tiers.items():
        if "peak_tier" not in user_data:
            current_rank = user_data.get("rank", "Unranked")
            if current_rank != "Unranked" and current_rank in TIERS:
                user_data["peak_tier"] = current_rank
                initialized_count += 1
    
    if initialized_count > 0:
        save_json(TIERS_FILE, tiers)
        print(f"Initialized peak tiers for {initialized_count} existing users")
    
    return initialized_count

def generate_website_data():
    """Generate consolidated JSON data for the website with all current data"""
    website_data = {
        "players": {},
        "stats": stats,
        "config": {
            "regions": REGIONS,
            "tiers": TIERS,
            "rank_names": RANK_NAMES
        }
    }
    
    # Process users with tiers (ranked players)
    for tier_key, tier_data in tiers.items():
        tier_key_str = str(tier_key)
        user_found = False
        
        # Find matching user in users.json
        for user_key, user_info in users.items():
            user_key_str = str(user_key)
            if tier_key_str == user_key_str:
                user_found = True
                website_data["players"][tier_key_str] = {
                    "username": user_info.get("username", "Unknown"),
                    "uuid": user_info.get("uuid", "N/A"),
                    "tier": tier_data.get("rank", "Unranked"),
                    "peak_tier": tier_data.get("peak_tier", tier_data.get("rank", "Unranked")),
                    "region": user_info.get("region", "Unknown"),
                    "pref_server": user_info.get("pref_server", ""),
                    "verified": True,
                    "cooldown": cooldowns.get(tier_key_str, {})
                }
                break
        
        # If no matching user found, create entry with tier data only
        if not user_found:
            website_data["players"][tier_key_str] = {
                "username": tier_data.get("username", "Unknown"),
                "uuid": tier_data.get("uuid", "N/A"),
                "tier": tier_data.get("rank", "Unranked"),
                "peak_tier": tier_data.get("peak_tier", tier_data.get("rank", "Unranked")),
                "region": "Unknown",
                "pref_server": "",
                "verified": True,
                "cooldown": cooldowns.get(tier_key_str, {})
            }
    
    # Add users without tiers (unranked verified users)
    for user_key, user_info in users.items():
        user_key_str = str(user_key)
        if user_key_str not in website_data["players"]:
            website_data["players"][user_key_str] = {
                "username": user_info.get("username", "Unknown"),
                "uuid": user_info.get("uuid", "N/A"),
                "tier": "Unranked",
                "peak_tier": "Unranked",
                "region": user_info.get("region", "Unknown"),
                "pref_server": user_info.get("pref_server", ""),
                "verified": True,
                "cooldown": cooldowns.get(user_key_str, {})
            }
    
    # Save the consolidated data
    website_data_file = "json/website_data.json"
    save_json(website_data_file, website_data)
    print(f"Generated website data with {len(website_data['players'])} players")
    
    return website_data

async def rank_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=rank, value=rank)
        for rank in TIERS if current.lower() in rank.lower()
    ]

async def close_tier_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete for close command tier option - includes Test Discontinued"""
    choices = [
        app_commands.Choice(name=rank, value=rank)
        for rank in TIERS if current.lower() in rank.lower()
    ]
    # Add Test Discontinued option
    if "test discontinued".startswith(current.lower()) or "discontinued".startswith(current.lower()):
        choices.append(app_commands.Choice(name="Test Discontinued", value="Test Discontinued"))
    return choices

async def region_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=region, value=region)
        for region in REGIONS if current.lower() in region.lower()
    ]

async def time_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    times = ["alltime", "month"]
    return [
        app_commands.Choice(name=time, value=time)
        for time in times if current.lower() in time.lower()
    ]

async def days_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    days_options = ["1 Day", "2 Days", "3 Days", "4 Days", "5 Days", "6 Days", "7 Days"]
    return [
        app_commands.Choice(name=days, value=days)
        for days in days_options if current.lower() in days.lower()
    ]

async def send_result_log(guild, testee, tester, old_rank, new_rank):
    results_channel_id = config.get("channels", {}).get("results")
    
    if not results_channel_id:
        return

    channel = guild.get_channel(results_channel_id)
    if not channel:
        return

    testee_id = str(testee.id)
    mc_data = get_user_mc_data(testee_id)
    testee_data = users.get(testee_id, {})
    
    username = mc_data["username"]
    uuid = mc_data["uuid"]
    region = testee_data.get("region", "N/A")
    
    old_rank_full = RANK_NAMES.get(old_rank, old_rank)
    new_rank_full = RANK_NAMES.get(new_rank, new_rank)

    embed = discord.Embed(title=f"{testee.name}'s Test Results", color=BLACK)
    embed.set_author(name=f"{testee.name}", icon_url=testee.display_avatar.url)
    
    embed.add_field(name="Tester:", value=tester.mention, inline=False)
    embed.add_field(name="Region:", value=region, inline=False)
    embed.add_field(name="Username:", value=username, inline=False)
    embed.add_field(name="Previous Rank:", value=old_rank_full, inline=False)
    embed.add_field(name="Rank Earned:", value=new_rank_full, inline=False)
    
    if uuid != "N/A":
        embed.set_thumbnail(url=get_skin_url(uuid))

    msg = await channel.send(content=f"{testee.mention}", embed=embed)
    for emoji in EMOJIS:
        await msg.add_reaction(emoji)

async def update_member_roles(member, new_rank):
    if "tier_roles" not in config:
        return
    
    tier_role_ids = config["tier_roles"].values()
    roles_to_remove = [member.guild.get_role(rid) for rid in tier_role_ids if rid]
    roles_to_remove = [r for r in roles_to_remove if r and r in member.roles]
    
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove)
        except:
            pass
            
    new_role_id = config["tier_roles"].get(new_rank)
    if new_role_id:
        new_role = member.guild.get_role(new_role_id)
        if new_role:
            try:
                await member.add_roles(new_role)
            except:
                pass

async def remove_waitlist_roles(member: discord.Member):
    waitlist_role_keys = ["waitlist-na", "waitlist-eu", "waitlist-as-au"]
    roles_to_remove = []
    for key in waitlist_role_keys:
        role_id = config.get("roles", {}).get(key)
        if role_id:
            role = member.guild.get_role(role_id)
            if role and role in member.roles:
                roles_to_remove.append(role)
    
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove)
        except:
            pass

    user_id = member.id
    for region in queues:
        if user_id in queues[region]:
            queues[region].remove(user_id)

# --- Configuration Commands ---

config_group = app_commands.Group(name="config", description="Configuration commands")
tester_group = app_commands.Group(name="tester", description="Tester management commands")
cooldown_manage_group = app_commands.Group(name="cooldownmanage", description="Cooldown management commands")
list_group = app_commands.Group(name="list", description="Tier list management commands")

# --- Permission Check Utility ---

def is_tester_or_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        staff_role_id = config.get("roles", {}).get("staff")
        tester_role_id = config.get("roles", {}).get("tester")
        user_role_ids = [r.id for r in interaction.user.roles]
        if (staff_role_id and staff_role_id in user_role_ids) or (tester_role_id and tester_role_id in user_role_ids):
            return True
        await interaction.response.send_message(embed=black_embed("You do not have permission to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_tester():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        tester_role_id = config.get("roles", {}).get("tester")
        user_role_ids = [r.id for r in interaction.user.roles]
        if tester_role_id and tester_role_id in user_role_ids:
            return True
        await interaction.response.send_message(embed=black_embed("You need the tester role to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        staff_role_id = config.get("roles", {}).get("staff")
        user_role_ids = [r.id for r in interaction.user.roles]
        if staff_role_id and staff_role_id in user_role_ids:
            return True
        await interaction.response.send_message(embed=black_embed("You need the staff role to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_high_staff():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        high_staff_role_id = config.get("roles", {}).get("high_staff")
        staff_role_id = config.get("roles", {}).get("staff")
        user_role_ids = [r.id for r in interaction.user.roles]
        if (high_staff_role_id and high_staff_role_id in user_role_ids) or (staff_role_id and staff_role_id in user_role_ids):
            return True
        await interaction.response.send_message(embed=black_embed("You need the high staff or staff role to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_migration_key():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        migration_key_role_id = config.get("roles", {}).get("migration_key")
        user_role_ids = [r.id for r in interaction.user.roles]
        if migration_key_role_id and migration_key_role_id in user_role_ids:
            return True
        await interaction.response.send_message(embed=black_embed("You need the Migration Key role to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_whitelisted():
    async def predicate(interaction: discord.Interaction) -> bool:
        whitelist = config.get("whitelist", [])
        if interaction.user.id in whitelist:
            return True
        await interaction.response.send_message(embed=black_embed("You are not whitelisted to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_restriction_key():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        restriction_key_role_id = config.get("roles", {}).get("restriction_key")
        user_role_ids = [r.id for r in interaction.user.roles]
        if restriction_key_role_id and restriction_key_role_id in user_role_ids:
            return True
        await interaction.response.send_message(embed=black_embed("You need the Restriction Key role to use this command."), ephemeral=True)
        return False
    return app_commands.check(predicate)

# --- Bot Setup ---

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        self.tree.add_command(config_group)
        self.tree.add_command(tester_group)
        self.tree.add_command(cooldown_manage_group)
        self.tree.add_command(list_group)
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
        
        # Load tiers from local JSON file
        global tiers
        tiers = load_tiers_from_json()
        print(f"Loaded {len(tiers)} tiers from local JSON file")
        
        # Initialize peak tiers for existing users who don't have them set
        initialize_peak_tiers()
        
        # Generate initial website data
        generate_website_data()

        # Restore active tickets from persistent storage so post-restart closes/skips still work
        for channel_id_str, ticket_data in eval_tickets.items():
            cid = int(channel_id_str)
            if cid not in active_tickets:
                active_tickets[cid] = ticket_data
        for channel_id_str, ticket_data in high_tickets.items():
            cid = int(channel_id_str)
            if cid not in active_tickets:
                active_tickets[cid] = ticket_data
        print(f"Restored {len(active_tickets)} active ticket(s) from storage.")

        channel_id = config.get("channels", {}).get("request-test")
        if channel_id:
            channel = self.get_channel(channel_id)
            if channel:
                try:
                    await channel.purge(limit=10, check=lambda m: m.author == self.user)
                except:
                    pass
                
                embed = discord.Embed(title="📝 Evaluation Testing Waitlist", color=BLACK)
                embed.description = (
                    "Upon applying, you will be added to a waitlist channel.\n"
                    "Here you will be pinged when a tester of your region is available.\n"
                    "If you are HT3 or higher, a high ticket will be created.\n\n"
                    "• **Region** should be the region of the server you wish to test on\n"
                    "• **Username** should be the name of the account you will be testing on\n\n"
                    "🛑 **Failure to provide authentic information will result in a denied test.**"
                )
                await channel.send(embed=embed, view=RequestTestView())
                print(f"Refreshed request-test embed in {channel.name}")

        for guild in self.guilds:
            for region in REGIONS:
                await update_waitlist_embed(guild, region)
        print("Initialized waitlist embeds for all regions.")
        
        # Start background task to check for tier role changes
        self.loop.create_task(tier_list_background_task())
        print("Started tier list background task.")
        
        # Start background task to expire time-based restrictions
        self.loop.create_task(restriction_expiry_background_task())
        print("Started restriction expiry background task.")
        
        # Update all tier lists on startup
        for tier in TIER_LIST_TIERS:
            await update_tierlist_message(self, tier)
        print("Refreshed all tier list embeds.")
        
        # Send hardcoded embeds to specific channels only if flag is set
        if SEND_EMBEDS_ON_STARTUP:
            await send_static_embeds(self)
            print("Sent static embeds to channels.")
        else:
            print("Skipping static embeds (use -embed flag to send them).")

async def send_static_embeds(bot):
    """Send hardcoded embeds to specific channels"""
    
    # Migrations Channel
    migrations_channel_id = 1495387249469292604
    migrations_channel = bot.get_channel(migrations_channel_id)
    if migrations_channel:
        try:
            await migrations_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        migrations_embed = discord.Embed(color=BLACK)
        migrations_embed.description = """# Migrations Rubric <:crystal:1498275567433285743>
**__Vanilla Tierlist Migrations__**
> HT3 VTL - **HT3** 
> LT2 VTL - **LT2**
> HT2 VTL - **HT2**
> LT1 VTL - **HT2**
> HT1 VTL - **HT2**
————————————————-
**__Restricted Migrations (unless cheating/hacking)__**
> HT3 VTL -** HT3**
> LT2 VTL - **LT2**
> HT2 VTL - **LT2**
> LT1 VTL - **LT2**
> HT1 VTL - **LT2**
————————————————-
**__Fake Tierlist Migrations__**
> HT3 Fake - **HT3**
> LT2 Fake - **HT3**
> HT2 Fake - **HT3**
> LT1 Fake - **HT3**
> HT1 Fake - **LT2**
————————————————-
__Migratable Tierlists__
- Vanilla Tierlist (McTiers)
- Crystal Community (PvPTiers)
- Lucnoxity Tierlist  
- Crystal Ranked
- Nova Tiers 
————————————————-
-# *[You can NOT migrate if you have already tested, & you can NOT migrate if you restricted/blacklisted on any of these tierlist for cheating/subhuman. Leaving the tierlist then rejoining to migrate will result in a restriction. **Do not try this.** These servers are bound to change frequently so please double check this channel before making a migration ticket.]*
        """
        await migrations_channel.send(embed=migrations_embed)
        print(f"Sent migrations embed to {migrations_channel.name}")
    
    # Rules Channel
    rules_channel_id = 1500507943634735126
    rules_channel = bot.get_channel(rules_channel_id)
    if rules_channel:
        try:
            await rules_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        rules_embed = discord.Embed(color=BLACK)
        rules_embed.description = """# Rules
`-` Doxing / Threats, Raping / Threats, Ratting / Threats, Swatting / Threats are prohibited & will result in a blacklist (Includes doxes that occur in other servers)
`-` Do not disrespect staff
`-` No botting or destructive behavior
`-` No bribing for boosting and others
`-` Do not do violate Discord TOS/Guidelines
`-` Do not excessively ping members
`-` No NFSW Media (Instant ban)
`-` Do not DM advertise your servers or websites/projects
`-` Excessive pings towards testers or staff will result in punishment
`-` Being excessively toxic or threatening another player will result in punishment
`-` Discriminatory hate speech/phrases are not tolerated
`-` Participating in the Discord server via alts may result in a ban
`-` Excessively NSFW discussions will result in punishment
`-` Troll/Joke Tickets will result in an instant punishment
        """
        await rules_channel.send(embed=rules_embed)
        print(f"Sent rules embed to {rules_channel.name}")
    
    # Booster Rewards Channel
    booster_rewards_channel_id = 1500556184233443519
    booster_rewards_channel = bot.get_channel(booster_rewards_channel_id)
    if booster_rewards_channel:
        try:
            await booster_rewards_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        booster_embed = await generate_booster_rewards_embed(booster_rewards_channel.guild)
        await booster_rewards_channel.send(embed=booster_embed)
        print(f"Sent booster rewards embed to {booster_rewards_channel.name}")
    
    # Ranked Rubric Channel
    ranked_rubric_channel_id = 1500508856306897007
    ranked_rubric_channel = bot.get_channel(ranked_rubric_channel_id)
    if ranked_rubric_channel:
        try:
            await ranked_rubric_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        # Ranked Rubric Channel - Part 1
        rubric_embed1 = discord.Embed(color=BLACK)
        rubric_embed1.description = """## <:ht1:1500514343698038866> Testing for HT1:
- **Phase 1:** Beat two LT2 opponents
- **Phase 2:** Beat two HT2 opponents
 - **Phase 3:** Beat two opponents in the same Tier as you
 - **Phase 4:** Beat the HT1 Player. If successful, you will steal their title.

## <:LT1:1500514329357848807> Testing for LT1:
- **Phase 1:** Beat two LT2 opponents
- **Phase 2:** Beat two opponents in the same Tier as you
- **Phase 3:** Achieve an equal or better overall score against 2 players in the Tier you are testing for. You must get a minimum of 3 rounds on each opponent.

## <:lt2:1500514313905897502> Testing for LT2/HT2:
- **Phase 1:** Beat two opponents in the same Tier as you
- **Phase 2:** Achieve an equal or better overall score against 2 players in the Tier you are testing for. You must get a minimum of 3 rounds on each opponent.

## <:ht3:1500514293383303430>  Testing for HT3:
- **Phase 1:** If you beat an evaluation tester 3-1 or better, you will be guaranteed a chance to test for HT3. With any other score, the tester decides whether you may test for HT3 or not.
- **Phase 2:** You will be paired against a HT3 opponent, who you must beat in a First to 3 in order to receive HT3.

## ❓ Missing opponents?
- Replace each missing opponent with 2 lower tiered opponents.
- If you are missing an opponent from your region, you will fight cross-regionally with ping equalization.
- "Equalized" Ping must be within 20ms and within the same tick-range. A tick-range is 50ms, meaning a 99ms player vs. a 101ms player is not considered equalized.

## ❌ Failed Tests
- Failing a Tier Test will result in a 3 day cooldown
- Failing a T2+ Tier Test to an opponent who ranks up within 10 days of your test in a condition that you might have otherwise passed will result in the test being re-opened.
  - For example, If you are testing for HT2 and lose 3-4 to a LT2 who passes HT2, your test will be re-opened counting them as a HT2 instead.
## 🗺️  T2+ Tests - Biome Striking

In order to decide what terrain the next match will be played on, players will eliminate options until one remains. This will allow for more interesting match sets by adding more diversity to the environment.
Biome striking is not mandatory if players agree upon a specific place to fight (or if they have no other option).

**There are five available biomes to choose from:**
- Snow
- Plains
- Desert
- Badlands
- Mushroom

Player 1 will strike one of these biomes, then Player 2 will strike two, leaving Player 1 to choose between the remaining two options. The player who gets the first strike will rotate after each match. **By default, the player tier testing is given the match 1 first strike**. If both players are tier testing, they will play rock paper scissors (<https://www.rpsgame.org>) to determine who strikes first in match 1.
        """
        await ranked_rubric_channel.send(embed=rubric_embed1)
        
        # Ranked Rubric Channel - Part 2
        rubric_embed2 = discord.Embed(color=BLACK)
        rubric_embed2.description = """=======================================================================
## 🏅 T2+ Retirement & Peak Tiers
Players T2 or higher will have to hold or defend their rank before their Peak Tier is applied to them.
Inactive players who choose to retire will be retired at their peak Tier on their profile. Peak Tiers are a good way for players to retain their points after earning a rank.

__T2+ Peak Tier Requirements:__
- **HT1:** 90 days without rank defenses or 2 rank defenses and 50 days holding the rank

- **LT1:** 2 rank defenses

- **T2:** 3 rank defenses

  - Rank "Holding" is considered paused while unavailable to complete assigned fights

__Retirement Rules:__

- It is advisable to carefully consider whether or not you wish to retire before contacting a staff member.
  - Contacting a staff member to retire means you will automatically be retired as soon as you meet the requirements (if not already).
  - Contacting a staff member to retire will automatically initiate the retirement process and cannot be backtracked.

## 🔻 Demotions:
**Demotions for LT1/HT1:**
- 1 loss against a lesser Tier will result in a demotion.
- 1 significant loss to a player in the same Tier will result in demotion.
- 2 losses to players in the same Tier will result in a demotion.
- Winning a fight will remove a loss from your record.

**Demotions for LT2/HT2:**
- 2 losses to a lesser Tier will result in a demotion.
- 2 significant losses to players in the same Tier will result in a demotion.
- Both forms of losing are under the same counter towards a demotion.
- Winning a fight will remove a loss from your record.

**Demotions for HT3:**
- When testing, 2 consecutive losses to a player in the same Tier will result in a demotion.
  - Beating your first opponent removes any chance of demotion.
  - If a testing player loses to their first opponent 2-4 or greater, another will be assigned. In order to not be demoted, the testing player must beat their second opponent; any other score will result in a demotion.
  - Losing 3-4 will not result in fighting a 2nd player and your test will be closed without demotion.

**Any forfeit will result in instant demotion.**

***"Significant loss" refers to a score of less than half.***
        """
        await ranked_rubric_channel.send(embed=rubric_embed2)
        
        # Ranked Rubric Channel - Part 3
        rubric_embed3 = discord.Embed(color=BLACK)
        rubric_embed3.description = """=======================================================================
## <:tester:1500514257643503757>   **__Tester Evaluation (Below HT3) Limits & Rules__**  <:tester:1500514257643503757> 
<:totem:1500514211845898363> - 14 Totems of Undying
<:arrow:1500514245580820613> - No Weakness Arrows *(Due to the absence of storage items, this rule is in place for evaluation tests)*
<:shulkerbox:1500514229000863804> - No Storage Items *(Ender Chests, Shulker Boxes, etc.)*
*(First to 3 Wins)*

=======================================================================
## <:shulkerbox:1500514229000863804> **__HT3+ Testing Limits & Rules__** <:shulkerbox:1500514229000863804>
<:totem:1500514211845898363> - 8 Totems of Undying
<:SpeedPotion:1500514198587965651> - You can freely store Potions, Crystals, Obsidian, Pearls, & Bottles o' Enchanting in Shulker Boxes.
✅  - For regulation purposes, please only have the aforementioned items in shulkers at the start of the fight.
<:enderchest:1500514185371582586> **Ender Chests are allowed and you may store anything (within the rules) in them!**
*(First to 3 Wins for HT3 Tests)*
*(First to 4 Wins for T2+ Tests)*

=======================================================================
## <:crystal:1498275567433285743> **__Universal Kit Rules & Limits__** <:respawn_anchor:1500514147597684899>    
🥛 ** - No Milk** *(This item provides little to no benefit without promoting increased stalling)*
<:enchantedgapple:1500514124474617898> ** - No Enchanted Golden Apples**  *(The rarity of this item arguably makes it too uncommon to recur in Vanilla PvP)*
🐢 ** - No Potions or arrows of the Turtle Master**  *(This item provides little to no benefit outside of the confines of the testing system)*
<:respawn_anchor:1500514147597684899> ** - 64 Respawn Anchors**  *(This limit is in place to reduce stalling issues with the testing system, with low impact)*
<:firework:1500514159329148979> ** - 24 Firework Rockets**  *(This limit is in place to reduce stalling issues with the testing system, with low impact)*
<:NetheriteIngot:1500514172595601428> ** - 4 Armor Pieces**  *(This limit is in place to reduce issues with the testing system, with low impact)*

=======================================================================
## <:grass:1500514074914455613>    ***Kit items must be obtainable in 1.21+ Vanilla Survival. This applies to all forms of testing.***
** **
# 🛡️ Testing as an Unranked or Below HT3 Player:
- Enter the wait-list and wait for a Verified Tester to become available.
  - When a Tester is active, you will be pinged to join the queue. Once you have passed through the queue, your testing ticket will be opened.
        """
        await ranked_rubric_channel.send(embed=rubric_embed3)
        print(f"Sent ranked rubric embeds to {ranked_rubric_channel.name}")
    
    # Ranked Ruleset Channel
    ranked_ruleset_channel_id = 1500508875026337973
    ranked_ruleset_channel = bot.get_channel(ranked_ruleset_channel_id)
    if ranked_ruleset_channel:
        try:
            await ranked_ruleset_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        # Ranked Ruleset Channel - Part 1
        ruleset_embed1 = discord.Embed(color=BLACK)
        ruleset_embed1.description = """## ❌ __Cheating & Restrictions__ 

If a player is caught cheating, assisting in cheating, or withholding relevant information needed to punish cheating/misconduct, they may be restricted, demoted, and banned from Discord/Testing participation. If further misconduct occurs during or after their restriction, it will become **permanent** (This includes lying and attempting to falsely appeal the restriction)

**What is classified as cheating?**
- Account Sharing in ranked fights
- Rigging Fights/Scores (includes planned throwing fights, untruthfully claiming ranked fights were not official, etc.)
- Unfair Advantages (through disallowed client mods, server plugins, commands, etc.)
- Use common sense.

## 🎮  **__Mod/Client Rules__**

✅ Examples of mods that are generally allowed:

- Marlow's Crystal Optimizer
- Hero's Anchor Optimizer
- Hero's Elytra Optimizer
- Totem Counter

Cosmetic mods that don't grant an unreasonable advantage (Capes, Crosshairs, Block Overlays, etc.)
Mods that focus on improving the performance of the Minecraft client without impacting the gameplay itself
HUD modifications that provide information about you, the player. (Armor HUD, Potion HUD, Saturation HUD, etc.)

❎  Disallowed:
Mods that modify movement, reach, or circumvent typical PvP interactions
Mods that automate or circumvent typical PvP interactions (Macros, Auto-clickers, Auto Totem, etc.)
Mods that create substantial irregularities between a Vanilla client (Moving while in inventory, block-placement changes, etc.)
Mods that increase visibility and perception of the opponent or their position (ESP, Radar, Mini-map, Freecam, etc.)
Mods that provide or track typically unavailable information about your opponent (Armor Durability, Health, Saturation, etc.)
Internal or external modifications that allow you to double-bind controls (exceptions for mice that require it for button binding)
Internal or external modifications that cause an unreasonably negative impact on your connection or latency

Any modification that creates irregularities between how your client communicates with the server vs. a standard vanilla client may result in an anti-cheat ban.
Mods are to be used at your own risk - it's advisable to do your own research beforehand! Also - use common sense.

**If you are reporting someone who violated any of these rules or limits, concrete evidence must be submitted.**
        """
        await ranked_ruleset_channel.send(embed=ruleset_embed1)
        
        # Ranked Ruleset Channel - Part 2
        ruleset_embed2 = discord.Embed(color=BLACK)
        ruleset_embed2.description = """## 🏆 **__Ranked Rules__** 🏆 
- You may load your ender chest once per round. Loading mid-round is permitted if you have not used any previously stored contents.
- Do not stall (includes taking longer than necessary to regear, exploring the world & looting structures, excessive camping, deliberately using unconventional methods to acquire EXP such as smelting/farming animals, etc.)
  - Do not craft, smelt, enchant, etc. mid-match.
- Do not leave the game unless required and be reasonably quick to rejoin if you were disconnected. Fully leaving (for 15+ mins) in the middle of a test counts as an automatic loss, UNLESS the opponent was informed prior of possible leave; one player warning beforehand counts for BOTH players, and permits them both to leave during that session. Players should be reasonably understanding of unequivocally unpreventable circumstances.
- Do not mine/collect placed Respawn Anchors.
- Do not deliberately take off your armor to hide from or attack your opponent while fully invisible.
  - Do not take off your armor to concede defeat.
- Do not deliberately attack your opponents if they are blatantly lagged out.
- Do not spam testing players with messages to disrupt the process of their test.
- Both players are liable to confirm readiness before a match.
  - "Confirming readiness" is automatically achieved by attempting to debuff or damage your opponent.
- Do not TP Trap, please wait at least 3 seconds after a teleport before attacking/debuffing the other player and only teleport if both of you will be surfaced.
- Do not RTP without mutual agreeance with your opponent
- Only 1 account is allowed on the Tier List per-player. Playing on another player's account will result in severe punishment.
- Do not fly up or place blocks within 3 seconds of teleporting to your opponent.
        """
        await ranked_ruleset_channel.send(embed=ruleset_embed2)
        print(f"Sent ranked ruleset embeds to {ranked_ruleset_channel.name}")
    
    # Verified Servers Channel
    verified_servers_channel_id = 1500509932674355282
    verified_servers_channel = bot.get_channel(verified_servers_channel_id)
    if verified_servers_channel:
        try:
            await verified_servers_channel.purge(limit=100, check=lambda m: m.author == bot.user)
        except:
            pass
        
        servers_embed = discord.Embed(color=BLACK)
        servers_embed.description = """# **__NA Testing Servers__**
<:dot_green:1500510125037977901> auroraprac.com `(East)` 
<:dot_green:1500510125037977901> crystalranked.org `(East)` 
<:dot_green:1500510125037977901> east.uspvp.org `(East)` 
<:dot_green:1500510125037977901> eternalanarchy.xyz `(East)` 
<:dot_green:1500510125037977901> miami.auroraprac.com `(East)` 
<:dot_green:1500510125037977901> miamiprac.com `(East)` 
<:dot_green:1500510125037977901> na.catpvp.xyz `(East)` 
<:dot_green:1500510125037977901> nae.vanillacompetitive.com `(East)` 
<:dot_green:1500510125037977901> stray.gg `(East)` 
<:dot_green:1500510125037977901> na.rankedtiers.net `(East)` 
<:dot_green:1500510125037977901> vanillapractice.com `(East & West)` 
<:dot_green:1500510125037977901> central.auroraprac.com `(Central)` 
<:dot_green:1500510125037977901> nac.vanillacompetitive.com `(Central)` 
<:dot_green:1500510125037977901> uspvp.org `(Central)` 
<:dot_green:1500510125037977901> west.auroraprac.com `(West)` 
<:dot_green:1500510125037977901> west.catpvp.xyz `(West)` 
<:dot_green:1500510125037977901> west.uspvp.org `(West)` 
<:dot_green:1500510125037977901> naw.vanillacompetitive.com `(West)` 
<:dot_green:1500510125037977901> br.vanillacompetitive.com `(SA)` 
<:dot_green:1500510125037977901> cherryvanilla.club `(SA)` 
<:dot_green:1500510125037977901> sapvp.com `(SA)` 

# **__EU Testing Servers__**
<:dot_green:1500510125037977901> euprac.net
<:dot_green:1500510125037977901> eupvp.net
<:dot_green:1500510125037977901> eu.catpvp.xyz
<:dot_green:1500510125037977901> eu.stray.gg
<:dot_green:1500510125037977901> eu.uspvp.org
<:dot_green:1500510125037977901> eu.vanillacompetitive.com
<:dot_green:1500510125037977901> itaprac.xyz
<:dot_green:1500510125037977901> mcprac.net
<:dot_green:1500510125037977901> pidors.apexmc.co
<:dot_green:1500510125037977901> pvphub.me
<:dot_green:1500510125037977901> vanillapractice.com
<:dot_green:1500510125037977901> vikur.net
<:dot_green:1500510125037977901> rankedtiers.net

# **__AS/AU Testing Servers__**
<:dot_green:1500510125037977901> as.catpvp.xyz `(AS)` 
<:dot_green:1500510125037977901> as.flakepvp.net `(AS)` 
<:dot_green:1500510125037977901> asiantiers.xyz `(AS)` 
<:dot_green:1500510125037977901> asiaprac.xyz `(AS)` 
<:dot_green:1500510125037977901> as.inpvp.xyz `(AS)` 
<:dot_green:1500510125037977901> as.stray.gg `(AS)` 
<:dot_green:1500510125037977901> as.strikemc.net `(AS)` 
<:dot_green:1500510125037977901> vanillapractice.com `(AS)` 
<:dot_green:1500510125037977901> bhtiers.xyz `(ME)` 
<:dot_green:1500510125037977901> indtiers.online `(IN)` 
<:dot_green:1500510125037977901> inpvp.xyz `(IN)` 
<:dot_green:1500510125037977901> au.inpvp.xyz `(AU)` 
<:dot_green:1500510125037977901> au.catpvp.xyz `(AU)` 
<:dot_green:1500510125037977901> oceanias.net `(AU)` 
<:dot_green:1500510125037977901> purevanilla.club `(AU)`
        """
        await verified_servers_channel.send(embed=servers_embed)
        print(f"Sent verified servers embed to {verified_servers_channel.name}")

bot = MyBot()

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        log_channel_id = config.get("channels", {}).get("bot-logs")
        if log_channel_id:
            log_channel = bot.get_channel(log_channel_id)
            if log_channel:
                user = interaction.user
                command_name = interaction.data.get("name")
                
                options = interaction.data.get("options", [])
                args_list = []
                for opt in options:
                    if "value" in opt:
                        args_list.append(f"{opt['name']}: {opt['value']}")
                    elif "options" in opt:
                        sub_opts = opt.get("options", [])
                        sub_args = [f"{so['name']}: {so['value']}" for so in sub_opts if "value" in so]
                        args_list.append(f"{opt['name']} ({', '.join(sub_args)})")
                
                args_str = ", ".join(args_list) if args_list else "None"
                
                embed = black_embed(title="Command Log")
                embed.add_field(name="User", value=f"{user.mention} ({user.name})", inline=True)
                embed.add_field(name="Channel", value=interaction.channel.mention if interaction.channel else "DM", inline=True)
                embed.add_field(name="Command", value=f"/{command_name}", inline=True)
                embed.add_field(name="Arguments", value=args_str, inline=False)
                embed.set_footer(text=f"User ID: {user.id}")
                embed.timestamp = datetime.datetime.now()
                
                try:
                    await log_channel.send(embed=embed)
                except:
                    pass

# --- Minecraft Utilities ---

def get_minecraft_data(username):
    try:
        resp = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}")
        if resp.status_code == 200:
            return resp.json()
        return None
    except:
        return None

def get_skin_url(uuid):
    return f"https://render.crafty.gg/3d/bust/{uuid}"

def get_user_mc_data(user_id):
    user_id = str(user_id)
    username = "Unknown"
    uuid = "N/A"
    
    if user_id in tiers:
        username = tiers[user_id].get("username", username)
        uuid = tiers[user_id].get("uuid", uuid)
    
    if user_id in users:
        if username == "Unknown" or username == "N/A":
            username = users[user_id].get("username", username)
        if uuid == "N/A" or not uuid:
            uuid = users[user_id].get("uuid", uuid)
            
    return {"username": username, "uuid": uuid}

# --- Tier List Management ---

async def add_to_tierlist(tier: str, region: str, user_id: str, username: str, verified_username: str):
    """Add a user to a tier list"""
    tier = tier.lower()
    region = region.lower()
    
    if tier not in tier_lists:
        tier_lists[tier] = {}
    if region not in tier_lists[tier]:
        tier_lists[tier][region] = []
    
    # Check if user already exists
    for user in tier_lists[tier][region]:
        if user.get("user_id") == str(user_id):
            user["username"] = username
            user["verified_username"] = verified_username
            save_json(TIER_LISTS_FILE, tier_lists)
            return False  # Updated existing
    
    # Add new user
    tier_lists[tier][region].append({
        "user_id": str(user_id),
        "username": username,
        "verified_username": verified_username
    })
    save_json(TIER_LISTS_FILE, tier_lists)
    return True  # Added new

async def remove_from_tierlist(tier: str, region: str, user_id: str):
    """Remove a user from a tier list"""
    tier = tier.lower()
    region = region.lower()
    
    if tier not in tier_lists or region not in tier_lists[tier]:
        return False
    
    user_id = str(user_id)
    tier_lists[tier][region] = [u for u in tier_lists[tier][region] if u.get("user_id") != user_id]
    
    if not tier_lists[tier][region]:
        del tier_lists[tier][region]
    if not tier_lists[tier]:
        del tier_lists[tier]
    
    save_json(TIER_LISTS_FILE, tier_lists)
    return True

def get_user_tier_role(member: discord.Member) -> str:
    """Get the tier role of a user (ht3, lt2, ht2, lt1, or None)"""
    tier_roles = config.get("tier_roles", {})
    
    for role in member.roles:
        role_id = role.id
        # Find the tier name from the role ID
        for tier_name, tier_role_id in tier_roles.items():
            if tier_role_id == role_id:
                tier_name_lower = tier_name.lower()
                # Only return valid tier list tiers
                if tier_name_lower in ["ht3", "lt2", "ht2", "lt1"]:
                    return tier_name_lower
    return None

async def check_and_update_tier_lists(guild: discord.Guild):
    """Check all users in tier lists and update based on tier role changes"""
    tier_roles = config.get("tier_roles", {})
    valid_tiers = ["ht3", "lt2", "ht2", "lt1"]
    tiers_to_update = set()
    
    # Iterate through all tier lists
    for tier in list(tier_lists.keys()):
        if tier not in valid_tiers:
            continue
            
        for region in list(tier_lists[tier].keys()):
            users_to_remove = []
            users_to_move = []
            
            for user_data in tier_lists[tier][region]:
                user_id = user_data.get("user_id")
                
                try:
                    member = await guild.fetch_member(int(user_id))
                    current_tier = get_user_tier_role(member)
                    
                    if current_tier is None:
                        # User no longer has a valid tier role (below HT3), remove from list
                        users_to_remove.append(user_id)
                    elif current_tier != tier:
                        # User's tier changed, move to appropriate list if valid (HT3, LT2, HT2, LT1)
                        # If tier is below HT3 (LT3, HT4, LT4, HT5, LT5), remove from all lists
                        if current_tier in ["ht3", "lt2", "ht2", "lt1"]:
                            users_to_move.append((user_id, current_tier, user_data))
                        else:
                            users_to_remove.append(user_id)
                except:
                    # User not found in server, remove from list
                    users_to_remove.append(user_id)
            
            # Remove users who no longer qualify
            for user_id in users_to_remove:
                await remove_from_tierlist(tier, region, user_id)
            
            # Move users to new tier lists
            for user_id, new_tier, user_data in users_to_move:
                # Remove from current list
                await remove_from_tierlist(tier, region, user_id)
                
                # Add to new list
                await add_to_tierlist(
                    new_tier, 
                    region, 
                    user_id, 
                    user_data.get("username", "Unknown"), 
                    user_data.get("verified_username", "Unknown")
                )
                # Mark both old and new tiers for embed update
                tiers_to_update.add(tier)
                tiers_to_update.add(new_tier)
            
            # Update the embed if changes were made
            if users_to_remove or users_to_move:
                tiers_to_update.add(tier)
    
    # Update all tier embeds that had changes
    for tier in tiers_to_update:
        await update_tierlist_message(guild, tier)

async def tier_list_background_task():
    """Background task to check for tier role changes every 1 minute"""
    await bot.wait_until_ready()
    
    while not bot.is_closed():
        for guild in bot.guilds:
            await check_and_update_tier_lists(guild)
        
        # Wait 1 minute before next check
        await asyncio.sleep(60)

async def restriction_expiry_background_task():
    """Background task to remove restricted role from users when their restriction expires."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now()
        expired_ids = [user_id for user_id, record in restrictions.get("active", {}).items()
                       if record.get("expires_at") and datetime.datetime.fromisoformat(record["expires_at"]) <= now]
        if expired_ids:
            restricted_role_id = config.get("roles", {}).get("restricted")
            for user_id in expired_ids:
                record = restrictions.get("active", {}).get(user_id)
                if not record:
                    continue
                guild = None
                guild_id = record.get("guild_id")
                if guild_id:
                    guild = bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(int(user_id))
                    if not member:
                        try:
                            member = await guild.fetch_member(int(user_id))
                        except:
                            member = None
                    if member and restricted_role_id:
                        restricted_role = guild.get_role(restricted_role_id)
                        if restricted_role and restricted_role in member.roles:
                            try:
                                await member.remove_roles(restricted_role)
                            except:
                                pass

                # Strike through punishment message if available
                channel_id = record.get("channel_id")
                message_id = record.get("message_id")
                if guild and channel_id and message_id:
                    try:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            msg = await channel.fetch_message(message_id)
                            original_content = msg.content.strip()
                            if original_content and not original_content.startswith("~~"):
                                strikethrough_content = f"~~{original_content}~~"
                                await msg.edit(content=strikethrough_content)
                    except:
                        pass

                if user_id in restrictions["active"]:
                    active_record = restrictions["active"].pop(user_id)
                    save_json(RESTRICTIONS_FILE, restrictions)
                    # Mark history record as inactive
                    for history_record in restrictions["history"]:
                        if history_record.get("message_id") == active_record.get("message_id") and history_record.get("active"):
                            history_record["active"] = False
                            history_record["unrestricted_at"] = datetime.datetime.now().isoformat()
                            save_json(RESTRICTIONS_FILE, restrictions)
                            break
        await asyncio.sleep(60)

def _tierlist_region_lines(tier_lower: str, region_key: str, bot: commands.Bot = None) -> str:
    """Return formatted user lines for a sub-region, or empty string if none."""
    if tier_lower in tier_lists and region_key in tier_lists[tier_lower]:
        users_in_region = tier_lists[tier_lower][region_key]
        if users_in_region:
            lines = []
            for user_data in users_in_region:
                username = user_data.get("username", "Unknown")
                verified = user_data.get("verified_username", "Unknown")
                user_id = user_data.get("user_id", "Unknown")
                
                # Try to get Discord user mention
                discord_mention = f"<@{user_id}>"
                try:
                    if user_id != "Unknown" and bot:
                        discord_user = bot.get_user(int(user_id))
                        if discord_user:
                            discord_mention = discord_user.mention
                except:
                    pass
                
                lines.append(f"> → {discord_mention} - {verified}")
            return "\n".join(lines)
    return ""

def get_ticket_category(rank: str, region: str) -> str:
    """Determine the appropriate ticket category based on what the user is testing for"""
    debug_print(f"get_ticket_category called with rank: '{rank}', region: '{region}'")

    if rank == "LT3":
        result = "high-tickets"  # Testing for HT3/LT2 - use high-tickets category
        debug_print(f"LT3 rank -> {result}")
        return result
    elif rank == "HT3":
        result = "high-test-lt2"  # Testing for LT2
        debug_print(f"HT3 rank -> {result}")
        return result
    elif rank == "LT2":
        result = "high-test-ht2"  # Testing for HT2
        debug_print(f"LT2 rank -> {result}")
        return result
    elif rank == "HT2":
        result = "high-test-lt1"  # Testing for LT1
        debug_print(f"HT2 rank -> {result}")
        return result
    elif rank == "LT1":
        result = "high-test-ht1"  # Testing for HT1
        debug_print(f"LT1 rank -> {result}")
        return result
    else:
        # For evals (Unranked, LT5, HT5, LT4, HT4, HT1) - use region-specific evaluation category
        region_lower = region.lower()
        if region_lower == "na":
            result = "na-evaluation-tests"
        elif region_lower == "eu":
            result = "eu-evaluation-tests"
        elif region_lower == "as":
            result = "as-evaluation-tests"
        elif region_lower == "au":
            result = "au-evaluation-tests"
        else:
            result = "na-evaluation-tests"  # Default fallback
        debug_print(f"Default rank '{rank}' with region '{region}' -> {result}")
        return result

async def generate_tierlist_embed(tier: str, guild: discord.Guild, bot: commands.Bot = None):
    """Generate the tier list embed for a given tier"""
    tier_lower = tier.lower()
    tier_display = tier_lower.upper()

    emoji = "<:crystal:1498275567433285743>"

    divider = "~~──────────────────────────────────────────~~"

    desc = (
        f"# {emoji} | __Omni Tiers__ — {tier_display} LIST\n"
        f"These players are voluntary members who can be assigned to high testing tickets!\n\n"
        f"{divider}\n"
    )

    # ── NORTH AMERICA ────────────────────────────────────────────────────────
    desc += "## `📍` | NORTH AMERICA\n"
    na_sub_regions = [("nae", "NA EAST"), ("nac", "NA CENTRAL"), ("naw", "NA WEST")]
    for region_key, label in na_sub_regions:
        lines = _tierlist_region_lines(tier_lower, region_key, bot)
        desc += f"**{label}**\n"
        desc += (lines if lines else "*No users in this region*") + "\n\n"

    desc += f"{divider}\n"

    # ── EUROPE ───────────────────────────────────────────────────────────────
    desc += "## `📍` | EUROPE\n"
    eu_lines = _tierlist_region_lines(tier_lower, "eu", bot)
    desc += (eu_lines if eu_lines else "*No users in this region*") + "\n\n"
    desc += f"{divider}\n"

    # ── ASIA ─────────────────────────────────────────────────────────────────
    desc += "## `📍` | ASIA\n"
    as_lines = _tierlist_region_lines(tier_lower, "as", bot)
    desc += (as_lines if as_lines else "*No users in this region*") + "\n\n"
    desc += f"{divider}\n"

    # ── AUSTRALIA ────────────────────────────────────────────────────────────
    desc += "## `📍` | AUSTRALIA\n"
    au_lines = _tierlist_region_lines(tier_lower, "au", bot)
    desc += (au_lines if au_lines else "*No users in this region*") + "\n\n"
    desc += divider

    embed = discord.Embed(description=desc, color=BLACK)

    now = datetime.datetime.now()
    timestamp = f"{now.month}/{now.day}/{now.year} {now.strftime('%I').lstrip('0') or '12'}:{now.strftime('%M')} {now.strftime('%p')}"
    embed.set_footer(text=f"Last updated by {guild.me.display_name if guild else 'bot'} • {timestamp}")
    return embed

async def generate_booster_rewards_embed(guild: discord.Guild):
    """Generate the booster rewards embed"""
    booster_emoji = "<:booster:1501695623844597871>"
    
    desc = f"""# **__Nitro Booster Perks__**{booster_emoji}
> {booster_emoji} Special Role / Color
> {booster_emoji} Image / Embed perms in <#1495377414530924757>
> {booster_emoji} Ability to add reactions to messages in <#1495377414530924757> and <#1497423230636396665>
> {booster_emoji} 3 Day Evalutation cooldown and 1 Day High cooldown"""

    embed = discord.Embed(description=desc, color=BLACK)
    return embed

async def update_tierlist_message(bot: commands.Bot, tier: str, channel_id: int = None):
    """Update or create the tier list message in a channel"""
    tier_lower = tier.lower()
    
    # Find the channel from config
    channel_key = f"tierlist-{tier_lower}"
    if channel_id:
        channel = bot.get_channel(channel_id)
    else:
        channel_id = config.get("channels", {}).get(channel_key)
        if not channel_id:
            return False
        channel = bot.get_channel(channel_id)
    
    if not channel:
        return False
    
    guild = channel.guild
    embed = await generate_tierlist_embed(tier, guild, bot)
    
    # Check if message exists in config
    message_key = f"tierlist-{tier_lower}-message"
    message_id = config.get("messages", {}).get(message_key)
    
    try:
        if message_id:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=embed)
        else:
            message = await channel.send(embed=embed)
            if "messages" not in config:
                config["messages"] = {}
            config["messages"][message_key] = message.id
            save_json(CONFIG_FILE, config)
        return True
    except:
        # If message doesn't exist, send a new one
        message = await channel.send(embed=embed)
        if "messages" not in config:
            config["messages"] = {}
        config["messages"][message_key] = message.id
        save_json(CONFIG_FILE, config)
        return True

# --- Configuration Commands ---

@config_group.command(name="channel", description="Configure channels")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    request_test="Channel for test requests",
    waitlist_na="Channel for NA waitlist",
    waitlist_eu="Channel for EU waitlist",
    waitlist_as_au="Channel for AS/AU waitlist",
    results="Channel for test results",
    high_results="Channel for high test results",
    queue_alert="Channel for queue alerts",
    migrations="Channel for migrations",
    bot_logs="Channel for bot logs",
    eval_transcript="Channel for eval transcripts",
    high_transcript="Channel for high test transcripts",
    ht3_list="Channel for HT3 tier list",
    lt2_list="Channel for LT2 tier list",
    ht2_list="Channel for HT2 tier list",
    lt1_list="Channel for LT1 tier list"
)
async def config_channel(
    interaction: discord.Interaction,
    request_test: Optional[discord.TextChannel] = None,
    waitlist_na: Optional[discord.TextChannel] = None,
    waitlist_eu: Optional[discord.TextChannel] = None,
    waitlist_as_au: Optional[discord.TextChannel] = None,
    results: Optional[discord.TextChannel] = None,
    high_results: Optional[discord.TextChannel] = None,
    queue_alert: Optional[discord.TextChannel] = None,
    migrations: Optional[discord.TextChannel] = None,
    bot_logs: Optional[discord.TextChannel] = None,
    eval_transcript: Optional[discord.TextChannel] = None,
    high_transcript: Optional[discord.TextChannel] = None,
    ht3_list: Optional[discord.TextChannel] = None,
    lt2_list: Optional[discord.TextChannel] = None,
    ht2_list: Optional[discord.TextChannel] = None,
    lt1_list: Optional[discord.TextChannel] = None
):
    if "channels" not in config: config["channels"] = {}
    
    mapping = {
        "request-test": request_test,
        "waitlist-na": waitlist_na,
        "waitlist-eu": waitlist_eu,
        "waitlist-as-au": waitlist_as_au,
        "results": results,
        "high-results": high_results,
        "queue-alert": queue_alert,
        "migrations": migrations,
        "bot-logs": bot_logs,
        "eval-transcript": eval_transcript,
        "high-transcript": high_transcript,
        "list-ht3": ht3_list,
        "list-lt2": lt2_list,
        "list-ht2": ht2_list,
        "list-lt1": lt1_list
    }
    
    for key, channel in mapping.items():
        if channel:
            config["channels"][key] = channel.id
            
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(embed=black_embed("Channels updated successfully."), ephemeral=True)

@config_group.command(name="category", description="Configure categories")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    passed_eval="Category for passed evaluations",
    high_test_lt2="Category for HT3/LT2 high tests",
    high_test_ht2="Category for LT2/HT2 high tests",
    high_test_lt1="Category for HT2/LT1 high tests",
    high_test_ht1="Category for LT1/HT1 high tests"
)
async def config_category(
    interaction: discord.Interaction,
    passed_eval: Optional[discord.CategoryChannel] = None,
    high_test_lt2: Optional[discord.CategoryChannel] = None,
    high_test_ht2: Optional[discord.CategoryChannel] = None,
    high_test_lt1: Optional[discord.CategoryChannel] = None,
    high_test_ht1: Optional[discord.CategoryChannel] = None
):
    if "categories" not in config: config["categories"] = {}
    
    if passed_eval: config["categories"]["passed-eval"] = passed_eval.id
    if high_test_lt2: config["categories"]["high-test-lt2"] = high_test_lt2.id
    if high_test_ht2: config["categories"]["high-test-ht2"] = high_test_ht2.id
    if high_test_lt1: config["categories"]["high-test-lt1"] = high_test_lt1.id
    if high_test_ht1: config["categories"]["high-test-ht1"] = high_test_ht1.id
    
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(embed=black_embed("Categories updated successfully."), ephemeral=True)

@config_group.command(name="roles", description="Configure roles")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    staff="Staff role",
    high_staff="High staff role",
    tester="Tester role",
    waitlist_na="NA waitlist role",
    waitlist_eu="EU waitlist role",
    waitlist_as_au="AS/AU waitlist role"
)
async def config_roles(
    interaction: discord.Interaction,
    staff: Optional[discord.Role] = None,
    high_staff: Optional[discord.Role] = None,
    tester: Optional[discord.Role] = None,
    waitlist_na: Optional[discord.Role] = None,
    waitlist_eu: Optional[discord.Role] = None,
    waitlist_as_au: Optional[discord.Role] = None
):
    if "roles" not in config: config["roles"] = {}
    
    mapping = {
        "staff": staff,
        "high_staff": high_staff,
        "tester": tester,
        "waitlist-na": waitlist_na,
        "waitlist-eu": waitlist_eu,
        "waitlist-as-au": waitlist_as_au
    }
    
    for key, role in mapping.items():
        if role:
            config["roles"][key] = role.id
            
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(embed=black_embed("Roles updated successfully."), ephemeral=True)

@config_group.command(name="tiers", description="Configure tier roles")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    lt5="LT5 tier role",
    ht5="HT5 tier role",
    lt4="LT4 tier role",
    ht4="HT4 tier role",
    lt3="LT3 tier role",
    ht3="HT3 tier role",
    lt2="LT2 tier role",
    ht2="HT2 tier role",
    lt1="LT1 tier role",
    ht1="HT1 tier role"
)
async def config_tiers(
    interaction: discord.Interaction,
    lt5: Optional[discord.Role] = None,
    ht5: Optional[discord.Role] = None,
    lt4: Optional[discord.Role] = None,
    ht4: Optional[discord.Role] = None,
    lt3: Optional[discord.Role] = None,
    ht3: Optional[discord.Role] = None,
    lt2: Optional[discord.Role] = None,
    ht2: Optional[discord.Role] = None,
    lt1: Optional[discord.Role] = None,
    ht1: Optional[discord.Role] = None
):
    if "tier_roles" not in config: config["tier_roles"] = {}
    
    mapping = {
        "LT5": lt5, "HT5": ht5,
        "LT4": lt4, "HT4": ht4,
        "LT3": lt3, "HT3": ht3,
        "LT2": lt2, "HT2": ht2,
        "LT1": lt1, "HT1": ht1
    }
    
    for key, role in mapping.items():
        if role:
            config["tier_roles"][key] = role.id
            
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(embed=black_embed("Tier roles updated successfully."), ephemeral=True)

# --- Modals & Views ---

class VerificationModal(discord.ui.Modal, title="Verify Account"):
    ign = discord.ui.TextInput(label="IGN", placeholder="Enter your Minecraft username", min_length=3, max_length=16)
    region = discord.ui.TextInput(label="Region (NA, EU, AS, AU)", placeholder="NA/EU/AS/AU", min_length=2, max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        region_upper = self.region.value.upper()
        if region_upper not in ["NA", "EU", "AS", "AU"]:
            await interaction.response.send_message(embed=black_embed("Invalid region. Please use NA, EU, AS, or AU."), ephemeral=True)
            return

        mc_data = get_minecraft_data(self.ign.value)
        if not mc_data:
            await interaction.response.send_message(embed=black_embed("Could not find a Minecraft account with that username."), ephemeral=True)
            return

        uuid = mc_data['id']
        username = mc_data['name']
        
        users[str(interaction.user.id)] = {
            "username": username,
            "uuid": uuid,
            "region": region_upper,
            "verified_at": str(datetime.datetime.now())
        }
        save_json(USERS_FILE, users)

        embed = discord.Embed(title="Verified!", color=BLACK)
        embed.description = "Your Minecraft account is linked."
        embed.add_field(name="Linked Username", value=username)
        embed.add_field(name="UUID", value=uuid)
        embed.set_thumbnail(url=get_skin_url(uuid))
        embed.set_footer(text=f"Omni Tiers • Today at {datetime.datetime.now().strftime('%I:%M %p')}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

class WaitlistModal(discord.ui.Modal, title="Enter Waitlist"):
    pref_server = discord.ui.TextInput(label="Preferred Server", placeholder="e.g. Applepvp, Crystalranked ect", min_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        if user_id in cooldowns:
            expiry_str = cooldowns[user_id].get("expiry")
            if expiry_str:
                expiry = datetime.datetime.fromisoformat(expiry_str)
                if datetime.datetime.now() < expiry:
                    await interaction.response.send_message(embed=black_embed(f"You are on cooldown until <t:{int(expiry.timestamp())}:F>"), ephemeral=True)
                    return

        users[user_id]["pref_server"] = self.pref_server.value
        save_json(USERS_FILE, users)

        user_rank = tiers.get(user_id, {}).get("rank", "Unranked")
        is_high_rank = user_rank in ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
        
        # Prevent HT1 users from entering waitlist
        if user_rank == "HT1":
            await interaction.response.send_message(embed=black_embed("HT1 users cannot enter the waitlist as they are at the highest rank."), ephemeral=True)
            return
        
        region = users[user_id]["region"]

        if is_high_rank:
            # Get Minecraft username for channel naming
            mc_data = get_user_mc_data(user_id)
            mc_username = mc_data.get("username", interaction.user.name)
            
            # Use the same category as the waitlist/queue channel
            waitlist_channel_key = f"waitlist-{region.lower()}"
            if region == "AS" or region == "AU":
                waitlist_channel_key = "waitlist-as-au"
            
            # Get waitlist channel and determine correct category
            waitlist_channel_id = config.get("channels", {}).get(waitlist_channel_key)
            if waitlist_channel_id:
                waitlist_channel = interaction.guild.get_channel(waitlist_channel_id)
                if waitlist_channel:
                    # Determine correct category based on user rank
                    category_key = get_ticket_category(user_rank)
                    debug_print(f"WaitlistModal - User rank: {user_rank}")
                    debug_print(f"WaitlistModal - Category key from get_ticket_category: {category_key}")
                    
                    category_id = config.get("categories", {}).get(category_key)
                    debug_print(f"WaitlistModal - Category ID from config: {category_id}")
                    
                    category = None
                    if category_id:
                        category = interaction.guild.get_channel(category_id)
                        debug_print(f"WaitlistModal - Found category: {category}")
                    
                    if not category:
                        debug_print(f"WaitlistModal - Category '{category_key}' not found, falling back to waitlist category")
                        category = waitlist_channel.category
                        debug_print(f"WaitlistModal - Using fallback category: {category}")
                    
                    debug_print(f"WaitlistModal - Final category for ticket: {category.name if category else 'None'}")
                if category:
                    overwrites = {
                        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    }
                    
                    # For high tickets, only staff can see them (not testers)
                    staff_role_id = config.get("roles", {}).get("staff")
                    staff_role = None
                    if staff_role_id:
                        staff_role = interaction.guild.get_role(staff_role_id)
                        if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                    # Determine channel name based on new naming scheme
                    if user_rank == "LT3":
                        channel_name = f"pull-{mc_username}"
                    elif user_rank == "HT3":
                        channel_name = f"lt2-{mc_username}"
                    elif user_rank == "LT2":
                        channel_name = f"ht2-{mc_username}"
                    elif user_rank == "HT2":
                        channel_name = f"lt1-{mc_username}"
                    elif user_rank == "LT1":
                        channel_name = f"ht1-{mc_username}"
                    else:
                        channel_name = f"eval-{mc_username}"

                    channel = await interaction.guild.create_text_channel(
                        name=channel_name,
                        category=category,
                        overwrites=overwrites
                    )
                    
                    ticket_info = {
                        "testee_id": interaction.user.id,
                        "tester_id": None,
                        "region": region,
                        "rank": user_rank,
                        "exempt": False,
                        "type": "high",
                        "opened_at": str(datetime.datetime.now())
                    }
                    active_tickets[channel.id] = ticket_info
                    high_tickets[str(channel.id)] = ticket_info
                    save_json(HIGH_TICKETS_FILE, high_tickets)

                    mc_data = get_user_mc_data(user_id)
                    embed = discord.Embed(title="High Ticket", color=BLACK)
                    embed.set_author(name=f"{interaction.user.name}", icon_url=interaction.user.display_avatar.url)
                    embed.add_field(name="Region:", value=region, inline=False)
                    embed.add_field(name="Username:", value=mc_data["username"], inline=False)
                    embed.add_field(name="Preferred Server:", value=self.pref_server.value, inline=False)
                    embed.add_field(name="Current Rank:", value=RANK_NAMES.get(user_rank, user_rank), inline=False)
                    
                    if mc_data["uuid"] != "N/A":
                        embed.set_thumbnail(url=get_skin_url(mc_data["uuid"]))

                    notify_message = interaction.user.mention
                    if staff_role:
                        notify_message += f" {staff_role.mention}"

                    await channel.send(f"{notify_message} High Ticket created. Staff, please assist.", embed=embed)
                    await interaction.response.send_message(embed=black_embed(f"A high-ticket has been created for you: {channel.mention}"), ephemeral=True)
                    await remove_waitlist_roles(interaction.user)
                    await update_waitlist_embed(interaction.guild, region)
                    return

        role_key = f"waitlist-{region.lower()}"
        if region == "AS" or region == "AU":
            role_key = "waitlist-as-au"
            
        role_id = config.get("roles", {}).get(role_key)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except:
                    pass
        
        await interaction.response.send_message(embed=black_embed("You have been added to the waitlist!"), ephemeral=True)

class ClaimModal(discord.ui.Modal, title="Claim Ticket"):
    def __init__(self, ticket_channel):
        super().__init__()
        self.ticket_channel = ticket_channel

    async def on_submit(self, interaction: discord.Interaction):
        staff_role_id = config.get("roles", {}).get("staff")
        tester_role_id = config.get("roles", {}).get("tester")
        user_role_ids = [r.id for r in interaction.user.roles]
        
        is_staff_or_tester = interaction.user.guild_permissions.administrator or \
                             (staff_role_id and staff_role_id in user_role_ids) or \
                             (tester_role_id and tester_role_id in user_role_ids)
        
        if not is_staff_or_tester:
            await interaction.response.send_message(embed=black_embed("You do not have permission to claim this ticket."), ephemeral=True)
            return

        ticket_id = self.ticket_channel.id
        if ticket_id not in active_tickets:
            await interaction.response.send_message(embed=black_embed("This ticket is no longer active."), ephemeral=True)
            return

        if active_tickets[ticket_id].get("tester_id"):
             await interaction.response.send_message(embed=black_embed("This ticket has already been claimed."), ephemeral=True)
             return

        if active_tickets[ticket_id]["testee_id"] == interaction.user.id:
            await interaction.response.send_message(embed=black_embed("You cannot claim your own ticket."), ephemeral=True)
            return

        active_tickets[ticket_id]["tester_id"] = interaction.user.id
        
        is_high = active_tickets[ticket_id].get("type") == "high"
        if is_high:
            high_tickets[str(ticket_id)] = active_tickets[ticket_id]
            save_json(HIGH_TICKETS_FILE, high_tickets)
        else:
            eval_tickets[str(ticket_id)] = active_tickets[ticket_id]
            save_json(EVAL_TICKETS_FILE, eval_tickets)

        message = interaction.message
        embed = message.embeds[0]
        testee = interaction.guild.get_member(active_tickets[ticket_id]["testee_id"])
        embed.title = f"{testee.name}'s Test Results" if testee else "Test Results"
        
        testee_id = active_tickets[ticket_id]["testee_id"]
        mc_data = get_user_mc_data(testee_id)
        testee_rank = tiers.get(str(testee_id), {}).get("rank", "Unranked")
        
        embed.clear_fields()
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Region:", value=active_tickets[ticket_id]["region"], inline=False)
        embed.add_field(name="Username:", value=mc_data["username"], inline=False)
        testee_data = users.get(str(testee_id), {})
        embed.add_field(name="Preferred Server:", value=testee_data.get("pref_server", "N/A"), inline=False)
        embed.add_field(name="Previous Rank:", value=RANK_NAMES.get(testee_rank, testee_rank), inline=False)

        await interaction.response.edit_message(embed=embed, view=None)
        await self.ticket_channel.send(f"Ticket claimed by {interaction.user.mention}.")

class ClaimView(discord.ui.View):
    def __init__(self, ticket_channel):
        super().__init__(timeout=None)
        self.ticket_channel = ticket_channel

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ClaimModal(self.ticket_channel))

class RequestTestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Account", style=discord.ButtonStyle.primary, custom_id="verify_account")
    async def verify_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerificationModal())

    @discord.ui.button(label="Enter Waitlist", style=discord.ButtonStyle.success, custom_id="enter_waitlist")
    async def enter_waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in users:
            await interaction.response.send_message(embed=black_embed("Please verify your account first."), ephemeral=True)
            return

        if user_id in cooldowns:
            expiry_str = cooldowns[user_id].get("expiry")
            if expiry_str:
                expiry = datetime.datetime.fromisoformat(expiry_str)
                if datetime.datetime.now() < expiry:
                    await interaction.response.send_message(embed=black_embed(f"You are on cooldown until <t:{int(expiry.timestamp())}:F>"), ephemeral=True)
                    return

        await interaction.response.send_modal(WaitlistModal())

# --- Verification & UI Commands ---

@bot.tree.command(name="uuid", description="Fetch the uuid of a premium minecraft account")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    username="Minecraft username to fetch UUID for"
)
async def uuid(interaction: discord.Interaction, username: str):
    data = get_minecraft_data(username)
    if data:
        embed = black_embed(f"UUID for `{data['name']}`: `{data['id']}`")
        embed.set_thumbnail(url=get_skin_url(data['id']))
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(embed=black_embed("Account not found."), ephemeral=True)

# --- Queue Management ---

active_testers = {}
queues = {"NA": [], "EU": [], "AS": [], "AU": []}
last_session = load_json(SESSIONS_FILE)
for region in REGIONS:
    if region not in last_session:
        last_session[region] = "Never"

async def update_waitlist_embed(guild, region, delete_and_resend=False):
    channel_key = f"waitlist-{region.lower()}"
    if region in ["AS", "AU"]: channel_key = "waitlist-as-au"
    
    channel_id = config.get("channels", {}).get(channel_key)
    if not channel_id: return
    
    channel = guild.get_channel(channel_id)
    if not channel: return

    testers = active_testers.get(region, [])
    
    embed = discord.Embed(color=BLACK)
    if not testers:
        embed.title = "No Testers Online"
        embed.description = f"No testers for your region are available at this time.\nYou will be pinged when a tester is available.\nCheck back later!\n\nLast testing session: `{last_session.get(region, 'Never')}`"
        view = None
    else:
        embed.title = "Tester(s) Available!"
        embed.description = "⏱ The queue updates every 10 seconds.\nUse `/leave` if you wish to be removed from the waitlist or queue."
        
        queue_list = queues.get(region, [])
        queue_text = "\n".join([f"{i+1}. <@{uid}>" for i, uid in enumerate(queue_list)]) if queue_list else "Empty"
        embed.add_field(name=f"Queue ({len(queue_list)}/20):", value=queue_text, inline=False)
        
        tester_text = "\n".join([f"{i+1}. <@{uid}>" for i, uid in enumerate(testers)])
        embed.add_field(name="Active Testers:", value=tester_text, inline=False)
        
        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(label="Join Queue", style=discord.ButtonStyle.success, custom_id=f"join_queue_{region}")
        
        async def join_queue_callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if str(user_id) not in users:
                await interaction.response.send_message(embed=black_embed("Please verify first."), ephemeral=True)
                return
            
            user_region = users[str(user_id)]["region"]
            if user_region != region:
                await interaction.response.send_message(embed=black_embed(f"You belong to {user_region} region, not {region}."), ephemeral=True)
                return

            if user_id in queues[region]:
                await interaction.response.send_message(embed=black_embed("You are already in the queue."), ephemeral=True)
                return
            
            if len(queues[region]) >= 20:
                await interaction.response.send_message(embed=black_embed("Queue is full."), ephemeral=True)
                return
            
            queues[region].append(user_id)
            await interaction.response.send_message(embed=black_embed("Joined the queue!"), ephemeral=True)
            
            # Send alert to queue alerts channel
            queue_alert_channel_id = config.get("channels", {}).get("queue-alert")
            if queue_alert_channel_id:
                queue_alert_channel = guild.get_channel(queue_alert_channel_id)
                if queue_alert_channel:
                    # Get all testers for this region
                    testers = active_testers.get(region, [])
                    tester_mentions = " ".join([f"<@{tester_id}>" for tester_id in testers]) if testers else ""
                    
                    # Build the alert message
                    message_parts = []
                    if tester_mentions:
                        message_parts.append(tester_mentions)
                    message_parts.append(f"{interaction.user.mention} has joined the {region} queue! (Position: {len(queues[region])})")
                    
                    alert_message = " ".join(message_parts)
                    await queue_alert_channel.send(alert_message)
            
            await update_waitlist_embed(guild, region)

        btn.callback = join_queue_callback
        view.add_item(btn)

    # Get waitlist role for this region
    waitlist_role_key = f"waitlist-{region.lower()}"
    if region in ["AS", "AU"]: 
        waitlist_role_key = "waitlist-as-au"
    
    waitlist_role_id = config.get("roles", {}).get(waitlist_role_key)
    waitlist_role = guild.get_role(waitlist_role_id) if waitlist_role_id else None
    
    # Prepare message content
    message_content = None
    if testers and waitlist_role:
        message_content = f"{waitlist_role.mention}"
    
    if delete_and_resend:
        # Delete old message and send new one
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                await message.delete()
                break
        await channel.send(content=message_content, embed=embed, view=view)
    else:
        # Edit existing message
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                await message.edit(content=message_content, embed=embed, view=view)
                return
        
        await channel.send(content=message_content, embed=embed, view=view)

# --- Queue Commands ---

@bot.tree.command(name="start", description="Put yourself active as a tester")
@is_tester()
async def start(interaction: discord.Interaction):
    tester_role_id = config.get("roles", {}).get("tester")
    if not tester_role_id or tester_role_id not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message(embed=black_embed("You are not a tester."), ephemeral=True)
        return

    user_id = str(interaction.user.id)
    if user_id not in users:
        await interaction.response.send_message(embed=black_embed("Please verify yourself first to set your region."), ephemeral=True)
        return

    region = users[user_id]["region"]
    if region not in active_testers: active_testers[region] = []
    
    if interaction.user.id not in active_testers[region]:
        active_testers[region].append(interaction.user.id)
        await interaction.response.send_message(embed=black_embed(f"You are now active for {region}!"), ephemeral=True)
        await update_waitlist_embed(interaction.guild, region, delete_and_resend=True)
    else:
        await interaction.response.send_message(embed=black_embed("You are already active."), ephemeral=True)

@bot.tree.command(name="stop", description="Put yourself inactive as a tester")
@is_tester()
async def stop(interaction: discord.Interaction):
    user_id = interaction.user.id
    removed = False
    for region in active_testers:
        if user_id in active_testers[region]:
            active_testers[region].remove(user_id)
            last_session[region] = datetime.datetime.now().strftime('%m/%d/%Y, %I:%M:%S %p')
            save_json(SESSIONS_FILE, last_session)
            await update_waitlist_embed(interaction.guild, region)
            removed = True
    
    if removed:
        await interaction.response.send_message(embed=black_embed("You are now inactive."), ephemeral=True)
    else:
        await interaction.response.send_message(embed=black_embed("You were not active."), ephemeral=True)

@bot.tree.command(name="leave", description="Leave the active queue you're in")
async def leave(interaction: discord.Interaction):
    user_id = interaction.user.id
    removed = False
    for region in queues:
        if user_id in queues[region]:
            queues[region].remove(user_id)
            await update_waitlist_embed(interaction.guild, region)
            removed = True
    
    if removed:
        await interaction.response.send_message(embed=black_embed("Left the queue."), ephemeral=True)
    else:
        await interaction.response.send_message(embed=black_embed("You were not in any queue."), ephemeral=True)

# --- Ticket Management ---

active_tickets = {}

async def create_transcript(channel):
    messages = [message async for message in channel.history(limit=None, oldest_first=True)]
    
    # Start HTML document
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcript - {channel.name}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #36393f;
            color: #dcddde;
            margin: 0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: #2f3136;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #40444b;
        }}
        .header h1 {{
            color: #ffffff;
            margin: 0;
            font-size: 2em;
        }}
        .header p {{
            color: #b9bbbe;
            margin: 5px 0 0 0;
        }}
        .message {{
            margin-bottom: 20px;
            padding: 15px;
            background-color: #40444b;
            border-radius: 6px;
            border-left: 4px solid #7289da;
        }}
        .message-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .author {{
            font-weight: bold;
            color: #ffffff;
        }}
        .author-id {{
            color: #7289da;
            font-size: 0.9em;
            margin-left: 8px;
        }}
        .timestamp {{
            color: #99aab5;
            font-size: 0.9em;
        }}
        .message-content {{
            color: #dcddde;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        .embed {{
            background-color: #4a4e58;
            border: 1px solid #5a5e68;
            border-radius: 4px;
            padding: 10px;
            margin-top: 10px;
        }}
        .embed-title {{
            font-weight: bold;
            color: #ffffff;
            margin-bottom: 5px;
        }}
        .embed-description {{
            color: #dcddde;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Transcript - {channel.name}</h1>
            <p>Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
"""
    
    # Add messages
    for msg in messages:
        timestamp = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
        author_name = msg.author.name
        author_id = msg.author.id
        content = msg.content or "*No content*"
        
        # Escape HTML special characters in content
        content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        html_content += f"""
        <div class="message">
            <div class="message-header">
                <span class="author">{author_name}<span class="author-id">({author_id})</span></span>
                <span class="timestamp">{timestamp}</span>
            </div>
            <div class="message-content">{content}</div>
"""
        
        # Add embeds if present
        if msg.embeds:
            for embed in msg.embeds:
                embed_title = embed.title or "Embed"
                embed_description = embed.description or "No description"
                embed_description = embed_description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                html_content += f"""
            <div class="embed">
                <div class="embed-title">{embed_title}</div>
                <div class="embed-description">{embed_description}</div>
            </div>
"""
        
        html_content += "        </div>\n"
    
    # Close HTML document
    html_content += """
    </div>
</body>
</html>
"""
    
    file_content = html_content.encode('utf-8')
    return discord.File(io.BytesIO(file_content), filename=f"transcript-{channel.name}.html")

@bot.tree.command(name="next", description="Open a ticket with the next person in the queue")
@is_tester()
async def next_ticket(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in users:
        await interaction.response.send_message(embed=black_embed("Please verify yourself first."), ephemeral=True)
        return

    region = users[user_id]["region"]
    if not queues[region]:
        await interaction.response.send_message(embed=black_embed(f"No one in the {region} queue."), ephemeral=True)
        return
    
    testee_id = queues[region].pop(0)
    await update_waitlist_embed(interaction.guild, region)
    testee = interaction.guild.get_member(testee_id)
    if not testee:
        await interaction.response.send_message(embed=black_embed("The next person in queue is no longer in the server."), ephemeral=True)
        return

    testee_rank = tiers.get(str(testee_id), {}).get("rank", "Unranked")
    debug_print(f"Creating ticket for user with rank: {testee_rank}")
    
    # Prevent HT1 users from getting tickets
    if testee_rank == "HT1":
        await interaction.response.send_message(embed=black_embed("HT1 users cannot get tickets."), ephemeral=True)
        return
    
    mc_data = get_user_mc_data(str(testee_id))
    mc_username = mc_data.get("username", testee.name)
    
    # Use the same category as the waitlist/queue channel
    region = users[user_id]["region"]
    waitlist_channel_key = f"waitlist-{region.lower()}"
    if region == "AS" or region == "AU":
        waitlist_channel_key = "waitlist-as-au"
    
    # Get waitlist channel and determine correct category
    waitlist_channel_id = config.get("channels", {}).get(waitlist_channel_key)
    if not waitlist_channel_id:
        await interaction.response.send_message(embed=black_embed("Waitlist channel not configured."), ephemeral=True)
        return
    
    waitlist_channel = interaction.guild.get_channel(waitlist_channel_id)
    if not waitlist_channel:
        await interaction.response.send_message(embed=black_embed("Waitlist channel not found."), ephemeral=True)
        return
    
    # Determine correct category based on user rank and region
    category_key = get_ticket_category(testee_rank, region)
    debug_print(f"User rank: {testee_rank}")
    debug_print(f"Category key from get_ticket_category: {category_key}")
    
    category_id = config.get("categories", {}).get(category_key)
    debug_print(f"Category ID from config: {category_id}")
    
    category = None
    if category_id:
        category = interaction.guild.get_channel(category_id)
        debug_print(f"Found category: {category}")
    
    if not category:
        debug_print(f"Category '{category_key}' not found, falling back to waitlist category")
        category = waitlist_channel.category
        debug_print(f"Using fallback category: {category}")
    
    debug_print(f"Final category for ticket: {category.name if category else 'None'}")
    
    # Determine ticket type based on rank
    is_high = testee_rank in ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
    
    # For high and eval tickets, set different permissions
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        testee: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    # Add staff role permissions for all ticket types
    staff_role_id = config.get("roles", {}).get("staff")
    if staff_role_id:
        staff_role = interaction.guild.get_role(staff_role_id)
        if staff_role: 
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Add tester role permissions only for eval tickets (not high tickets)
    if not is_high:
        tester_role_id = config.get("roles", {}).get("tester")
        if tester_role_id:
            tester_role = interaction.guild.get_role(tester_role_id)
            if tester_role: 
                overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Determine channel name based on new naming scheme
    if testee_rank in ["Unranked", "LT5", "HT5", "LT4", "HT4", "HT1"]:
        channel_name = f"eval-{mc_username}"
    elif testee_rank == "LT3":
        channel_name = f"pull-{mc_username}"
    elif testee_rank == "HT3":
        channel_name = f"lt2-{mc_username}"
    elif testee_rank == "LT2":
        channel_name = f"ht2-{mc_username}"
    elif testee_rank == "HT2":
        channel_name = f"lt1-{mc_username}"
    elif testee_rank == "LT1":
        channel_name = f"ht1-{mc_username}"
    else:
        channel_name = f"eval-{mc_username}"
    
    channel = await interaction.guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites
    )
    
    # Determine ticket type based on rank
    is_high = testee_rank in ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
    ticket_type = "high" if is_high else "eval"
    
    ticket_info = {
        "testee_id": testee_id,
        "tester_id": interaction.user.id,
        "region": region,
        "rank": testee_rank,
        "exempt": False,
        "type": ticket_type,
        "opened_at": str(datetime.datetime.now())
    }
    
    active_tickets[channel.id] = ticket_info
    
    if is_high:
        high_tickets[str(channel.id)] = ticket_info
        save_json(HIGH_TICKETS_FILE, high_tickets)
    else:
        eval_tickets[str(channel.id)] = ticket_info
        save_json(EVAL_TICKETS_FILE, eval_tickets)

    mc_data = get_user_mc_data(testee_id)
    testee_data = users.get(str(testee_id), {})
    pref_server = testee_data.get("pref_server", "N/A")
    
    embed = discord.Embed(title=f"User Pulled for Testing", color=BLACK)
    embed.set_author(name=f"{testee.name}", icon_url=testee.display_avatar.url)
    
    embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
    embed.add_field(name="Region:", value=region, inline=False)
    embed.add_field(name="Username:", value=mc_data["username"], inline=False)
    embed.add_field(name="Preferred Server:", value=pref_server, inline=False)
    
    if mc_data["uuid"] != "N/A":
        embed.set_thumbnail(url=get_skin_url(mc_data["uuid"]))
    
    await channel.send(f"{testee.mention} {interaction.user.mention}", embed=embed)
    await interaction.followup.send(embed=black_embed(f"Ticket created: {channel.mention}"), ephemeral=True)
    await remove_waitlist_roles(testee)
    await update_waitlist_embed(interaction.guild, region)

@bot.tree.command(name="add", description="Add a member to the current ticket")
@is_tester()
@app_commands.describe(
    member="Discord member to add to the ticket"
)
async def add_member(interaction: discord.Interaction, member: discord.Member):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
    await interaction.response.send_message(embed=black_embed(f"Added {member.mention} to the ticket."), ephemeral=True)

@bot.tree.command(name="remove", description="Removes a member from the current ticket")
@is_tester()
@app_commands.describe(
    member="Discord member to remove from the ticket"
)
async def remove_member(interaction: discord.Interaction, member: discord.Member):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(embed=black_embed(f"Removed {member.mention} from the ticket."), ephemeral=True)

@bot.tree.command(name="deadline", description="Set a deadline for the ticket")
@is_staff()
@app_commands.autocomplete(days=days_autocomplete)
@app_commands.describe(
    days="Number of days until the deadline (e.g., '1 Day', '3 Days', '7 Days')"
)
async def deadline(interaction: discord.Interaction, days: str):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    # Check if the channel is in the allowed categories from config
    allowed_category_ids = config.get("categories", {}).values()
    if not interaction.channel.category or interaction.channel.category.id not in allowed_category_ids:
        await interaction.response.send_message(embed=black_embed("This command can only be used in configured ticket categories."), ephemeral=True)
        return
    
    # Extract the number of days from the selection (e.g., "1 Day" -> 1)
    days_number = int(days.split()[0])
    
    # Calculate the deadline timestamp
    deadline_time = datetime.datetime.now() + datetime.timedelta(days=days_number)
    deadline_timestamp = int(deadline_time.timestamp())
    
    # Format the message with Discord timestamps
    message = f"# <t:{deadline_timestamp}:f> <t:{deadline_timestamp}:R> until DeadLine is reached @here"
    
    await interaction.channel.send(message)
    await interaction.response.send_message(embed=black_embed(f"Deadline set for {days}."), ephemeral=True)

@bot.tree.command(name="restrict", description="Restrict users for specific reasons")
@is_restriction_key()
@app_commands.describe(
    igns="Comma-separated list of Minecraft usernames (e.g., 'player1,player2')",
    discord_accounts="Comma-separated list of Discord IDs or mentions (e.g., '123456789, @user')",
    reason="Reason for the restriction",
    time="Duration of restriction in days (e.g., '7d' for 7 days, optional)",
    appeal="Time until appealable in days (e.g., '3d' for 3 days, optional)"
)
async def restrict(interaction: discord.Interaction, igns: str, discord_accounts: str, reason: str, time: str = None, appeal: str = None):
    await interaction.response.defer(ephemeral=True)
    
    # Parse comma-separated inputs
    ign_list = [ign.strip() for ign in igns.split(",")]
    discord_id_list = parse_discord_account_ids(discord_accounts)
    
    # Parse time (e.g., "7d" for 7 days, "30d" for 30 days)
    time_days = 0
    if time:
        if time.endswith('d'):
            time_days = int(time[:-1])
        else:
            time_days = int(time)
    
    # Parse appeal time (e.g., "7d" for 7 days, "30d" for 30 days)
    appeal_days = 0
    if appeal:
        if appeal.endswith('d'):
            appeal_days = int(appeal[:-1])
        else:
            appeal_days = int(appeal)
    
    # Calculate timestamps
    restriction_end = datetime.datetime.now() + datetime.timedelta(days=time_days) if time else None
    appeal_time = datetime.datetime.now() + datetime.timedelta(days=appeal_days) if appeal else None
    
    # Get UUIDs for each IGN
    uuid_list = []
    for ign in ign_list:
        mc_data = get_minecraft_data(ign)
        if mc_data:
            uuid_list.append(mc_data["id"])
        else:
            uuid_list.append("N/A")
    
    # Format discord mentions and resolve guild members for role assignment
    discord_mentions = []
    for discord_id in discord_id_list:
        member = interaction.guild.get_member(int(discord_id))
        if member:
            discord_mentions.append(member.mention)
        else:
            discord_mentions.append(f"<@{discord_id}>")
    discord_mentions = " / ".join(discord_mentions)
    
    # Format IGNs
    ign_formatted = " / ".join(ign_list)
    
    # Create the message as plain text (not embed) so it can be edited with strikethrough
    message = f"{discord_mentions} - {ign_formatted} - Restricted for **{reason}**\n\n"
    
    # Add each account with their UUID
    for i, ign in enumerate(ign_list):
        message += f"{ign} - `{uuid_list[i]}`\n"
    
    # Add appeal and restriction duration info if provided
    if appeal_time:
        message += f"\nAppealable in <t:{int(appeal_time.timestamp())}:R>"
    if restriction_end:
        message += f"\nRestricted for <t:{int(restriction_end.timestamp())}:R>"
    
    # Send to punishments channel
    punishments_channel_id = config.get("channels", {}).get("punishments")
    if punishments_channel_id:
        punishments_channel = interaction.guild.get_channel(punishments_channel_id)
        if punishments_channel:
            msg = await punishments_channel.send(message)
            # Store message and expiration info for each discord account
            for discord_id in discord_id_list:
                record = {
                    "message_id": msg.id,
                    "guild_id": interaction.guild.id,
                    "channel_id": punishments_channel.id,
                    "reason": reason,
                    "igns": ign_list,
                    "appeal_at": appeal_time.isoformat() if appeal_time else None,
                    "restricted_at": datetime.datetime.now().isoformat(),
                    "active": True
                }
                if restriction_end:
                    record["expires_at"] = restriction_end.isoformat()
                restrictions["active"][discord_id] = record

                history_record = record.copy()
                history_record["user_id"] = discord_id
                history_record["active"] = True
                restrictions["history"].append(history_record)
            save_json(RESTRICTIONS_FILE, restrictions)
        else:
            await interaction.followup.send(embed=black_embed("Punishments channel not found."), ephemeral=True)
            return
    else:
        await interaction.followup.send(embed=black_embed("Punishments channel not configured."), ephemeral=True)
        return
    
    # Add restricted role to all discord accounts
    restricted_role_id = config.get("roles", {}).get("restricted")
    if restricted_role_id:
        restricted_role = interaction.guild.get_role(restricted_role_id)
        if restricted_role:
            for discord_id in discord_id_list:
                try:
                    member = interaction.guild.get_member(int(discord_id))
                    if not member:
                        member = await interaction.guild.fetch_member(int(discord_id))
                    if member:
                        await member.add_roles(restricted_role)
                except Exception:
                    pass
        else:
            await interaction.followup.send(embed=black_embed("Restricted role not found."), ephemeral=True)
            return
    else:
        await interaction.followup.send(embed=black_embed("Restricted role not configured."), ephemeral=True)
        return
    
    await interaction.followup.send(embed=black_embed("Restriction message sent to punishments channel and restricted role added to all users."), ephemeral=True)

@bot.tree.command(name="cooldown", description="View your cooldown status")
async def cooldown(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in users:
        await interaction.response.send_message(embed=black_embed("You are not verified."), ephemeral=True)
        return

    embed = discord.Embed(color=BLACK)
    user_cooldown = cooldowns.get(user_id, {})
    if user_cooldown:
        expiry_str = user_cooldown.get("expiry")
        if expiry_str:
            expiry = datetime.datetime.fromisoformat(expiry_str)
            if datetime.datetime.now() < expiry:
                embed.title = "Active Cooldown"
                embed.description = f"You are on cooldown.\nExpires: <t:{int(expiry.timestamp())}:R>"
            else:
                embed.title = "No Active Cooldown"
                embed.description = "You don't have any cooldown currently.\nYou can join the waitlist or queue freely."
        else:
            embed.title = "No Active Cooldown"
            embed.description = "You don't have any cooldown currently.\nYou can join the waitlist or queue freely."
    else:
        embed.title = "No Active Cooldown"
        embed.description = "You don't have any cooldown currently.\nYou can join the waitlist or queue freely."

    user_rank = tiers.get(user_id, {}).get("rank", "Unranked")

    mc_data = get_user_mc_data(user_id)

    embed.add_field(name="Ranking", value=user_rank) 
    embed.add_field(name="UUID", value=mc_data["uuid"])
    embed.add_field(name="Last Tested", value=user_cooldown.get("last_test", "Never"))
    if mc_data["uuid"] != "N/A":
        embed.set_thumbnail(url=get_skin_url(mc_data["uuid"]))

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="unrestrict", description="Remove restriction from users")
@is_restriction_key()
@app_commands.describe(
    discord_accounts="Comma-separated list of Discord IDs or mentions to unrestrict (e.g., '123456789, @user')"
)
async def unrestrict(interaction: discord.Interaction, discord_accounts: str):
    await interaction.response.defer(ephemeral=True)
    
    # Parse comma-separated discord inputs and normalize mentions to IDs
    discord_id_list = parse_discord_account_ids(discord_accounts)
    
    # Remove restricted role from all discord accounts
    restricted_role_id = config.get("roles", {}).get("restricted")
    if not restricted_role_id:
        await interaction.followup.send(embed=black_embed("Restricted role not configured."), ephemeral=True)
        return
    
    restricted_role = interaction.guild.get_role(restricted_role_id)
    if not restricted_role:
        await interaction.followup.send(embed=black_embed("Restricted role not found."), ephemeral=True)
        return
    
    success_count = 0
    for discord_id in discord_id_list:
        try:
            member = await interaction.guild.fetch_member(int(discord_id))
            await member.remove_roles(restricted_role)
            success_count += 1
        except:
            pass
    
    # Edit original restriction messages with strikethrough
    punishments_channel_id = config.get("channels", {}).get("punishments")
    if punishments_channel_id:
        punishments_channel = interaction.guild.get_channel(punishments_channel_id)
        if punishments_channel:
            processed_message_ids = set()
            for discord_id in discord_id_list:
                active_record = restrictions["active"].get(discord_id)
                if not active_record or not active_record.get("message_id"):
                    continue

                msg_id = active_record["message_id"]
                if msg_id not in processed_message_ids:
                    try:
                        msg = await punishments_channel.fetch_message(msg_id)
                        original_content = msg.content.strip()
                        if original_content and not (original_content.startswith("~~") and original_content.endswith("~~")):
                            strikethrough_content = f"~~{original_content}~~"
                            await msg.edit(content=strikethrough_content)
                    except:
                        pass
                    processed_message_ids.add(msg_id)

                # Mark history record as inactive
                for history_record in restrictions["history"]:
                    if history_record.get("message_id") == msg_id and history_record.get("active"):
                        history_record["active"] = False
                        history_record["unrestricted_at"] = datetime.datetime.now().isoformat()
                        break

                if discord_id in restrictions["active"]:
                    del restrictions["active"][discord_id]
            save_json(RESTRICTIONS_FILE, restrictions)
    
    await interaction.followup.send(embed=black_embed(f"Removed restricted role from {success_count}/{len(discord_id_list)} users."), ephemeral=True)

@bot.tree.command(name="skip", description="Skip and delete the current ticket")
@is_tester()
async def skip(interaction: discord.Interaction):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    ticket_data = active_tickets[interaction.channel.id]
    testee_id = ticket_data["testee_id"]
    is_high = ticket_data.get("type") == "high"

    await interaction.response.send_message(embed=black_embed("Deleting ticket in 5 seconds..."), ephemeral=True)
    
    transcript_file = await create_transcript(interaction.channel)
    transcript_channel_id = config.get("channels", {}).get("high-transcript" if is_high else "eval-transcript")
    
    if transcript_channel_id:
        transcript_channel = interaction.guild.get_channel(transcript_channel_id)
        if transcript_channel:
            embed = discord.Embed(title=f"{'High' if is_high else 'Eval'} Ticket Transcript (Skipped)", color=BLACK)
            embed.add_field(name="User", value=f"<@{testee_id}>", inline=True)
            embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
            embed.timestamp = datetime.datetime.now()
            
            transcript_msg = await transcript_channel.send(embed=embed, file=transcript_file)
            
            ticket_data["transcript_url"] = transcript_msg.attachments[0].url if transcript_msg.attachments else None
            ticket_data["closed_at"] = str(datetime.datetime.now())
            ticket_data["closed_by"] = interaction.user.id
            ticket_data["status"] = "skipped"
            
            if is_high:
                high_tickets[str(interaction.channel.id)] = ticket_data
                save_json(HIGH_TICKETS_FILE, high_tickets)
            else:
                eval_tickets[str(interaction.channel.id)] = ticket_data
                save_json(EVAL_TICKETS_FILE, eval_tickets)

    del active_tickets[interaction.channel.id]
    await asyncio.sleep(5)
    await interaction.channel.delete()

@bot.tree.command(name="exempt", description="Prevent the ticket from auto-closing")
@is_tester()
async def exempt(interaction: discord.Interaction):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    active_tickets[interaction.channel.id]["exempt"] = True
    await interaction.response.send_message(embed=black_embed("Ticket is now exempt from auto-closing."), ephemeral=True)

@bot.tree.command(name="unexempt", description="Re-enable auto-closing for the ticket")
@is_tester()
async def unexempt(interaction: discord.Interaction):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    active_tickets[interaction.channel.id]["exempt"] = False
    await interaction.response.send_message(embed=black_embed("Ticket is no longer exempt from auto-closing."), ephemeral=True)

# --- Results & Evaluation ---

@bot.tree.command(name="passeval", description="Mark the ticket eval passed")
@is_tester()
async def passeval(interaction: discord.Interaction):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    await interaction.response.defer()
    
    ticket_data = active_tickets[interaction.channel.id]
    testee_id = ticket_data["testee_id"]
    testee = interaction.guild.get_member(testee_id)
    
    if testee:
        old_rank = tiers.get(str(testee_id), {}).get("rank", "Unranked")

        await interaction.channel.edit(name=f"{testee.name}-ht3")
        
        user_id = str(testee_id)
        if user_id not in tiers:
            tiers[user_id] = {
                "username": users.get(user_id, {}).get("username", testee.name),
                "uuid": users.get(user_id, {}).get("uuid", "N/A"),
                "rank": "LT3"
            }
        else:
            tiers[user_id]["username"] = users.get(user_id, {}).get("username", tiers[user_id].get("username", testee.name))
            tiers[user_id]["rank"] = "LT3"
        
        # Update peak tier
        update_peak_tier(user_id, "LT3")
        
        save_tiers_to_json(user_id, tiers[user_id])
        
        # Generate updated website data
        generate_website_data()
        
        cooldowns[user_id] = {
            "expiry": (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat(),
            "last_test": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "rank": "LT3"
        }
        save_json(COOLDOWNS_FILE, cooldowns)

        # Move channel to passed-eval category (using correct category from config)
        passed_eval_category_id = config.get("categories", {}).get("passed-eval")
        print(f"DEBUG: passed-eval category ID: {passed_eval_category_id}")
        
        # Try to find passed-eval category if config ID doesn't work
        passed_eval_category = None
        if passed_eval_category_id:
            passed_eval_category = interaction.guild.get_channel(passed_eval_category_id)
            print(f"DEBUG: Found passed-eval category by config ID: {passed_eval_category}")
        
        # Fallback: find passed-eval category by name if config fails
        if not passed_eval_category:
            for category in interaction.guild.categories:
                if "Passed Eval [HT3]" in category.name:
                    passed_eval_category = category
                    print(f"DEBUG: Found passed-eval category by name: {category.name} (ID: {category.id})")
                    break
        
        if passed_eval_category:
            print(f"DEBUG: Moving channel {interaction.channel.name} to category {passed_eval_category.name}")
            try:
                await interaction.channel.edit(category=passed_eval_category)
                print(f"DEBUG: Successfully moved channel to passed-eval category")
            except Exception as e:
                print(f"DEBUG: Error moving channel: {e}")
                await interaction.followup.send(embed=black_embed(f"Error moving channel: {e}"))
        else:
            print("DEBUG: passed-eval category not found in guild")
            await interaction.followup.send(embed=black_embed("Passed Eval category not found in server."))
        
        # Remove ticket from active_tickets
        del active_tickets[interaction.channel.id]
        print(f"DEBUG: Removed ticket {interaction.channel.id} from active_tickets")
        
        await interaction.followup.send(embed=black_embed(f"Evaluation passed. {testee.mention} has been moved to passed evaluation channel."))
    else:
        await interaction.followup.send(embed=black_embed("Testee not found in server."))

@bot.tree.command(name="close", description="Close the ticket with an optional tier")
@is_tester()
@app_commands.autocomplete(tier=close_tier_autocomplete)
@app_commands.describe(
    tier="Tier to assign if closing with a result (optional, e.g., LT1, HT1, LT2, HT2, etc.)"
)
async def close(interaction: discord.Interaction, tier: Optional[str] = None):
    if interaction.channel.id not in active_tickets:
        await interaction.response.send_message(embed=black_embed("This is not an active ticket channel."), ephemeral=True)
        return
    
    ticket_data = active_tickets[interaction.channel.id]
    testee_id = str(ticket_data["testee_id"])
    
    # Handle "Test Discontinued" as no tier
    if tier and tier.lower() == "test discontinued":
        tier = None
    
    if tier:
        # Validate tier against allowed TIERS
        validated_tier = validate_tier(tier)
        if not validated_tier:
            await interaction.response.send_message(embed=black_embed(f"Invalid tier '{tier}'. Must be one of: {', '.join(TIERS)}"), ephemeral=True)
            return
        
        tier = validated_tier
        old_rank = tiers.get(testee_id, {}).get("rank", "Unranked")
        
        await interaction.response.defer()
        
        cooldowns[testee_id] = {
            "expiry": (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat(),
            "last_test": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "tier": tier
        }
        save_json(COOLDOWNS_FILE, cooldowns)

        if testee_id not in tiers:
            tiers[testee_id] = {
                "username": users.get(testee_id, {}).get("username", "Unknown"),
                "uuid": users.get(testee_id, {}).get("uuid", "N/A"),
                "rank": tier
            }
        else:
            tiers[testee_id]["username"] = users.get(testee_id, {}).get("username", tiers[testee_id].get("username", "Unknown"))
            tiers[testee_id]["rank"] = tier
        
        # Update peak tier
        update_peak_tier(testee_id, tier)
        
        save_tiers_to_json(testee_id, tiers[testee_id])
        
        # Generate updated website data
        generate_website_data()

        tester_id = str(interaction.user.id)
        if tester_id not in stats:
            stats[tester_id] = {"alltime": 0, "month": 0}
        stats[tester_id]["alltime"] += 1
        stats[tester_id]["month"] += 1
        save_json(STATS_FILE, stats)
        
        await interaction.followup.send(embed=black_embed(f"Ticket closed with tier {tier}. Deleting in 5 seconds..."))
        
        testee = interaction.guild.get_member(int(testee_id))
        if testee:
            await update_member_roles(testee, tier)
            await send_result_log(interaction.guild, testee, interaction.user, old_rank, tier)
    else:
        await interaction.response.send_message(embed=black_embed(f"Ticket closed. Deleting in 5 seconds..."))

    transcript_file = await create_transcript(interaction.channel)
    is_high = ticket_data.get("type") == "high"
    transcript_channel_id = config.get("channels", {}).get("high-transcript" if is_high else "eval-transcript")
    
    if transcript_channel_id:
        transcript_channel = interaction.guild.get_channel(transcript_channel_id)
        if transcript_channel:
            embed = discord.Embed(title=f"{'High' if is_high else 'Eval'} Ticket Transcript", color=BLACK)
            embed.add_field(name="User", value=f"<@{testee_id}>", inline=True)
            embed.add_field(name="Tester", value=interaction.user.mention, inline=True)
            if tier:
                embed.add_field(name="Result", value=tier, inline=True)
            embed.timestamp = datetime.datetime.now()
            
            transcript_msg = await transcript_channel.send(embed=embed, file=transcript_file)
            
            ticket_data["transcript_url"] = transcript_msg.attachments[0].url if transcript_msg.attachments else None
            ticket_data["closed_at"] = str(datetime.datetime.now())
            ticket_data["closed_by"] = interaction.user.id
            
            if is_high:
                high_tickets[str(interaction.channel.id)] = ticket_data
                save_json(HIGH_TICKETS_FILE, high_tickets)
            else:
                eval_tickets[str(interaction.channel.id)] = ticket_data
                save_json(EVAL_TICKETS_FILE, eval_tickets)

    del active_tickets[interaction.channel.id]
    await asyncio.sleep(5)
    await interaction.channel.delete()

@bot.tree.command(name="forceresult", description="Force assign a test result to a member")
@is_high_staff()
@app_commands.autocomplete(tier=rank_autocomplete)
@app_commands.describe(
    member="Discord member to assign the result to",
    tier="Tier to assign (e.g., LT1, HT1, LT2, HT2, etc.)",
    reason="Reason for the force result"
)
async def forceresult(interaction: discord.Interaction, member: discord.Member, tier: str, reason: str):
    # Validate tier against allowed TIERS
    validated_tier = validate_tier(tier)
    if not validated_tier:
        await interaction.response.send_message(embed=black_embed(f"Invalid tier '{tier}'. Must be one of: {', '.join(TIERS)}"), ephemeral=True)
        return
    
    tier = validated_tier
    user_id = str(member.id)
    
    await interaction.response.defer()
    
    old_rank = tiers.get(user_id, {}).get("rank", "Unranked")
    
    cooldowns[user_id] = {
        "expiry": (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat(),
        "last_test": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "tier": tier,
        "reason": reason
    }
    save_json(COOLDOWNS_FILE, cooldowns)

    if user_id not in tiers:
        tiers[user_id] = {
            "username": users.get(user_id, {}).get("username", member.name),
            "uuid": users.get(user_id, {}).get("uuid", "N/A"),
            "rank": tier
        }
    else:
        tiers[user_id]["username"] = users.get(user_id, {}).get("username", tiers[user_id].get("username", member.name))
        tiers[user_id]["rank"] = tier
    
    # Update peak tier
    update_peak_tier(user_id, tier)
    
    save_tiers_to_json(user_id, tiers[user_id])
    
    # Generate updated website data
    generate_website_data()

    # Result logging
    await update_member_roles(member, tier)
    await send_result_log(interaction.guild, member, interaction.user, old_rank, tier)

    await interaction.followup.send(embed=black_embed(f"Force assigned result {tier} to {member.mention}. Reason: {reason}"))

# --- Cooldown & Queue Control ---

@cooldown_manage_group.command(name="set", description="Set a users cooldown to a specific number of days")
@is_high_staff()
@app_commands.describe(
    member="Discord member to set cooldown for",
    days="Duration of cooldown in days (e.g., 7 for 7 days)",
    reason="Reason for the cooldown"
)
async def setcooldown(interaction: discord.Interaction, member: discord.Member, days: int, reason: str = "No reason provided"):
    user_id = str(member.id)
    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    cooldowns[user_id] = {
        "expiry": expiry.isoformat(),
        "reason": reason,
        "last_test": cooldowns.get(user_id, {}).get("last_test", "N/A")
    }
    save_json(COOLDOWNS_FILE, cooldowns)
    await interaction.response.send_message(embed=black_embed(f"Set cooldown for {member.mention} to {days} days. Reason: {reason}"))

@cooldown_manage_group.command(name="reset", description="Reset a users cooldown")
@is_high_staff()
@app_commands.describe(
    member="Discord member to reset cooldown for",
    reason="Reason for the cooldown reset"
)
async def resetcooldown(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    user_id = str(member.id)
    if user_id in cooldowns and "expiry" in cooldowns[user_id]:
        cooldowns[user_id].pop("expiry", None)
        cooldowns[user_id]["reset_reason"] = reason
        save_json(COOLDOWNS_FILE, cooldowns)
        await interaction.response.send_message(embed=black_embed(f"Reset cooldown for {member.mention}. Reason: {reason}"))
    else:
        await interaction.response.send_message(embed=black_embed(f"{member.mention} has no active cooldown."), ephemeral=True)

@bot.tree.command(name="forcestopqueue", description="Force stop the testing queue for a specific region")
@is_high_staff()
@app_commands.autocomplete(region=region_autocomplete)
@app_commands.describe(
    region="Region to stop the queue for (e.g., na, eu, as-au)"
)
async def forcestopqueue(interaction: discord.Interaction, region: str):
    region = region.upper()
    if region in active_testers:
        active_testers[region] = []
        queues[region] = []
        last_session[region] = datetime.datetime.now().strftime('%m/%d/%Y, %I:%M:%S %p')
        save_json(SESSIONS_FILE, last_session)
        await update_waitlist_embed(interaction.guild, region)
        await interaction.response.send_message(embed=black_embed(f"Stopped queue for {region}."))
    else:
        await interaction.response.send_message(embed=black_embed("Invalid region."), ephemeral=True)

@bot.tree.command(name="forcetest", description="Force create a test ticket for a member")
@is_high_staff()
@app_commands.describe(
    member="Discord member to create the test ticket for",
    tester="Discord member who will be the tester"
)
async def forcetest(interaction: discord.Interaction, member: discord.Member, tester: discord.Member):
    user_id = str(member.id)
    if user_id not in users:
        await interaction.response.send_message(embed=black_embed(f"{member.mention} is not verified."), ephemeral=True)
        return

    # Auto-detect region from user's data
    region = users[user_id].get("region", "NA")
    region = region.upper()

    testee_rank = tiers.get(user_id, {}).get("rank", "Unranked")

    # Get Minecraft username for channel naming
    mc_data = get_user_mc_data(member.id)
    mc_username = mc_data.get("username", member.name)

    # Use the same category as the waitlist/queue channel
    waitlist_channel_key = f"waitlist-{region.lower()}"
    if region == "AS" or region == "AU":
        waitlist_channel_key = "waitlist-as-au"

    # Get waitlist channel and determine correct category
    waitlist_channel_id = config.get("channels", {}).get(waitlist_channel_key)
    if not waitlist_channel_id:
        await interaction.response.send_message(embed=black_embed("Waitlist channel not configured."), ephemeral=True)
        return

    waitlist_channel = interaction.guild.get_channel(waitlist_channel_id)
    if not waitlist_channel:
        await interaction.response.send_message(embed=black_embed("Waitlist channel not found."), ephemeral=True)
        return

    # Determine correct category based on user rank and region
    category_key = get_ticket_category(testee_rank, region)
    category_id = config.get("categories", {}).get(category_key)
    category = None

    if category_id:
        category = interaction.guild.get_channel(category_id)

    if not category:
        await interaction.response.send_message(embed=black_embed(f"Category '{category_key}' not found in server."), ephemeral=True)
        return
    
    # Determine ticket type based on rank
    is_high = testee_rank in ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
    
    # For high and eval tickets, set different permissions
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        tester: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    # Add staff role permissions for all ticket types
    staff_role_id = config.get("roles", {}).get("staff")
    if staff_role_id:
        staff_role = interaction.guild.get_role(staff_role_id)
        if staff_role: 
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Add tester role permissions only for eval tickets (not high tickets)
    if not is_high:
        tester_role_id = config.get("roles", {}).get("tester")
        if tester_role_id:
            tester_role = interaction.guild.get_role(tester_role_id)
            if tester_role: 
                overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Determine channel name based on new naming scheme
    if testee_rank in ["Unranked", "LT5", "HT5", "LT4", "HT4", "HT1"]:
        channel_name = f"eval-{mc_username}"
    elif testee_rank == "LT3":
        channel_name = f"pull-{mc_username}"
    elif testee_rank == "HT3":
        channel_name = f"lt2-{mc_username}"
    elif testee_rank == "LT2":
        channel_name = f"ht2-{mc_username}"
    elif testee_rank == "HT2":
        channel_name = f"lt1-{mc_username}"
    elif testee_rank == "LT1":
        channel_name = f"ht1-{mc_username}"
    else:
        channel_name = f"eval-{mc_username}"
    
    channel = await interaction.guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites
    )
    
    # Determine ticket type based on rank
    is_high = testee_rank in ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
    ticket_type = "high" if is_high else "eval"
    
    ticket_info = {
        "testee_id": member.id,
        "tester_id": tester.id,
        "region": region,
        "rank": testee_rank,
        "exempt": False,
        "type": ticket_type,
        "opened_at": str(datetime.datetime.now())
    }
    
    active_tickets[channel.id] = ticket_info
    
    # Store in appropriate ticket file based on ticket type
    if is_high:
        high_tickets[str(channel.id)] = ticket_info
        save_json(HIGH_TICKETS_FILE, high_tickets)
    else:
        eval_tickets[str(channel.id)] = ticket_info
        save_json(EVAL_TICKETS_FILE, eval_tickets)

    mc_data = get_user_mc_data(member.id)
    testee_data = users.get(str(member.id), {})
    pref_server = testee_data.get("pref_server", "N/A")
    testee_rank = tiers.get(str(member.id), {}).get("rank", "Unranked")
    
    embed = discord.Embed(title=f"{member.name}'s Test Results", color=BLACK)
    embed.set_author(name=f"{member.name}", icon_url=member.display_avatar.url)
    
    embed.add_field(name="Tester:", value=tester.mention, inline=False)
    embed.add_field(name="Region:", value=region, inline=False)
    embed.add_field(name="Username:", value=mc_data["username"], inline=False)
    embed.add_field(name="Preferred Server:", value=pref_server, inline=False)
    embed.add_field(name="Previous Rank:", value=RANK_NAMES.get(testee_rank, testee_rank), inline=False)
    
    if mc_data["uuid"] != "N/A":
        embed.set_thumbnail(url=get_skin_url(mc_data["uuid"]))
    
    await channel.send(f"{member.mention} {tester.mention}", embed=embed)
    await interaction.followup.send(embed=black_embed(f"Force ticket created: {channel.mention}"), ephemeral=True)
    await remove_waitlist_roles(member)
    await update_waitlist_embed(interaction.guild, region)

STATS_FILE = 'json/stats.json'
stats = load_json(STATS_FILE)

# --- Tier List Commands ---

async def tierlist_tier_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=tier, value=tier)
        for tier in TIER_LIST_TIERS if current.lower() in tier.lower()
    ]

async def tierlist_region_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    regions = list(TIER_LIST_REGIONS.keys())
    return [
        app_commands.Choice(name=f"{reg} - {TIER_LIST_REGIONS[reg]}", value=reg)
        for reg in regions if current.lower() in reg.lower()
    ]

@list_group.command(name="add", description="Add a user to a tier list (auto-detects tier from role)")
@app_commands.autocomplete(region=tierlist_region_autocomplete)
@is_tester_or_staff()
@app_commands.describe(
    user="Discord user to add to the tier list",
    region="Region for the tier list (e.g., nae, nac, naw, eu, as, au)"
)
async def listadd(
    interaction: discord.Interaction,
    user: discord.User,
    region: str
):
    """
    Add a user to a tier list (auto-detects tier from role)
    
    Parameters:
    - user: Discord user or user ID
    - region: nae, nac, naw, eu, as, or au
    """
    
    region_lower = region.lower()
    
    # Validate region
    if region_lower not in TIER_LIST_REGIONS:
        await interaction.response.send_message(
            embed=black_embed(f"Invalid region. Must be one of: {', '.join(TIER_LIST_REGIONS.keys())}"),
            ephemeral=True
        )
        return
    
    # Get user data
    user_id = user.id
    user_data = users.get(str(user_id), {})
    
    if not user_data:
        await interaction.response.send_message(
            embed=black_embed(f"{user.mention} has not been verified yet."),
            ephemeral=True
        )
        return
    
    # Auto-detect tier from user's role
    tier_roles = config.get("tier_roles", {})
    tier_lower = None
    
    # Check user's roles for tier roles
    for role in user.roles:
        role_id = role.id
        # Find the tier name from the role ID
        for tier_name, tier_role_id in tier_roles.items():
            if tier_role_id == role_id:
                tier_name_lower = tier_name.lower()
                # Map to tier list (only ht3, lt2, ht2, lt1 are valid)
                if tier_name_lower in ["ht3", "lt2", "ht2", "lt1"]:
                    tier_lower = tier_name_lower
                break
    
    if not tier_lower:
        await interaction.response.send_message(
            embed=black_embed(f"{user.mention} does not have a valid tier role (HT3, LT2, HT2, or LT1)."),
            ephemeral=True
        )
        return
    
    username = user_data.get("username", user.name)
    verified_username = user_data.get("username", user.name)
    
    # Add to tier list
    is_new = await add_to_tierlist(tier_lower, region_lower, user_id, username, verified_username)
    
    # Update embed
    bot = interaction.client
    await update_tierlist_message(bot, tier_lower)
    
    action = "Added" if is_new else "Updated"
    embed = black_embed(
        f"{action} {user.mention} to **{tier_lower.upper()}** list in **{TIER_LIST_REGIONS[region_lower]}**",
        title="Tier List Updated"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@list_group.command(name="remove", description="Remove a user from all tier lists")
@is_tester_or_staff()
@app_commands.describe(
    user="Discord mention, Discord ID, UUID, or Minecraft username (e.g., '@user, 123456789, uuid, or username)"
)
async def listremove(
    interaction: discord.Interaction,
    user: str
):
    """Remove a user from all tier lists
    
    Parameters:
    - user: Discord mention, Discord ID, UUID, or Minecraft username
    """
    
    # Resolve user from input
    user_id = None
    user_mention = user
    discord_user = None
    
    # Try to parse as Discord mention
    if user.startswith("<@") and user.endswith(">"):
        # Extract user ID from mention
        user_id = user.strip("<@!>")
        try:
            user_id = int(user_id)
            discord_user = await interaction.guild.fetch_member(user_id)
            user_id = str(user_id)
            user_mention = discord_user.mention
        except:
            await interaction.response.send_message(
                embed=black_embed(f"Could not find user from mention: {user}"),
                ephemeral=True
            )
            return
    # Try to parse as Discord ID
    elif user.isdigit():
        try:
            user_id = str(int(user))
            discord_user = await interaction.guild.fetch_member(int(user_id))
            user_mention = discord_user.mention
        except:
            await interaction.response.send_message(
                embed=black_embed(f"Could not find Discord user with ID: {user}"),
                ephemeral=True
            )
            return
    # Try to find by UUID in users.json
    else:
        # Check if it's a UUID (32 hex chars with or without dashes)
        import re
        uuid_pattern = r'^[0-9a-fA-F]{32}$|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        if re.match(uuid_pattern, user):
            # Search by UUID
            for uid, user_data in users.items():
                if user_data.get("uuid", "").lower() == user.lower():
                    user_id = uid
                    discord_user = await interaction.guild.fetch_member(int(uid))
                    user_mention = discord_user.mention
                    break
        else:
            # Search by Minecraft username
            for uid, user_data in users.items():
                if user_data.get("username", "").lower() == user.lower() or user_data.get("verified_username", "").lower() == user.lower():
                    user_id = uid
                    discord_user = await interaction.guild.fetch_member(int(uid))
                    user_mention = discord_user.mention
                    break
    
    if not user_id:
        await interaction.response.send_message(
            embed=black_embed(f"Could not find user: {user}"),
            ephemeral=True
        )
        return
    
    # Remove from all tier lists and regions
    removed_count = 0
    tiers_updated = set()
    
    for tier in list(tier_lists.keys()):
        for region in list(tier_lists[tier].keys()):
            removed = await remove_from_tierlist(tier, region, user_id)
            if removed:
                removed_count += 1
                tiers_updated.add(tier)
    
    if removed_count == 0:
        await interaction.response.send_message(
            embed=black_embed(f"{user_mention} was not found in any tier list"),
            ephemeral=True
        )
        return
    
    # Update all affected tier list embeds
    bot = interaction.client
    for tier in tiers_updated:
        await update_tierlist_message(bot, tier)
    
    embed = black_embed(
        f"Removed {user_mention} from {removed_count} tier list(s)",
        title="Tier List Updated"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Tester Management & Stats ---

@tester_group.command(name="add", description="Assign the verified tester role to a member")
@is_high_staff()
@app_commands.describe(
    member="Discord member to assign the tester role to"
)
async def addtester(interaction: discord.Interaction, member: discord.Member):
    role_id = config.get("roles", {}).get("tester")
    if not role_id:
        await interaction.response.send_message(embed=black_embed("Tester role not configured."), ephemeral=True)
        return
    
    role = interaction.guild.get_role(role_id)
    if role:
        await member.add_roles(role)
        await interaction.response.send_message(embed=black_embed(f"Added tester role to {member.mention}."))
    else:
        await interaction.response.send_message(embed=black_embed("Tester role not found in server."), ephemeral=True)

@tester_group.command(name="remove", description="Remove the verified tester role from a member")
@is_high_staff()
@app_commands.describe(
    member="Discord member to remove the tester role from"
)
async def removetester(interaction: discord.Interaction, member: discord.Member):
    role_id = config.get("roles", {}).get("tester")
    if not role_id:
        await interaction.response.send_message(embed=black_embed("Tester role not configured."), ephemeral=True)
        return
    
    role = interaction.guild.get_role(role_id)
    if role:
        await member.remove_roles(role)
        await interaction.response.send_message(embed=black_embed(f"Removed tester role from {member.mention}."))
    else:
        await interaction.response.send_message(embed=black_embed("Tester role not found in server."), ephemeral=True)

@bot.tree.command(name="configquota", description="Set the monthly test quota for verified testers")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    tests="Number of tests required per month (e.g., 10)"
)
async def configquota(interaction: discord.Interaction, tests: int):
    config["quota"] = tests
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(embed=black_embed(f"Monthly test quota set to {tests}."))

@bot.tree.command(name="stats", description="View the number of tests conducted by a tester")
@is_high_staff()
@app_commands.describe(
    member="Discord member to view stats for"
)
async def tester_stats_cmd(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)
    user_stats = stats.get(user_id, {"alltime": 0, "month": 0})
    await interaction.response.send_message(embed=black_embed(f"Stats for {member.mention}:\nAll-time: {user_stats['alltime']}\nThis month: {user_stats['month']}"))

@bot.tree.command(name="testerstats", description="View tester statistics from alltime or the current month")
@is_staff()
@app_commands.autocomplete(time=time_autocomplete)
@app_commands.describe(
    time="Time period to view stats for (e.g., 'All Time' or 'This Month')"
)
async def testerstats(interaction: discord.Interaction, time: str):
    if time.lower() not in ["alltime", "month"]:
        await interaction.response.send_message(embed=black_embed("Invalid time period. Use 'alltime' or 'month'."), ephemeral=True)
        return
    
    await interaction.response.send_message(embed=black_embed(f"Tester statistics for {time} (Detailed list implementation placeholder)."))

@bot.tree.command(name="testerlb", description="Display the testing leaderboard")
@is_staff()
async def testerlb(interaction: discord.Interaction):
    sorted_stats = sorted(stats.items(), key=lambda item: item[1].get('alltime', 0), reverse=True)
    lb_text = "\n".join([f"<@{uid}>: {s['alltime']} tests" for uid, s in sorted_stats[:10]])
    embed = discord.Embed(title="Testing Leaderboard", description=lb_text or "No stats yet.", color=BLACK)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wipe", description="Wipe all user data and tiers")
@is_whitelisted()
async def wipe(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    global users
    users.clear()
    save_json(USERS_FILE, users)
    
    global tiers
    tiers.clear()
    save_json(TIERS_FILE, tiers)
    
    global tier_lists
    tier_lists.clear()
    save_json(TIER_LISTS_FILE, tier_lists)
    
    global cooldowns
    cooldowns.clear()
    save_json(COOLDOWNS_FILE, cooldowns)
    
    global stats
    stats.clear()
    save_json(STATS_FILE, stats)
    
    bot = interaction.client
    for tier in TIER_LIST_TIERS:
        await update_tierlist_message(bot, tier)
    
    await interaction.followup.send(embed=black_embed("All user data, tiers, cooldowns, and stats have been wiped."), ephemeral=True)

# --- Migration & Profile ---

@bot.tree.command(name="migrate", description="Migrate a user's tier from another server")
@is_migration_key()
@app_commands.autocomplete(tier=rank_autocomplete, tier_from_server=rank_autocomplete)
@app_commands.describe(
    user="Discord member to migrate tier for",
    tier="Tier to assign (e.g., LT1, HT1, LT2, HT2, etc.)",
    server="Server name the tier is from",
    tier_from_server="Original tier from the other server (optional, defaults to Unranked)"
)
async def migrate(interaction: discord.Interaction, user: discord.Member, tier: str, server: str, tier_from_server: Optional[str] = "Unranked"):
    # Validate tier against allowed TIERS
    validated_tier = validate_tier(tier)
    if not validated_tier:
        await interaction.response.send_message(embed=black_embed(f"Invalid tier '{tier}'. Must be one of: {', '.join(TIERS)}"), ephemeral=True)
        return
    
    tier = validated_tier
    user_id = str(user.id)
    old_rank = tiers.get(user_id, {}).get("rank", "Unranked")
    if user_id not in users:
        await interaction.response.send_message(embed=black_embed(f"{user.mention} is not verified. They must verify their Minecraft account before being migrated."), ephemeral=True)
        return

    if user_id not in tiers:
        tiers[user_id] = {
            "username": users[user_id].get("username", user.name),
            "uuid": users[user_id].get("uuid", "N/A"),
            "rank": tier
        }
    else:
        tiers[user_id]["username"] = users[user_id].get("username", tiers[user_id].get("username", user.name))
        tiers[user_id]["rank"] = tier
    
    update_peak_tier(user_id, tier)
    
    save_tiers_to_json(user_id, tiers[user_id])
    
    generate_website_data()

    await update_member_roles(user, tier)

    verified_username = users[user_id].get("username", user.name)
    tier_full = RANK_NAMES.get(tier, tier)
    is_high_migration = TIERS.index(tier) >= TIERS.index("HT3") if tier in TIERS else False
    result_channel_key = "high-results" if is_high_migration else "results"
    result_channel_id = config.get("channels", {}).get(result_channel_key)
    if result_channel_id:
        result_channel = bot.get_channel(result_channel_id)
        if result_channel:
            await result_channel.send(f"`{verified_username}` - **{tier_full}** {server.upper()}")

    await interaction.response.send_message(embed=black_embed(f"Migrated {user.mention} from {server} ({old_rank} -> {tier})."), ephemeral=True)

@bot.tree.command(name="profile", description="View a users minecraft profile")
async def profile(interaction: discord.Interaction, user: discord.Member):
    user_id = str(user.id)
    if user_id not in users and user_id not in tiers:
        await interaction.response.send_message(embed=black_embed("User is not verified and has no ranks."), ephemeral=True)
        return
    
    mc_data = get_user_mc_data(user_id)
    user_data = users.get(user_id, {})
    user_rank = tiers.get(user_id, {}).get("rank", "Unranked")
    
    embed = discord.Embed(title=f"{mc_data['username']}'s Profile", color=BLACK)
    embed.add_field(name="UUID", value=mc_data['uuid'])
    embed.add_field(name="Region", value=user_data.get('region', 'N/A'))
    embed.add_field(name="Rank", value=RANK_NAMES.get(user_rank, user_rank))
    
    if mc_data['uuid'] != "N/A":
        embed.set_thumbnail(url=get_skin_url(mc_data['uuid']))
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Display all available commands and their requirements")
async def help_command(interaction: discord.Interaction):
    """Display comprehensive help information for all commands"""
    
    embed1 = discord.Embed(
        title="📚 Command Help (1/4)",
        description="All available commands and their requirements",
        color=BLACK
    )
    
    general_commands = """
**/uuid** - Fetch the UUID of a premium Minecraft account
• Requirements: Administrator permissions
• Usage: Get Minecraft UUID for any username

**/profile** - View a user's Minecraft profile
• Requirements: None
• Usage: Shows UUID, region, rank, and skin

**/leave** - Leave the active queue you're in
• Requirements: None
• Usage: Remove yourself from the testing queue
"""
    
    config_commands = """
**/config channel** - Configure bot channels
• Requirements: Administrator permissions
• Usage: Set up text channels for various bot functions

**/config category** - Configure ticket categories
• Requirements: Administrator permissions
• Usage: Set up categories for passed eval and high test tickets

**/config roles** - Configure bot roles
• Requirements: Administrator permissions
• Usage: Set up staff, tester, and other roles

**/config tiers** - Configure tier roles
• Requirements: Administrator permissions
• Usage: Set up Discord roles for each tier

**/configquota** - Set monthly test quota
• Requirements: Administrator permissions
• Usage: Set how many tests verified testers must complete monthly
"""
    
    embed1.add_field(name="🔧 General Commands", value=general_commands, inline=False)
    embed1.add_field(name="⚙️ Configuration (Admin Only)", value=config_commands, inline=False)
    embed1.set_footer(text="Page 1/4 - Use /help to see all pages")
    
    # Second embed - Tester and Cooldown Management
    embed2 = discord.Embed(
        title="📚 Command Help (2/4)",
        description="Tester and Cooldown Management Commands",
        color=BLACK
    )
    
    tester_commands = """
**/testerstats** - View tester statistics from alltime or the current month
• Requirements: Tester role
• Usage: See testing statistics for all testers

**/testerlb** - Display the testing leaderboard
• Requirements: Tester role
• Usage: See leaderboard of most active testers

**/start** - Put yourself active as a tester
• Requirements: Tester role
• Usage: Mark yourself as available for testing

**/stop** - Put yourself inactive as a tester
• Requirements: Tester role
• Usage: Mark yourself as unavailable for testing

**/next** - Open a ticket with the next person in the queue
• Requirements: Tester role
• Usage: Start a test with the next person in queue

**/ticket add** - Add a member to the current ticket
• Requirements: Tester role
• Usage: Add someone to the current test channel

**/ticket remove** - Removes a member from the current ticket
• Requirements: Tester role
• Usage: Remove someone from the current test channel

**/ticket close** - Close the ticket with an optional rank
• Requirements: Tester role
• Usage: End the current test and create transcript

**/skip** - Skip and delete the current ticket
• Requirements: Tester role
• Usage: Skip the current test and delete the channel

**/exempt** - Prevent the ticket from auto-closing
• Requirements: Tester role
• Usage: Make the ticket immune to auto-close

**/unexempt** - Re-enable auto-closing for the ticket
• Requirements: Tester role
• Usage: Remove auto-close exemption from ticket

**/passeval** - Mark the ticket eval passed
• Requirements: Tester role
• Usage: Mark evaluation as passed
"""
    
    cooldown_commands = """
**/cooldown set** - Set a user's cooldown to a specific number of days
• Requirements: High Staff role
• Usage: Put someone on cooldown with a reason

**/cooldown reset** - Reset a user's cooldown
• Requirements: High Staff role
• Usage: Remove someone's cooldown
"""
    
    embed2.add_field(name="👥 Tester Commands", value=tester_commands, inline=False)
    embed2.add_field(name="⏱️ Cooldown Management (High Staff Only)", value=cooldown_commands, inline=False)
    embed2.set_footer(text="Page 2/4 - Use /help to see all pages")
    
    embed3 = discord.Embed(
        title="📚 Command Help (3/4)",
        description="Staff and High Staff Commands",
        color=BLACK
    )
    
    staff_commands = """
**/migrate** - Migrate a user's rank from another server
• Requirements: Staff role
• Usage: Transfer user data between different servers

**/testerstats** - View tester statistics from alltime or the current month
• Requirements: Staff role
• Usage: See testing statistics for all testers

**/testerlb** - Display the testing leaderboard
• Requirements: Staff role
• Usage: See leaderboard of most active testers

**/ticket add** - Add a member to the current ticket
• Requirements: Staff role
• Usage: Add someone to the current test channel

**/ticket remove** - Removes a member from the current ticket
• Requirements: Staff role
• Usage: Remove someone from the current test channel

**/ticket close** - Close the ticket with an optional rank
• Requirements: Staff role
• Usage: End the current test and create transcript

**/exempt** - Prevent the ticket from auto-closing
• Requirements: Staff role
• Usage: Make the ticket immune to auto-close

**/unexempt** - Re-enable auto-closing for the ticket
• Requirements: Staff role
• Usage: Remove auto-close exemption from ticket
"""
    
    high_staff_commands = """
**/forceresult** - Force assign a test result to a member
• Requirements: High Staff role
• Usage: Manually assign a rank to someone

**/forcestopqueue** - Force stop the testing queue for a specific region
• Requirements: High Staff role
• Usage: Clear and stop a region's testing queue

**/forcetest** - Force create a test ticket for a member
• Requirements: High Staff role
• Usage: Create a test ticket for specific users

**/migrate** - Migrate a user's rank from another server
• Requirements: High Staff role
• Usage: Transfer user data between different servers

**/ticket add** - Add a member to the current ticket
• Requirements: High Staff role
• Usage: Add someone to the current test channel

**/ticket remove** - Removes a member from the current ticket
• Requirements: High Staff role
• Usage: Remove someone from the current test channel

**/ticket close** - Close the ticket with an optional rank
• Requirements: High Staff role
• Usage: End the current test and create transcript

**/testerstats** - View tester statistics from alltime or the current month
• Requirements: High Staff role
• Usage: See testing statistics for all testers

**/testerlb** - Display the testing leaderboard
• Requirements: High Staff role
• Usage: See leaderboard of most active testers

**/exempt** - Prevent the ticket from auto-closing
• Requirements: High Staff role
• Usage: Make the ticket immune to auto-close

**/unexempt** - Re-enable auto-closing for the ticket
• Requirements: High Staff role
• Usage: Remove auto-close exemption from ticket

**/tester add** - Assign the verified tester role to a member
• Requirements: High Staff role
• Usage: Give someone the verified tester role

**/tester remove** - Remove the verified tester role from a member
• Requirements: High Staff role
• Usage: Remove someone's verified tester role

**/cooldown set** - Set a user's cooldown to a specific number of days
• Requirements: High Staff role
• Usage: Put someone on cooldown with a reason

**/cooldown reset** - Reset a user's cooldown
• Requirements: High Staff role
• Usage: Remove someone's cooldown

**/stats** - View the number of tests conducted by a tester
• Requirements: High Staff role
• Usage: See test statistics for a specific member
"""
    
    embed3.add_field(name="👨‍💼 Staff Commands", value=staff_commands, inline=False)
    embed3.add_field(name="⭐ High Staff Commands", value=high_staff_commands, inline=False)
    embed3.set_footer(text="Page 3/4 - Use /help to see all pages")
    
    embed4 = discord.Embed(
        title="📚 Command Help (4/4)",
        description="Tier List and Admin Commands",
        color=BLACK
    )
    
    tierlist_commands = """
**/tierlist add** - Add a user to a tier list
• Requirements: Verified tester or staff role
• Usage: Add someone to a specific tier list region

**/tierlist remove** - Remove a user from a tier list
• Requirements: Verified tester or staff role
• Usage: Remove someone from a tier list region
"""
    
    admin_commands = """
**/config channel** - Configure bot channels
• Requirements: Administrator permissions
• Usage: Set up text channels for various bot functions

**/config category** - Configure ticket categories
• Requirements: Administrator permissions
• Usage: Set up categories for passed eval and high test tickets

**/config roles** - Configure bot roles
• Requirements: Administrator permissions
• Usage: Set up staff, high staff, tester, and other roles

**/config tiers** - Configure tier roles
• Requirements: Administrator permissions
• Usage: Set up Discord roles for each tier

**/configquota** - Set monthly test quota
• Requirements: Administrator permissions
• Usage: Set how many tests verified testers must complete monthly
"""
    
    embed4.add_field(name="📋 Tier List Management", value=tierlist_commands, inline=False)
    embed4.add_field(name="⚙️ Configuration (Admin Only)", value=admin_commands, inline=False)
    embed4.set_footer(text="Page 4/4 - Use /help to see all pages")
    
    await interaction.response.send_message(embed=embed1, ephemeral=True)
    await interaction.followup.send(embed=embed2, ephemeral=True)
    await interaction.followup.send(embed=embed3, ephemeral=True)
    await interaction.followup.send(embed=embed4, ephemeral=True)

async def shutdown_bot():
    """Clean shutdown of the bot"""
    print("Shutting down bot...")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    if message.content.startswith('!format'):
        print(f"Processing !format command from {message.author.name} in {message.channel.name}")
        await handle_format_command(message)
        return
    
    await bot.process_commands(message)

async def handle_format_command(message):
    """Handle the !format command to generate format templates"""
    
    if not (is_staff_check(message.author) or is_tester_check(message.author)):
        await message.channel.send("You don't have permission to use this command.")
        return
    
    channel_name = message.channel.name.lower()
    
    testee_info = get_testee_info_from_ticket(message.channel.id)
    
    format_text = ""
    
    if "ht3" in channel_name:
        format_text = generate_ht3_format(testee_info)
    elif "lt2" in channel_name:
        format_text = generate_lt2_format(testee_info)
    elif "ht2" in channel_name:
        format_text = generate_ht2_format(testee_info)
    elif "lt1" in channel_name:
        format_text = generate_lt1_format(testee_info)
    elif "ht1" in channel_name:
        format_text = generate_ht1_format(testee_info)
    else:
        format_text = generate_ht3_format(testee_info)
    
    await message.channel.send(format_text)

def get_testee_info_from_ticket(channel_id):
    """Extract testee information from active ticket"""
    if channel_id not in active_tickets:
        return {"discord_name": "Unknown", "ign": "Unknown", "discord_mention": "Unknown"}
    
    ticket_data = active_tickets[channel_id]
    testee_id = str(ticket_data.get("testee_id", ""))

    if testee_id in users:
        user_data = users[testee_id]
        discord_name = user_data.get("username", "Unknown")
        ign = user_data.get("username", "Unknown")
        discord_mention = f"<@{testee_id}>"
    else:
        discord_name = "Unknown"
        ign = "Unknown"
        discord_mention = "Unknown"
    
    return {"discord_name": discord_name, "ign": ign, "discord_mention": discord_mention}

def generate_ht3_format(testee_info):
    """Generate format for HT3 evaluation"""
    return f"""{testee_info['discord_mention']} - {testee_info['ign']} - **Promoted to/Failed High Tier 3**
*Passed Evaluation*
### __HT3 Fight:__
> Won/Loss 0-0 vs. ign"""

def generate_lt2_format(testee_info):
    """Generate format for LT2 evaluation"""
    return f"""{testee_info['discord_mention']} - {testee_info['ign']} - **Promoted to/Failed Low Tier 2**
### __LT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __HT3 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign"""

def generate_ht2_format(testee_info):
    """Generate format for HT2 evaluation"""
    return f"""{testee_info['discord_mention']} - {testee_info['ign']} - **Promoted to/Failed High Tier 2**
### __HT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __LT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign"""

def generate_lt1_format(testee_info):
    """Generate format for LT1 evaluation"""
    return f"""{testee_info['discord_mention']} - {testee_info['ign']} - **Promoted to/Failed Low Tier 1**
### __LT1 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __HT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __LT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign"""

def generate_ht1_format(testee_info):
    """Generate format for HT1 evaluation"""
    return f"""{testee_info['discord_mention']} - {testee_info['ign']} - **Promoted to/Failed High Tier 1**
### __HT1 Fight:__
> Won/Loss 0-0 vs. ign

### __LT1 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __HT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign

### __LT2 Fight:__
> Won/Loss 0-0 vs. ign
> Won/Loss 0-0 vs. ign"""

def is_staff_check(member):
    """Check if member has staff role"""
    staff_role_id = config.get("roles", {}).get("staff")
    return any(role.id == staff_role_id for role in member.roles)

def is_tester_check(member):
    """Check if member has tester role"""
    tester_role_id = config.get("roles", {}).get("tester")
    return any(role.id == tester_role_id for role in member.roles)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if "-embed" in sys.argv:
            SEND_EMBEDS_ON_STARTUP = True
            print("Embed sending enabled for this startup")
        else:
            print(f"Unknown arguments: {sys.argv[1:]}")
            print("Available arguments: -embed (send static embeds on startup)")
    
    try:
        bot.run('BOT_TOKEN')
    except KeyboardInterrupt:
        print("Bot interrupted by user")
    finally:
        asyncio.run(shutdown_bot())