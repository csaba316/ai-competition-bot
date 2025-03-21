import os
import aiohttp
import asyncpraw
import asyncio
import discord
import json
import logging
import re
import hashlib  # Import hashlib here
from bs4 import BeautifulSoup
from aiolimiter import AsyncLimiter
from urllib.parse import urljoin
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --- Configuration ---
# Get values directly from environment variables set in Railway
TWITTER_ACCOUNTS = ["AIcrowd", "Kaggle", "DrivenDataOrg", "MLcontests"] # Keep as list in the code
TWITTER_KEYWORDS = ["AI competition", "machine learning challenge", "hackathon", "prize", "submission", "AI contest"]
REDDIT_SUBREDDITS = ["AICompetitions", "AIArt", "ArtificialInteligence", "aivideo", "ChatGPT", "aipromptprogramming", "SunoAI", "singularity", "StableDiffusion", "weirddalle", "MidJourney", "Artificial", "OpenAI", "runwayml"]
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


# --- Utility Functions ---
def generate_post_hash(title, text):
    return hashlib.sha256((title + text).encode()).hexdigest()

def parse_deadline(deadline_text):
    """
    Parses a deadline string. Placeholder: Implement based on formats.
    """
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", deadline_text)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d/%m/%Y') # Adapt
        except ValueError:
            return None
    return None

# --- Scraping Functions ---

# Twitter API Rate Limiter - VERY CONSERVATIVE
twitter_limiter = AsyncLimiter(1, 60)  # Max 1 request per 60 seconds

async def check_twitter(bearer_token):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    tweets = []

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            for account in TWITTER_ACCOUNTS:
                url = f"https://api.twitter.com/2/tweets/search/recent?query=from:{account}&tweet.fields=text,created_at,public_metrics&max_results=10"
                async with twitter_limiter:  # Rate limiting
                    try:
                        async with session.get(url) as response:
                            if response.status == 429:
                                logger.warning(f"Twitter API rate limit exceeded for {account}. Waiting...")
                                await asyncio.sleep(60)  # Wait before retrying
                                continue # Skip to the next account

                            response.raise_for_status() #Will raise for other errors
                            data = await response.json()
                            for tweet in data.get("data", []):
                                if any(keyword.lower() in tweet["text"].lower() for keyword in TWITTER_KEYWORDS):
                                    tweets.append({
                                        "title": tweet["text"],
                                        "url": f"https://twitter.com/{account}/status/{tweet['id']}",
                                        "source": "Twitter"
                                    })
                    except aiohttp.ClientError as e:
                        logger.error(f"Error fetching tweets from {account}: {e}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding JSON from Twitter API: {e}")
                    except Exception as e:  # Catch-all for unexpected errors
                        logger.exception(f"Unexpected error with Twitter API: {e}")

    except Exception as e:
        logger.exception(f"Unexpected error in check_twitter: {e}")
    return tweets



async def check_ml_contests():
    url = "https://mlcontests.com/"
    contests = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, 'lxml')

            for contest in soup.select("div.contest-item"):
                title_element = contest.select_one("h2 a")
                if title_element:
                    title = title_element.text.strip()
                    link = urljoin(url, title_element['href'])
                    description_element = contest.select_one("div.contest-description") #Hypothetical
                    description = description_element.text.strip() if description_element else "No description."
                    deadline_element = contest.select_one("span.contest-deadline")  #Hypothetical
                    deadline = parse_deadline(deadline_element.text.strip()) if deadline_element else None

                    contests.append({
                        "title": title,
                        "link": link,
                        "description": description,
                        "deadline": deadline,
                        "source": "MLContests"
                    })
                    await asyncio.sleep(1) # Rate Limiting - Increased delay
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching from MLContests: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in check_ml_contests: {e}")
    return contests


async def check_reddit(reddit_client):
    if reddit_client is None:
        raise ValueError("Reddit client not initialized.")

    new_posts = []
    past_alerts_file = "past_alerts.json"
    try:
        with open(past_alerts_file, "r") as file:
            past_alerts = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        past_alerts = []

    for sub in REDDIT_SUBREDDITS:
        try:
            subreddit = await reddit_client.subreddit(sub)
            async for submission in subreddit.hot(limit=10):
                post_hash = generate_post_hash(submission.title, submission.selftext)
                score_threshold = REDDIT_SCORE_THRESHOLDS.get(sub, REDDIT_SCORE_THRESHOLDS["DEFAULT"])

                if (
                    submission.score > score_threshold
                    and submission.upvote_ratio > 0.7
                    and post_hash not in past_alerts
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
                        past_alerts.append(post_hash)
        except asyncpraw.exceptions.PRAWException as e:
            logger.error(f"Error fetching posts from r/{sub}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in check_reddit (subreddit {sub}): {e}")

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
         user_agent=os.getenv("REDDIT_USER_AGENT"),
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
        self.bg_task = self.loop.create_task(self.check_and_send_updates())

    async def check_and_send_updates(self):
        await self.wait_until_ready()
        channel = self.get_channel(int(os.getenv("DISCORD_CHANNEL_ID")))
        while not self.is_closed():
            try:
                contests = await check_ml_contests()
                reddit_posts = await check_reddit(self.reddit_client)
                twitter_posts = await check_twitter(os.getenv("TWITTER_BEARER_TOKEN"))
                all_contests = contests + reddit_posts + twitter_posts

                if all_contests:
                    await self.send_discord_notification(channel, all_contests)

            except Exception as e:
                logger.exception(f"Error in check_and_send_updates: {e}")

            await asyncio.sleep(3600)

    async def send_discord_notification(self, channel, contests):
        for contest in contests:
            if contest['source'] == "Reddit":
                embed = discord.Embed(
                    title=contest["title"],
                    url=contest["url"],
                    color=discord.Color.orange(),
                    description=f"From r/{contest['subreddit']} (Score: {contest['score']}, Comments: {contest['comments']})",
                )
            elif contest['source'] == "Twitter":
                embed = discord.Embed(
                    title=contest["title"],
                    url=contest["url"],
                    color=discord.Color.blue()
                )
            elif contest['source'] == "MLContests":
                embed = discord.Embed(
                    title=contest["title"],
                    url=contest["link"],
                    color=discord.Color.green()
                )
                if "description" in contest:
                    embed.description = contest["description"]
                if "deadline" in contest:
                    embed.add_field(name="Deadline", value=str(contest["deadline"]))
            else:
                embed = discord.Embed( # Fallback
                    title = contest['title'],
                    url = contest['url']
                )

            await channel.send(embed=embed)

# --- Main ---
intents = discord.Intents.default()
intents.message_content = True  # Enable if needed
client = MyClient(intents=intents)
client.run(os.getenv("DISCORD_TOKEN"))
