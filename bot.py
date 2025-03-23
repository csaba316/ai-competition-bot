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
    "AI art contest", "generative art competition", "AI challenge",
    "machine learning competition", "hackathon", "art prize", "cash prize",
    "$ prize", "AI art competition", "AI design contest", "submission deadline",
    "call for entries", "creative AI challenge", "prompt engineering contest"
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

# --- Utility Functions ---
def generate_post_hash(title, text):
    return hashlib.sha256((title + text).encode()).hexdigest()

def is_same_domain(url1, url2):
    """Checks if two URLs belong to the same domain."""
    return urlparse(url1).netloc == urlparse(url2).netloc

# --- Scraping Functions ---

# List of User-Agents (add more for better rotation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    # Add more User-Agents here...
]

# Updated Headers to mimic a real browser
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_ROBOTS_CACHE = {}
_ROBOTS_CACHE_TIMEOUT = timedelta(hours=24)

async def fetch_robots_txt(session, url):
    """Fetches and parses the robots.txt file for a given URL, with caching.
    Uses Python's built-in RobotFileParser.
    """
    robots_url = urljoin(url, "/robots.txt")
    domain = urlparse(url).netloc

    if domain in _ROBOTS_CACHE:
        parser, cached_time = _ROBOTS_CACHE[domain]
        if datetime.utcnow() - cached_time < _ROBOTS_CACHE_TIMEOUT:
            return parser

    try:
        async with session.get(robots_url, headers=HEADERS) as response:
            if response.status == 200:
                text = await response.text()
                parser = RobotFileParser()
                parser.parse(text.splitlines())
                _ROBOTS_CACHE[domain] = (parser, datetime.utcnow())
                return parser
            else:
                logger.warning(f"Failed to fetch robots.txt for {url}, status: {response.status}")
                return None
    except Exception as e:
        logger.warning(f"Error fetching robots.txt for {url}: {e}")
        return None

async def scrape_website(session, website_data):
    url = website_data["url"]
    source = website_data["source"]
    contests = []

    try:
        # --- Respect robots.txt ---
        robots_ruleset = await fetch_robots_txt(session, url)
        if robots_ruleset and not robots_ruleset.can_fetch("*", url):
            logger.warning(f"Skipping {url} due to robots.txt disallow")
            return []

        # --- Set User-Agent and Headers ---
        headers = HEADERS.copy()
        headers["User-Agent"] = random.choice(USER_AGENTS)

        async with session.get(url, headers=headers) as response:
            # Gracefully handle non-200 responses
            if response.status != 200:
                logger.warning(f"Non-200 response from {url}: {response.status}")
                return []
            html = await response.text()

        article = Article(url)
        article.download(input_html=html)
        article.parse()

        # Keyword Filtering - using summary *BEFORE* calling .nlp()
        if any(keyword in article.summary.lower() for keyword in REDDIT_KEYWORDS):
            contests.append({
                "title": article.title,
                "link": url,
                "description": article.summary,
                "source": source,
                "deadline": None,
            })

    except aiohttp.ClientError as e:
        logger.error(f"Error fetching from {url}: {str(e)}")
    except Exception as e:
        logger.exception(f"Unexpected error scraping {url}: {e}")
    return contests

async def check_websites():
    all_contests = []
    checked_urls = set()

    async with aiohttp.ClientSession() as session:  # Re-use the same session
        for website_data in WEBSITES:
            url = website_data["url"]
            if url in checked_urls:
                logger.info(f"Skipping duplicate URL: {url}")
                continue
            checked_urls.add(url)

            try:
                contests = await scrape_website(session, website_data)
                all_contests.extend(contests)
                await asyncio.sleep(5)  # Increased delay
            except Exception as e:
                logger.exception(f"Error checking website {website_data['url']}: {e}")
    return all_contests

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
            async for submission in subreddit.hot(limit=10):
                post_hash = generate_post_hash(submission.title, submission.selftext)
                score_threshold = REDDIT_SCORE_THRESHOLDS.get(sub, REDDIT_SCORE_THRESHOLDS["DEFAULT"])

                if (
                    submission.score > score_threshold
                    and submission.upvote_ratio > 0.7
                    and post_hash not in reddit_hashes
                ):
                    text_to_check = submission.title.lower()
                    if submission.is_self:
                        text_to_check += " " + submission.selftext.lower()

                    if any(neg_word in text_to_check for neg_word in NEGATIVE_REDDIT_KEYWORDS):
                        continue

                    if any(word in text_to_check for word in REDDIT_KEYWORDS):
                        if submission.url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.mp4', '.webm', '.mov')):
                            logger.info(f"Skipping image/video post: {submission.url}")
                            continue
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
        self.bg_task = self.loop.create_task(self.check_websites_daily())
        self.reddit_task = self.loop.create_task(self.check_reddit_periodically())

    async def check_websites_daily(self):
        await self.wait_until_ready()
        channel = self.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        last_check_file = "last_website_check.json"

        while not self.is_closed():
            try:
                with open(last_check_file, "r") as file:
                    last_check_data = json.load(file)
                    last_check = last_check_data.get("last_check")
            except (FileNotFoundError, json.JSONDecodeError):
                last_check = None

            if last_check is None or (datetime.utcnow() - datetime.fromisoformat(last_check)) >= timedelta(days=1):
                logger.info("Performing daily website check...")
                website_contests = await check_websites()

                if website_contests:
                    await self.send_discord_notification(channel, website_contests)

                with open(last_check_file, "w") as file:
                    json.dump({"last_check": datetime.utcnow().isoformat()}, file)
            else:
                remaining_time = (datetime.fromisoformat(last_check) + timedelta(days=1)) - datetime.utcnow()
                logger.info(f"Next website check in {remaining_time}")
            await asyncio.sleep(3600)  # Check every hour if it is time

    async def check_reddit_periodically(self):
        await self.wait_until_ready()
        channel = self.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        while not self.is_closed():
            try:
                logger.info("Checking Reddit...")
                reddit_contests = await check_reddit(self.reddit_client)
                if reddit_contests:
                    await self.send_discord_notification(channel, reddit_contests)
            except asyncpraw.exceptions.PRAWException as e:  # Handle PRAW exceptions
                logger.error(f"PRAW exception in check_reddit_periodically: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error in check_reddit_periodically: {e}")
            finally:
                await asyncio.sleep(3600 * 6)  # Always sleep, even on error

    async def send_discord_notification(self, channel, contests):
        for contest in contests:
            if contest['source'] == "Reddit":
                embed = discord.Embed(
                    title=contest["title"],
                    url=contest["url"],
                    color=discord.Color.orange(),
                    description=f"From r/{contest['subreddit']} (Score: {contest['score']}, Comments: {contest['comments']})",
                )
            else:  # Now uses this for all website checks
                embed = discord.Embed(
                    title=contest['title'],
                    url=contest.get('link', contest.get('url')),
                    color=discord.Color.green()
                )
                if "description" in contest:
                    embed.description = contest["description"]
                if "deadline" in contest:  # Check for deadline
                    embed.add_field(name="Deadline", value=str(contest["deadline"]))
            await channel.send(embed=embed)

# --- Main ---
intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)
client.run(os.getenv("DISCORD_TOKEN"))
