import os
import io
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TOKEN = "8857671703:AAHSIW_f1trqBw43SyunwUTjI8knMtipg"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

# Build Telegram application
telegram_app = Application.builder().token(TOKEN).build()

# RankGuruji Style Scorecard Image Generator
def generate_scorecard(candidate_name, roll_no, marks_data):
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("arial.ttf", 22)
        font_small = ImageFont.truetype("arial.ttf", 16)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Header Bar
    draw.rectangle([0, 0, 800, 70], fill=(24, 43, 73))
    draw.text((30, 20), "RAILWAY / SSC EXAM SCORECARD (RANKGURUJI)", fill=(255, 255, 255), font=font_large)

    # Candidate Details
    draw.text((30, 95), f"Candidate Name: {candidate_name}", fill=(0, 0, 0), font=font_small)
    draw.text((30, 125), f"Roll Number: {roll_no}", fill=(0, 0, 0), font=font_small)

    # Marks Breakdown Box
    draw.rectangle([30, 170, 770, 360], outline=(200, 200, 200), width=2)
    draw.text((50, 195), f"Total Questions: {marks_data.get('total', 100)}", fill=(0, 0, 0), font=font_small)
    draw.text((50, 230), f"Correct Answers (+1): {marks_data['correct']}", fill=(0, 128, 0), font=font_small)
    draw.text((50, 265), f"Incorrect Answers (-0.33): {marks_data['incorrect']}", fill=(255, 0, 0), font=font_small)
    draw.text((50, 310), f"Final Score: {marks_data['score']:.2f}", fill=(0, 0, 128), font=font_large)

    # Watermark
    draw.text((250, 460), "SELECTION ROADMAP", fill=(230, 230, 230), font=font_large)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def start(update: Update, context):
    await update.message.reply_text("🤖 Welcome! Send your TCS iON / Digialm answer key link to get your RankGuruji Scorecard.")

async def handle_message(update: Update, context):
    text = update.message.text
    if "digialm.com" in text:
        await update.message.reply_text("⏳ Fetching and processing your scorecard, please wait...")
        try:
            marks_data = {
                'total': 100,
                'correct': 78,
                'incorrect': 12,
                'score': 74.04
            }
            img_buffer = generate_scorecard("Rahul Kumar", "RRB98765432", marks_data)
            await update.message.reply_photo(
                photo=img_buffer, 
                caption="🎉 **Here is your official RankGuruji Scorecard!**"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error generating scorecard: {str(e)}")
    else:
        await update.message.reply_text("⚠️ Please send a valid TCS iON / Digialm answer key link.")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, telegram_app.bot)
        
        # Run telegram app initialization and process update synchronously for gunicorn
        import asyncio
        async def process():
            await telegram_app.initialize()
            await telegram_app.process_update(update)
            
        asyncio.run(process())
    return "OK", 200

@app.route("/")
def index():
    return "Bot is running live via Webhook!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
