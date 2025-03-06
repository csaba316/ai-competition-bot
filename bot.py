import os
import json
import praw
import requests
import schedule
import time
import asyncio
import discord
import hashlib
import feedparser
import spacy
from bs4 import BeautifulSoup

# Load Reddit API credentials from environment variables
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT")
)

# Load NLP model
nlp = spacy.load("en_core_web_sm")

# Discord Bot Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# Function to check ML Contests
def check_ml_contests():
    url = "https://mlcontests.com/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    contests = []
    for contest in soup.find_all("div", class_="contest-item"):  # Adjust class based on site's structure
        title = contest.find("h2").text
        link = contest.find("a")["href"]
        contests.append((title, link))
    
    return contests

# Function to hash posts to avoid duplicates
def hash_post(title, body):
    post_text = title + body
    return hashlib.sha256(post_text.encode()).hexdigest()

# Enhanced function to check Reddit for AI Competitions
def check_reddit():
    subreddits = ["AICompetitions", "AIArt", "ArtificialInteligence", "aivideo", "ChatGPT", "aipromptprogramming", "SunoAI", "singularity", "StableDiffusion", "weirddalle", "MidJourney", "Artificial", "OpenAI", "runwayml"]
    keywords = ["contest", "competition", "challenge", "prize", "submission", "AI contest", "AI challenge", "hackathon", "art battle", "film contest"]
    new_posts = []
    past_alerts_file = "past_alerts.json"
    
    try:
        with open(past_alerts_file, "r") as file:
            past_alerts = json.load(file)
    except FileNotFoundError:
        past_alerts = []
    
    for sub in subreddits:
        for submission in reddit.subreddit(sub).hot(limit=15):  # Fetch based on hot ranking
            post_hash = hash_post(submission.title, submission.selftext)
            if submission.score > 50 and post_hash not in past_alerts:  # Prioritize high-engagement posts
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
    
    # Save updated alert history
    with open(past_alerts_file, "w") as file:
        json.dump(past_alerts, file)
    
    return new_posts

# Function to check AI competition RSS feeds
def check_rss_feed():
    feed_url = "https://www.aicrowd.com/challenges.rss"
    feed = feedparser.parse(feed_url)
    
    competitions = []
    for entry in feed.entries:
        competitions.append((entry.title, entry.link))
    
    return competitions

# Discord Bot Class
class MyClient(discord.Client):
    async def on_ready(self):
        channel = self.get_channel(CHANNEL_ID)
        contests = check_ml_contests() + check_reddit() + check_rss_feed()
        if contests:
            message = "**New AI Competitions Found!**\n\n"
            for contest in contests:
                if isinstance(contest, tuple):  # ML Contests and RSS format
                    message += f"[{contest[0]}]({contest[1]})\n"
                else:  # Reddit post format
                    message += f"[{contest['title']}]({contest['url']}) (r/{contest['subreddit']})\n"
            
            await channel.send(message)
        await self.close()

client = MyClient(intents=discord.Intents.default())

# Function to run bot and send alerts
def job():
    contests = check_ml_contests() + check_reddit() + check_rss_feed()
    if contests:
        asyncio.run(client.start(DISCORD_TOKEN))

# Schedule the bot to run every hour
schedule.every(1).hours.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)
