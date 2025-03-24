import os
import aiohttp
import asyncpraw
import asyncio
import discord
import json
import logging
import re
import hashlib
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
from newspaper import Article
import nltk
import random
from urllib.robotparser import RobotFileParser

# Attempt to import Brotli. If unavailable, adjust headers accordingly.
try:
    import brotli
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False

# Set NLTK data path
nltk.data.path.append("/usr/share/nltk_data")

# Download NLTK data (punkt) if it's not already present
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', download_dir='/usr/share/nltk_data')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --- Configuration ---
REDDIT_SUBREDDITS = [
    "AICompetitions", "AIArt", "ArtificialInteligence", "aivideo", "ChatGPT",
    "aipromptprogramming", "SunoAI", "singularity", "StableDiffusion", "weirddalle",
    "MidJourney", "Artificial", "OpenAI", "runwayml"
]
REDDIT_KEYWORDS = [
    "AI contest",
    "AI competition",
    "artificial intelligence contest",
    "AI art contest",
    "generative AI contest",
    "generative AI competition",
    "machine learning contest",
    "deep learning contest",
    "creative AI contest",
    "AI challenge",
    "AI hackathon",
    "machine learning hackathon",
    "art contest",
    "digital art competition",
    "AI design contest",
    "prompt engineering contest",
    "innovation challenge",
    "call for entries",
    "open call contest",
    "submission deadline"
]
NEGATIVE_REDDIT_KEYWORDS = [
    "job", "hiring", "salary", "course", "tutorial", "research", "paper",
    "academic", "university", "conference", "discussion", "question",
    "opinion", "looking for", "seeking", "help", "advice"
]
REDDIT_SCORE_THRESHOLDS = {
    "AICompetitions": 50,
    "AIArt": 75,
    "ArtificialInteligence": 100,
    "ChatGPT": 100,
    "StableDiffusion": 75,
    "MidJourney": 75,
    "DEFAULT": 50,
}
# Advanced search query for targeted posts.
ADVANCED_SEARCH_QUERY = '"AI contest" OR "generative AI competition"'

# Build compiled regex patterns for each keyword (case-insensitive)
REDDIT_PATTERNS = [re.compile(r'\b' + re.escape(keyword.lower()) + r'\b') for keyword in REDDIT_KEYWORDS]

# --- Website Scraping (Commented Out) ---
"""
WEBSITES = [
    {"url": "https://mlcontests.com/", "source": "MLContests"},
    {"url": "https://curiousrefuge.com/", "source": "CuriousRefuge"},
    {"url": "https://curiousrefuge.com/ai-contests", "source": "CuriousRefuge"},
    {"url": "https://www.projectodyssey.ai/", "source": "ProjectOdyssey"},
    {"url": "https://runwayml.com/", "source": "RunwayML"},
    {"url": "https://suno.com/blog", "source": "SunoBlog"},
    {"url": "https://openai.com", "source": "OpenAI"},
    {"url": "https://openai.com/news/", "source": "OpenAINews"},
    {"url": "https://lumalabs.ai/", "source": "LumaLabs"},
    {"url": "https://klingai.com/activity-zone", "source": "KlingAI"},
    {"url": "https://deepmind.google/technologies/veo/veo-2/", "source": "DeepmindVeo"},
    {"url": "https://leonardo.ai/", "source": "LeonardoAI"},
    {"url": "https://leonardo.ai/news/", "source": "LeonardoAINews"},
    {"url": "https://worldaifilmfestival.com/en/", "source": "WorldAIFilmFestival"},
    {"url": "https://aiff.runwayml.com/", "source": "AIFFRunwayML"},
    {"url": "https://challenges.reply.com/ai-film-festival/home/", "source": "ReplyAIChallenge"},
    {"url": "https://www.filmawards.ai/", "source": "FilmAwardsAI"},
    {"url": "https://www.filmawards.ai/Articles/", "source": "FilmAwardsAIArticles"},
    {"url": "https://filmfreeway.com/festivals", "source": "FilmFreeway"},
    {"url": "https://melies.co/", "source": "Melies"},
    {"url": "https://melies.co/blog", "source": "MeliesBlog"},
    {"url": "https://aifilmfest.io/", "source": "AIFilmFestIO"},
]
"""

# --- Utility Functions ---
def generate_post_hash(title, text):
    return hashlib.sha256((title + text).encode()).hexdigest()

def is_same_domain(url1, url2):
    """Checks if two URLs belong to the same domain."""
    return urlparse(url1).netloc == urlparse(url2).netloc

# --- Reddit Collection Refinement ---
async def check_reddit(reddit_client):
    if reddit_client is None:
        raise ValueError("Reddit client not initialized.")

    new_posts = []
    past_alerts_file = "past_alerts.json"
    try:
        with open(past_alerts_file, "r") as file:
            past_alerts = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        past_alerts = {"reddit_hashes": []}

    reddit_hashes = past_alerts.get("reddit_hashes", [])

    for sub in REDDIT_SUBREDDITS:
        try:
            subreddit = await reddit_client.subreddit(sub)
            # Use advanced Reddit search with precise phrases
            logger.info(f"Searching r/{sub} using advanced query: {ADVANCED_SEARCH_QUERY}")
            async for submission in subreddit.search(
                ADVANCED_SEARCH_QUERY,
                sort="new",
                time_filter="month",
                limit=20
            ):
                post_hash = generate_post_hash(submission.title, submission.selftext)
                score_threshold = REDDIT_SCORE_THRESHOLDS.get(sub, REDDIT_SCORE_THRESHOLDS["DEFAULT"])

                if (
                    submission.score > score_threshold and
                    submission.upvote_ratio > 0.7 and
                    post_hash not in reddit_hashes
                ):
                    text_to_check = submission.title.lower()
                    if submission.is_self:
                        text_to_check += " " + submission.selftext.lower()

                    # Exclude posts with any negative keywords
                    if any(neg_word in text_to_check for neg_word in NEGATIVE_REDDIT_KEYWORDS):
                        continue

                    # Use regex patterns for refined keyword matching
                    if any(pattern.search(text_to_check) for pattern in REDDIT_PATTERNS):
                        post_data = {
                            "title": submission.title,
                            "url": f"https://www.reddit.com{submission.permalink}",
                            "subreddit": sub,
                            "score": submission.score,
                            "comments": submission.num_comments,
                            "source": "Reddit"
                        }
                        new_posts.append(post_data)
                        reddit_hashes.append(post_hash)
        except asyncpraw.exceptions.PRAWException as e:
            logger.error(f"Error fetching posts from r/{sub}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in check_reddit (subreddit {sub}): {e}")

    past_alerts["reddit_hashes"] = reddit_hashes
    try:
        with open(past_alerts_file, "w") as file:
            json.dump(past_alerts, file)
    except (IOError, OSError) as e:
        logger.error(f"Error writing to past_alerts.json: {e}")
    return new_posts

# --- Discord Bot ---
async def initialize_reddit():
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),  # Use a descriptive User-Agent for Reddit
    )
    return reddit

async def send_startup_message(channel):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    message = f"✅ Bot started successfully!\n📅 Timestamp: `{now}`"
    await channel.send(message)

class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        self.reddit_client = await initialize_reddit()
        channel = self.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        if channel:
            await send_startup_message(channel)
        # Commented out website scraping task:
        # self.bg_task = self.loop.create_task(self.check_websites_daily())
        self.reddit_task = self.loop.create_task(self.check_reddit_periodically())

    # Website scraping function removed/commented out for now.
    """
    async def check_websites_daily(self):
        # Website scraping code would go here.
        pass
    """

    async def check_reddit_periodically(self):
        await self.wait_until_ready()
        channel = self.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        while not self.is_closed():
            try:
                logger.info("Checking Reddit with advanced search...")
                reddit_contests = await check_reddit(self.reddit_client)
                if reddit_contests:
                    await self.send_discord_notification(channel, reddit_contests)
            except asyncpraw.exceptions.PRAWException as e:
                logger.error(f"PRAW exception in check_reddit_periodically: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error in check_reddit_periodically: {e}")
            finally:
                await asyncio.sleep(3600 * 24)  # Sleep 6 hours

    async def send_discord_notification(self, channel, contests):
        for contest in contests:
            if contest['source'] == "Reddit":
                embed = discord.Embed(
                    title=contest["title"],
                    url=contest["url"],
                    color=discord.Color.orange(),
                    description=f"From r/{contest['subreddit']} (Score: {contest['score']}, Comments: {contest['comments']})",
                )
            else:
                embed = discord.Embed(
                    title=contest['title'],
                    url=contest.get('link', contest.get('url')),
                    color=discord.Color.green()
                )
                if "description" in contest:
                    embed.description = contest["description"]
                if "deadline" in contest:
                    embed.add_field(name="Deadline", value=str(contest["deadline"]))
            await channel.send(embed=embed)

# --- Main ---
intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)
client.run(os.getenv("DISCORD_TOKEN"))
