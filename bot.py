import os
import aiohttp
import asyncpraw
import asyncio
import discord
import json
import hashlib
import feedparser
import spacy
from bs4 import BeautifulSoup

# Discord Bot Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# Global Reddit variable (initialized later)
reddit = None

# Initialize NLP
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    from spacy.cli import download
    download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")


# ✅ Fix: Ensure `reddit` is initialized properly in an async function
async def initialize_reddit():
    global reddit
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
    )

# ✅ Fix: Ensure API requests are async
async def check_ml_contests():
    url = "https://mlcontests.com/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()

    soup = BeautifulSoup(html, 'html.parser')
    
    contests = []
    for contest in soup.find_all("div", class_="contest-item"):
        title = contest.find("h2").text
        link = contest.find("a")["href"]
        contests.append((title, link))
    
    return contests


# ✅ Fix: Ensure `asyncpraw` is used properly
async def check_reddit():
    if reddit is None:
        await initialize_reddit()
        
    subreddits = ["AICompetitions", "AIArt", "ArtificialInteligence", "aivideo", "ChatGPT", "aipromptprogramming", "SunoAI", "singularity", "StableDiffusion", "weirddalle", "MidJourney", "Artificial", "OpenAI", "runwayml"]
    keywords = ["contest", "competition", "challenge", "prize", "submission", "AI contest", "AI challenge", "hackathon", "art battle", "film contest", "annual", "festival"]
    
    new_posts = []
    past_alerts_file = "past_alerts.json"

    try:
        with open(past_alerts_file, "r") as file:
            past_alerts = json.load(file)
    except FileNotFoundError:
        past_alerts = []

    for sub in subreddits:
        subreddit = await reddit.subreddit(sub)
        async for submission in subreddit.hot(limit=10):
            post_hash = hashlib.sha256((submission.title + submission.selftext).encode()).hexdigest()
            if submission.score > 50 and post_hash not in past_alerts:
                doc = nlp(submission.title.lower() + " " + submission.selftext.lower())
                if any(word in doc.text for word in keywords):
                    post_data = {
                        "title": submission.title,
                        "url": submission.url,
                        "subreddit": sub,
                        "score": submission.score,
                        "comments": submission.num_comments
                    }
                    new_posts.append(post_data)
                    past_alerts.append(post_hash)

    with open(past_alerts_file, "w") as file:
        json.dump(past_alerts, file)

    return new_posts


# ✅ Fix: Ensure RSS fetch is async
async def check_rss_feed():
    feed_url = "https://www.aicrowd.com/challenges.rss"
    async with aiohttp.ClientSession() as session:
        async with session.get(feed_url) as response:
            xml = await response.text()
    
    feed = feedparser.parse(xml)
    
    competitions = []
    for entry in feed.entries:
        competitions.append((entry.title, entry.link))
    
    return competitions


# Discord Bot Class
class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await initialize_reddit()  # ✅ Initialize Reddit once when bot starts
        self.bg_task = self.loop.create_task(self.check_and_send_updates())

    async def check_and_send_updates(self):
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)

        while not self.is_closed():
            try:
                contests = await check_ml_contests()
                reddit_posts = await check_reddit()
                rss_competitions = await check_rss_feed()

                all_contests = contests + reddit_posts + rss_competitions

                if all_contests:
                    message = "**New AI Competitions Found!**\n\n"
                    for contest in all_contests:
                        if isinstance(contest, tuple):  
                            message += f"[{contest[0]}]({contest[1]})\n"
                        else:  
                            message += f"[{contest['title']}]({contest['url']}) (r/{contest['subreddit']})\n"

                    await channel.send(message)

            except Exception as e:
                print(f"Error checking competitions: {e}")

            await asyncio.sleep(3600)  # ✅ Wait 1 hour before next check


# ✅ Use intents for Discord bot
intents = discord.Intents.default()
client = MyClient(intents=intents)

# Run the bot
client.run(DISCORD_TOKEN)
