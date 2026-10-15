import os
import io
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Apka Telegram Bot Token yahan daalein
TOKEN = "8857671703:AAHSIW_f1trqBwr43SyunwWUTjI8knMtipg"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
telegram_app = Application.builder().token(TOKEN).build()

# Scorecard Image Generating Logic (Pillow)
def generate_scorecard(candidate_name, roll_no, marks_data):
    img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("arial.ttf", 24)
        font_small = ImageFont.truetype("arial.ttf", 18)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Header
    draw.rectangle([0, 0, 800, 80], fill=(24, 43, 73))
    draw.text((30, 25), "RAILWAY / SSC EXAM SCORECARD (RANKGURUJI)", fill=(255, 255, 255), font=font_large)

    # Details
    draw.text((30, 110), f"Candidate Name: {candidate_name}", fill=(0, 0, 0), font=font_small)
    draw.text((30, 140), f"Roll Number: {roll_no}", fill=(0, 0, 0), font=font_small)

    # Marks Summary Box
    draw.rectangle([30, 190, 770, 350], outline=(200, 200, 200), width=2)
    draw.text((50, 210), f"Correct Answers: {marks_data['correct']}", fill=(0, 128, 0), font=font_small)
    draw.text((50, 250), f"Incorrect Answers: {marks_data['incorrect']}", fill=(255, 0, 0), font=font_small)
    draw.text((50, 290), f"Final Score: {marks_data['score']:.2f}", fill=(0, 0, 128), font=font_large)

    # Watermark
    draw.text((250, 450), "SELECTION ROADMAP", fill=(220, 220, 220), font=font_large)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

# Telegram Message Handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "digialm.com" in text:
        await update.message.reply_text("⏳ Processing your answer key link, please wait...")
        try:
            # Dummy parsing logic (apna original parser yahan laga sakte hain)
            marks_data = {'correct': 75, 'incorrect': 15, 'score': 71.05}
            img_buffer = generate_scorecard("Rahul Kumar", "RRB123456", marks_data)
            await update.message.reply_photo(photo=img_buffer, caption="🎉 Here is your official RankGuruji Scorecard!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error processing link: {str(e)}")
    else:
        await update.message.reply_text("⚠️ Please send a valid TCS iON / Digialm answer key link.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Welcome! Send your TCS iON answer key link to get your Scorecard.")

# Flask Webhook Route
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, telegram_app.bot)
    telegram_app.update_queue.put_nowait(update)
    return "OK", 200

@app.route("/")
def index():
    return "Bot is running live via Webhook!", 200

if __name__ == "__main__":
    import asyncio
    async def setup_webhook():
        await telegram_app.initialize()
        # Render par deploy hone ke baad apna Render URL yahan set karna hoga
        # await telegram_app.bot.set_webhook(url=f"https://YOUR_RENDER_SERVICE_URL/{TOKEN}")
        
    asyncio.run(setup_webhook())
    app.run(host="0.0.0.0", port=PORT)