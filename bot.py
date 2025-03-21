import os
import aiohttp
import asyncpraw
import asyncio
import discord
import json
import logging
import re
import hashlib
from bs4 import BeautifulSoup  # Still useful for some tasks
from urllib.parse import urljoin
from datetime import datetime, timedelta
from newspaper import Article  # Import newspaper3k
import nltk  # Import nltk

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --- Configuration ---
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

# Simplified WEBSITES list (no selectors needed for newspaper3k)
WEBSITES = [
    {"url": "https://mlcontests.com/", "source": "MLContests"},
    {"url": "https://www.kaggle.com/competitions", "source": "Kaggle"}, #Example
    # Add more websites here
]

# --- Utility Functions ---
def generate_post_hash(title, text):
    return hashlib.sha256((title + text).encode()).hexdigest()

# --- Scraping Functions ---

async def scrape_website(session, website_data):
    url = website_data["url"]
    source = website_data["source"]
    contests = []
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()

        article = Article(url)
        article.download(input_html=html)  # Pass the downloaded HTML
        article.parse()
        # article.nlp()  # Optional: For keywords, authors, summary, etc.

        # Keyword Filtering (Refine as needed)
        if any(keyword in article.text.lower() for keyword in REDDIT_KEYWORDS):
            contests.append({
                "title": article.title,
                "link": url,
                "description": article.text[:500] + ("..." if len(article.text) > 500 else ""), #Limit length
                "source": source,
                "deadline": None,  # newspaper3k's date extraction is unreliable
            })

    except aiohttp.ClientError as e:
        logger.error(f"Error fetching from {url}: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error scraping {url}: {e}")
    return contests


async def check_websites():
    all_contests = []
    async with aiohttp.ClientSession() as session:
        for website_data in WEBSITES:
            try:
                contests = await scrape_website(session, website_data)
                all_contests.extend(contests)
                await asyncio.sleep(1)  # Be polite
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
                # --- Website Check (Twice Daily) ---
                last_check_file = "last_website_check.json"
                try:
                    with open(last_check_file, "r") as file:
                        last_check_data = json.load(file)
                        last_check = last_check_data.get("last_check")
                except (FileNotFoundError, json.JSONDecodeError):
                    last_check = None

                if last_check is None or (datetime.utcnow() - datetime.fromisoformat(last_check)) >= timedelta(hours=12):
                    website_contests = await check_websites()

                    with open(last_check_file, "w") as file:
                        json.dump({"last_check": datetime.utcnow().isoformat()}, file)
                else:
                    website_contests = []

                # --- Reddit Check ---
                reddit_posts = await check_reddit(self.reddit_client)

                all_contests = website_contests + reddit_posts


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
            # No more MLContest specific check
            # elif contest['source'] == "MLContests":
            #     embed = discord.Embed(
            #         title=contest["title"],
            #         url=contest["link"],
            #         color=discord.Color.green()
            #     )
            #     if "description" in contest:
            #         embed.description = contest["description"]
            #     if "deadline" in contest:
            #         embed.add_field(name="Deadline", value=str(contest["deadline"]))

            else: #Now uses this for all website checks
                embed = discord.Embed(
                    title = contest['title'],
                    url = contest.get('link', contest.get('url')),
                    color = discord.Color.green()
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
