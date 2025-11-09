#!/usr/bin/env python3
"""
Nebraska State Roleplay Discord Management Bot - Fixed & cleaned single-file version
Features preserved:
 - session voting with Vote / View Voters buttons
 - quick join link button
 - welcome message + persisted welcome channel via bot_state.json
 - sessionboost, full, ssd (shutdown), infract, help, ping, say, checkperms, setwelcome, testwelcome
 - improved logging and safer command registration
"""

import os
import logging
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

STATE_FILE = "bot_state.json"
DEFAULT_WELCOME_CHANNEL_ID = 1371624518514376916  # fallback default


# ---------------------
# Bot configuration
# ---------------------
class BotConfig:
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
    CASE_INSENSITIVE = os.getenv("CASE_INSENSITIVE", "True").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

    @classmethod
    def validate_config(cls):
        errors = []
        if not cls.TOKEN:
            errors.append("DISCORD_BOT_TOKEN is required")
        return (len(errors) == 0, errors)


# ---------------------
# Logging setup
# ---------------------
class ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "ENDC": "\033[0m",
    }

    def format(self, record):
        level = record.levelname
        color = self.COLORS.get(level, "")
        end = self.COLORS["ENDC"]
        record.levelname = f"{color}{level}{end}"
        return super().format(record)


def setup_logger(level: Optional[str] = None):
    if level is None:
        level = BotConfig.LOG_LEVEL

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level, logging.INFO))

    # remove existing handlers to avoid duplicates
    while logger.handlers:
        logger.handlers.pop()

    # File handler
    os.makedirs("logs", exist_ok=True)
    fh = logging.FileHandler(f"logs/bot_{datetime.utcnow().strftime('%Y%m%d')}.log", encoding="utf-8")
    fh.setLevel(getattr(logging, level, logging.INFO))
    fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)

    # Console handler with colors
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level, logging.INFO))
    ch.setFormatter(ColoredFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(ch)

    logger.info("Logger configured")
    logger.info(f"Log level: {level}")
    return logger


logger = setup_logger()


# ---------------------
# Simple persistent state (for welcome channel)
# ---------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
            return {}
    return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")


state = load_state()
WELCOME_CHANNEL_ID = state.get("welcome_channel_id", DEFAULT_WELCOME_CHANNEL_ID)


# ---------------------
# Views
# ---------------------
class SessionVoteView(discord.ui.View):
    def __init__(self, threshold: int = 8, starter: Optional[discord.Member] = None):
        super().__init__(timeout=None)
        self.voters: set[int] = set()
        self.vote_threshold = threshold
        self.starter = starter  # 👈 store who ran !session
        self.vote_button.label = f"Vote (0)"

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.green, custom_id="nsrp_vote")
    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        # Toggle vote
        if user_id in self.voters:
            self.voters.remove(user_id)
            vote_count = len(self.voters)
            button.label = f"Vote ({vote_count})"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"Vote removed! ({vote_count}/{self.vote_threshold})", ephemeral=True)
            return

        self.voters.add(user_id)
        vote_count = len(self.voters)
        button.label = f"Vote ({vote_count})"

        # Update message
        await interaction.response.edit_message(view=self)

        remaining = self.vote_threshold - vote_count
        if remaining <= 0:
            # session start flow
            # Delete the original message safely
            try:
                if interaction.message:
                    await interaction.message.delete()
            except Exception:
                # fallback: try to defer and delete original response
                try:
                    await interaction.response.defer()
                    await interaction.delete_original_response()
                except Exception:
                    logger.exception("Failed to delete original vote message")

            # send session started embeds + quick join
            current_time = datetime.now(timezone.utc)
            timestamp = int(current_time.timestamp())
            starter_mention = self.starter.mention if self.starter else interaction.user.mention
            embeds = [
                discord.Embed().set_image(
                    url="https://media.discordapp.net/attachments/1371624569076449330/1379942614819672094/nsrp_start.png"
                ),
                discord.Embed(
                    title="Session Start Up!",
                    description=(
                        f"**Greetings,**\n"
                        "Our management team has decided to host a Session Start Up. "
                        "All the people who voted will be asked to join or face moderation!\n\n"
                        f"**Session Started by**\n{starter_mention}\n\n"
                        f"**Time**\n<t:{timestamp}:F>"
                    ),
                )
                .set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png")
                .add_field(name="Code", value="Nsrp", inline=True)
                .add_field(name="Owner", value="TheRealBballGamer40", inline=True)
                .add_field(name="Name", value="Nebraska State Roleplay I Strict I Professional", inline=True),
            ]

            view = QuickJoinView()
            # Mention the role (existing role id from your original code)
            mention_content = "@here <@&1371624203085676646>"
            session_msg = await interaction.channel.send(content=mention_content, embeds=embeds, view=view)

            voter_mentions = " ".join(f"<@{uid}>" for uid in self.voters)
            await session_msg.reply(f"The following voters must join or will be moderated!\n\n{voter_mentions}")
            # reset voters after start to avoid re-triggering with stale votes
            self.voters.clear()
            button.label = f"Vote (0)"
        else:
            await interaction.followup.send(f"Vote counted! **{remaining}** more votes needed to start the session.", ephemeral=True)

    @discord.ui.button(label="View Voters", style=discord.ButtonStyle.blurple, custom_id="nsrp_view_voters")
    async def view_voters_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.voters:
            await interaction.response.send_message("No one has voted yet!", ephemeral=True)
            return
        voter_list = " ".join(f"<@{uid}>" for uid in self.voters)
        await interaction.response.send_message(f"**Current Voters ({len(self.voters)}/{self.vote_threshold}):**\n{voter_list}", ephemeral=True)


class QuickJoinView(discord.ui.View):
    def __init__(self, url: str = "https://policeroleplay.community/join/Nsrp"):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Quick Join", style=discord.ButtonStyle.link, url=url))


class WelcomeView(discord.ui.View):
    def __init__(self, member_count: int):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=str(member_count), style=discord.ButtonStyle.secondary, disabled=True))
        self.add_item(discord.ui.Button(label="Dashboard", style=discord.ButtonStyle.link, url="https://discord.com/channels/1349505197210206350/1371624475610710106"))

# ---------------------
# Cog: Basic commands and utilities
# ---------------------
class BasicCommands(commands.Cog, name="BasicCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("BasicCommands")

    # -----------------
    # Session commands
    # -----------------
    @commands.command(name="session")
    async def session(self, ctx: commands.Context):
        required_role_id = 1371624144034332804
        if not any(r.id == required_role_id for r in ctx.author.roles):
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        timestamp = int(datetime.now(timezone.utc).timestamp())
        embeds = [
            discord.Embed().set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379942614819672094/nsrp_start.png"),
            discord.Embed(
                title="Session Start Up!",
                description=(f"**Greetings**, Our management team has decided to host a session vote. "
                             f"we must reach 8+ votes to initiate a session!\n\n**Started by**\n{ctx.author.mention}\n\n**Time**\n<t:{timestamp}:F>")
            ).set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png")
        ]

        view = SessionVoteView(threshold=8, starter=ctx.author)
        await ctx.send(content="@here <@&1371624203085676646>", embeds=embeds, view=view)

    @commands.command(name="sessionboost", aliases=["boost"])
    async def sessionboost(self, ctx: commands.Context):
        required_role_id = 1371624144034332804
        if not any(r.id == required_role_id for r in ctx.author.roles):
            return
        try:
            await ctx.message.delete()
        except Exception:
            pass

        embeds = [
            discord.Embed().set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379959681019023410/nsrp_low.png"),
            discord.Embed(description="Our management team has decided to host a Server Boost. Because we are either low players or not much roleplay is going on!\n").set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png"),
        ]
        await ctx.send(content="@here <@&1371624203085676646>", embeds=embeds)

    @commands.command(name="full")
    async def full(self, ctx: commands.Context):
        required_role_id = 1371624144034332804
        if not any(r.id == required_role_id for r in ctx.author.roles):
            return
        try:
            await ctx.message.delete()
        except Exception:
            pass

        timestamp = int(datetime.now(timezone.utc).timestamp())
        embeds = [
            discord.Embed().set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379961617336500314/nsrp_full.png"),
            discord.Embed(description=f"The server has been full since <t:{timestamp}:R> ; keep attempting to join!").set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png"),
        ]
        await ctx.send(embeds=embeds)

    @commands.command(name="ssd")
    async def ssd(self, ctx: commands.Context):
        required_role_id = 1371624144034332804
        if not any(r.id == required_role_id for r in ctx.author.roles):
            return
        try:
            await ctx.message.delete()
        except Exception:
            pass

        timestamp = int(datetime.now(timezone.utc).timestamp())
        embeds = [
            discord.Embed().set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1380314637198823464/image.png"),
            discord.Embed(
                title="Session Shut-Down",
                description=(f"Unfortunately, our staff team is unable to moderate the Server anymore, or there is a lack of players, you're not permitted to join during this period. "
                             f"To be notified of our future sessions please keep an eye out for a Session in <#1371624511153242152>\n\n**Server Shut Down**\n<t:{timestamp}:F>\n\n**Shutdown initiated by**\n{ctx.author.mention}"),
                color=discord.Color.dark_grey()
            ).set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png"),
        ]
        await ctx.send(embeds=embeds)

    # -----------------
    # Infraction system
    # -----------------
    @commands.command(name="infract")
    async def infract(self, ctx: commands.Context, user: discord.Member = None, appealable: str = None, *, reason_and_type: str = None):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        valid_types = ["warning", "strike", "demotion", "suspension", "termination"]

        if not user or not appealable or not reason_and_type:
            error_embed = discord.Embed(title="❌ Invalid Command Usage",
                                        description="**Usage:** `!infract [USER] [APPEALABLE] [REASON] [TYPE] [DURATION]`\n\n**Valid Types:** Warning, Strike, Demotion, Suspension, Termination\n**Examples:**\n`!infract @user Yes Failing to follow traffic laws Warning`\n`!infract @user No Excessive violations Suspension 7d`",
                                        color=discord.Color.red())
            await ctx.send(embed=error_embed, delete_after=15)
            return

        if appealable.lower() not in ["yes", "no"]:
            error_embed = discord.Embed(title="❌ Invalid Appealable Value", description="**Appealable must be:** `Yes` or `No`\n\n**Example:** `!infract @user Yes Reason Warning`", color=discord.Color.red())
            await ctx.send(embed=error_embed, delete_after=10)
            return

        parts = reason_and_type.split()
        if len(parts) < 2:
            error_embed = discord.Embed(title="❌ Missing Infraction Type",
                                        description="**Valid Types:** Warning, Strike, Demotion, Suspension, Termination\n\n**Example:** `!infract @user Yes Reason Warning`",
                                        color=discord.Color.red())
            await ctx.send(embed=error_embed, delete_after=10)
            return

        # Parse type and duration if provided
        infraction_type = parts[-1].lower()
        duration = None
        reason = None

        if infraction_type not in valid_types:
            # Maybe suspension with duration: ... Suspension 7d
            if len(parts) >= 3 and parts[-2].lower() in valid_types:
                infraction_type = parts[-2].lower()
                duration = parts[-1]
                reason = " ".join(parts[:-2])
            else:
                error_embed = discord.Embed(title="❌ Invalid Infraction Type", description=f"**Valid Types:** Warning, Strike, Demotion, Suspension, Termination\n**You entered:** {parts[-1]}", color=discord.Color.red())
                await ctx.send(embed=error_embed, delete_after=10)
                return
        else:
            if infraction_type == "suspension" and len(parts) >= 3:
                duration = parts[-1]
                reason = " ".join(parts[:-2])
            elif infraction_type == "suspension":
                error_embed = discord.Embed(title="❌ Suspension Requires Duration", description="**Example:** `!infract @user No Excessive violations Suspension 7d`\n**Duration formats:** 1h, 3d, 1w, 30d", color=discord.Color.red())
                await ctx.send(embed=error_embed, delete_after=10)
                return
            else:
                reason = " ".join(parts[:-1])

        type_config = {
            "warning": {"color": discord.Color.gold(), "emoji": "⚠️"},
            "strike": {"color": discord.Color.orange(), "emoji": "🔶"},
            "demotion": {"color": discord.Color.red(), "emoji": "⬇️"},
            "suspension": {"color": discord.Color.blue(), "emoji": "⏸️"},
            "termination": {"color": discord.Color.dark_red(), "emoji": "❌"},
        }

        config = type_config.get(infraction_type, {"color": discord.Color.dark_grey(), "emoji": ""})

        embed = discord.Embed(title=f"Staff Infraction | {infraction_type.capitalize()}",
                              description="The Nebraska State Roleplay HR team have decided to infract you for the following reason(s)",
                              color=config["color"])
        embed.add_field(name="Appealable:", value=appealable.capitalize(), inline=False)
        embed.add_field(name="Reason:", value=reason or "No reason provided", inline=False)
        if duration:
            embed.add_field(name="Duration:", value=duration, inline=False)
        embed.add_field(name="Issued By:", value=ctx.author.mention, inline=False)
        embed.set_image(url="https://media.discordapp.net/attachments/1371624569076449330/1379944415539367956/nsrpbottom.png")
        embed.set_footer(text=f"{datetime.now(timezone.utc).strftime('%m/%d/%Y %I:%M %p UTC')}")

        await ctx.send(content=user.mention, embed=embed)

    # -----------------
    # Utility commands
    # -----------------
    @commands.command(name="commands", aliases=["help"])
    async def help_cmd(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except Exception:
            pass
        embed = discord.Embed(title="🤖 Bot Commands", color=discord.Color.dark_grey())
        embed.add_field(name="Commands",
                        value=("**!session**\n"
                               "**!sessionboost**\n"
                               "**!full**\n"
                               "**!ssd**\n"
                               "**!infract [user] [appealable] [reason] [type]**\n"
                               "**!ping**\n"
                               "**!say [message]**\n"
                               "**!testwelcome**\n"
                               "**!help**"),
                        inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        start = datetime.now(timezone.utc)
        message = await ctx.send("Pinging...")
        end = datetime.now(timezone.utc)
        api_latency = (end - start).total_seconds() * 1000

        ping_embed = discord.Embed(title="🏓 Pong!", color=discord.Color(0x2f3136), timestamp=datetime.now(timezone.utc))
        websocket_ms = round(self.bot.latency * 1000)
        ping_embed.add_field(name="Latency", value=f"**WebSocket Latency** `{websocket_ms}ms`\n**API Latency** `{round(api_latency)}ms`", inline=False)
        await message.edit(content=None, embed=ping_embed)

    @commands.command(name="say")
    async def say(self, ctx: commands.Context, *, message: str = None):
        try:
            await ctx.message.delete()
        except Exception:
            pass
        if not message:
            error_embed = discord.Embed(title="❌ Error", description="Please provide a message for me to say.\n\n**Usage:** `!say <message>`", color=discord.Color.red())
            await ctx.send(embed=error_embed, delete_after=10)
            return
        await ctx.send(message)

    @commands.command(name="checkperms")
    async def checkperms(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except Exception:
            pass
        try:
            permissions = ctx.channel.permissions_for(ctx.guild.me)
            perms_list = []
            important_perms = [('send_messages', 'Send Messages'),
                               ('embed_links', 'Embed Links'),
                               ('use_external_emojis', 'Use External Emojis'),
                               ('read_message_history', 'Read Message History'),
                               ('view_channel', 'View Channel')]
            for perm_name, display_name in important_perms:
                has_perm = getattr(permissions, perm_name, False)
                status = "✅" if has_perm else "❌"
                perms_list.append(f"{status} {display_name}")
            message = f"**Bot Permissions in {ctx.channel.name}:**\n" + "\n".join(perms_list)
            await ctx.send(message)
        except Exception as e:
            await ctx.send(f"Error checking permissions: {e}")

    @commands.command(name="setwelcome")
    async def setwelcome(self, ctx: commands.Context, channel: discord.TextChannel = None):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        if channel is None:
            await ctx.send("Please specify a channel. Usage: `!setwelcome #channel-name`", delete_after=10)
            return

        global WELCOME_CHANNEL_ID, state
        old = WELCOME_CHANNEL_ID
        WELCOME_CHANNEL_ID = channel.id
        state["welcome_channel_id"] = WELCOME_CHANNEL_ID
        save_state(state)
        logger.info(f"Welcome channel updated from {old} to {WELCOME_CHANNEL_ID} by {ctx.author}")
        await ctx.send(f"Welcome channel updated to {channel.mention}", delete_after=10)

    @commands.command(name="testwelcome")
    async def testwelcome(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        guild = ctx.guild
        member = ctx.author

        logger.info(f"Testing welcome with channel ID: {WELCOME_CHANNEL_ID}")
        welcome_channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel and welcome_channel.guild == guild:
            try:
                view = WelcomeView(guild.member_count)
                await welcome_channel.send(f"Welcome **-** {member.mention} to **Nebraska State Roleplay** thank you so much for joining!", view=view)
                await ctx.send(f"✅ Test welcome message sent to {welcome_channel.mention}", delete_after=8)
            except Exception as e:
                logger.exception("Error sending test welcome")
                await ctx.send(f"❌ Error sending test welcome message: {e}")
        else:
            await ctx.send(f"❌ Welcome channel not found or not in this guild (ID: {WELCOME_CHANNEL_ID})", delete_after=10)


# ---------------------
# Bot setup & events
# ---------------------
class NebraskaBot:
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True

        self.bot = commands.Bot(
            command_prefix=BotConfig.COMMAND_PREFIX,
            case_insensitive=BotConfig.CASE_INSENSITIVE,
            intents=intents,
            help_command=None
        )
        self.logger = logging.getLogger("NebraskaBot")

    async def setup(self):
        # Add cogs properly
        await self.bot.add_cog(BasicCommands(self.bot))

        # Events
        @self.bot.event
        async def on_ready():
            self.logger.info(f"Bot ready: {self.bot.user} (ID: {self.bot.user.id})")
            print(f"Bot is ready: {self.bot.user} (Guilds: {len(self.bot.guilds)})")

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author == self.bot.user:
                return
            await self.bot.process_commands(message)

        @self.bot.event
        async def on_guild_join(guild: discord.Guild):
            self.logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")

        @self.bot.event
        async def on_guild_remove(guild: discord.Guild):
            self.logger.info(f"Left guild: {guild.name} (ID: {guild.id})")

        @self.bot.event
        async def on_member_join(member: discord.Member):
            guild = member.guild
            logger.info(f"Member joined: {member} in guild {guild.name} ({guild.id}). Member count: {guild.member_count}")
            target_guild_id = 1349505197210206350
            if guild.id != target_guild_id:
                return

            welcome_channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
            if not welcome_channel:
                logger.error(f"Welcome channel ID {WELCOME_CHANNEL_ID} not found in bot caches for guild {guild.name}")
                return

            try:
                view = WelcomeView(guild.member_count)
                await welcome_channel.send(f"Welcome **-** {member.mention} to **Nebraska State Roleplay** thank you so much for joining!", view=view)
            except Exception:
                logger.exception("Failed to send welcome message")


    async def run(self, token: str):
        if not token:
            raise RuntimeError("Bot token missing")
        await self.setup()  # await setup to register cogs
        await self.bot.start(token)


# ---------------------
# Main entry
# ---------------------
def main():
    logger.info("Starting Nebraska State Roleplay bot")
    is_valid, errors = BotConfig.validate_config()
    if not is_valid:
        logger.error("Config validation failed:")
        for e in errors:
            logger.error(f"  - {e}")
        return

    bot = NebraskaBot()
    try:
        asyncio.run(bot.run(BotConfig.TOKEN))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as exc:
        logger.exception(f"Bot crashed: {exc}")


if __name__ == "__main__":
    main()
