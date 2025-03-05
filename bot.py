import requests
import praw
import schedule
import time
import asyncio
import discord
from bs4 import BeautifulSoup
import os


# Load Reddit API credentials from environment variables
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT")
)

# Discord Bot Configuration
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
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

# Function to check Reddit for AI Competitions
def check_reddit():
    subreddits = ["AICompetitions", "AIArt", "ArtificialIntelligence"]
    new_posts = []
    
    for sub in subreddits:
        for submission in reddit.subreddit(sub).new(limit=5):  # Get 5 latest posts per subreddit
            new_posts.append((submission.title, submission.url))
    
    return new_posts

# Discord Bot Class
class MyClient(discord.Client):
    async def on_ready(self):
        channel = self.get_channel(CHANNEL_ID)
        contests = check_ml_contests() + check_reddit()
        if contests:
            message = "**New AI Competitions Found!**\n\n" + "\n".join([f"[{title}]({link})" for title, link in contests])
            await channel.send(message)
        await self.close()

client = MyClient(intents=discord.Intents.default())

# Function to run bot and send alerts
def job():
    contests = check_ml_contests() + check_reddit()
    if contests:
        asyncio.run(client.start(DISCORD_TOKEN))

# Schedule the bot to run every hour
schedule.every(1).hours.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)
