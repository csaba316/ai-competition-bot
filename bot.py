import os
import aiohttp
import asyncpraw
import asyncio
import discord
import json
import hashlib
import spacy
from datetime import datetime
from bs4 import BeautifulSoup

# Twitter API Configuration
BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_ACCOUNTS = ["AIcrowd", "Kaggle", "DrivenDataOrg", "MLcontests"]
TWITTER_KEYWORDS = ["AI competition", "machine learning challenge", "hackathon", "prize", "submission", "AI contest"]

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

# ✅ Initialize Reddit properly inside an async function
async def initialize_reddit():
    global reddit
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
    )

# ✅ Function to send a test message when the bot starts
async def send_startup_message(channel):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    message = f"✅ Bot started successfully!\n📅 Timestamp: `{now}`"
    await channel.send(message)

# ✅ Fetch Twitter AI Competitions
async def check_twitter():
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    tweets = []
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for account in TWITTER_ACCOUNTS:
            url = f"https://api.twitter.com/2/tweets/search/recent?query=from:{account}&tweet.fields=text,created_at,public_metrics&max_results=10"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    for tweet in data.get("data", []):
                        if any(keyword.lower() in tweet["text"].lower() for keyword in TWITTER_KEYWORDS):
                            tweets.append((tweet["text"], f"https://twitter.com/{account}/status/{tweet['id']}"))
    return tweets

# ✅ Check AI competitions from MLContests
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

# ✅ Check Reddit for AI Competitions
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

# ✅ Discord Bot Class
class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await initialize_reddit()  # ✅ Initialize Reddit once when bot starts
        
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            await send_startup_message(channel)
        
        self.bg_task = self.loop.create_task(self.check_and_send_updates())

    async def check_and_send_updates(self):
        await self.wait_until_ready()
        channel = self.get_channel(CHANNEL_ID)

        while not self.is_closed():
            try:
                contests = await check_ml_contests()
                reddit_posts = await check_reddit()
                twitter_posts = await check_twitter()
                all_contests = contests + reddit_posts + twitter_posts

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
