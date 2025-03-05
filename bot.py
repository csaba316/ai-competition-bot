import os
import json
import praw
import requests
import schedule
import time
import asyncio
import discord
from bs4 import BeautifulSoup

# Load Reddit API credentials from environment variables
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT")
)

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

# Function to check Reddit for AI Competitions
def check_reddit():
    subreddits = ["AICompetitions", "AIArt", "ArtificialInteligence", "aivideo", "ChatGPT", "aipromptprogramming", "SunoAI", "singularity", "StableDiffusion", "weirddalle", "MidJourney", "Artificial", "OpenAI", "runwayml"]
    new_posts = []
    
    keywords = ["contest", "competition", "challenge", "prize", "submission", "AI contest", "AI challenge", "hackathon", "art battle", "film contest"]
    
    past_alerts_file = "past_alerts.json"
    
    try:
        with open(past_alerts_file, "r") as file:
            past_alerts = json.load(file)
    except FileNotFoundError:
        past_alerts = []
    
    for sub in subreddits:
        for submission in reddit.subreddit(sub).new(limit=10):  # Fetch more posts for filtering
            if any(keyword in submission.title.lower() for keyword in keywords) and submission.id not in past_alerts:
                new_posts.append((submission.title, submission.url))
                past_alerts.append(submission.id)
    
    # Save updated alert history
    with open(past_alerts_file, "w") as file:
        json.dump(past_alerts, file)
    
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
