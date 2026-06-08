import os
import re
import json
import requests
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def extract_video_id(url):
    patterns = [
        r"(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def get_transcript(video_id):
    # Supadata API - реальний безкоштовний сервіс
    url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}"
    headers = {"x-api-key": os.environ.get("SUPADATA_API_KEY", "")}
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        chunks = data.get("content", [])
        if chunks:
            return " ".join(c.get("text", "") for c in chunks)
    raise Exception(f"Статус {r.status_code}: субтитри недоступні")

def chunk_text(text, chunk_size=6000):
    words = text.split()
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

def summarize_chunk(chunk, chunk_num, total):
    label = f"(частина {chunk_num}/{total})" if total > 1 else ""
    r = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        messages=[{"role":"user","content":f"Зроби стислий конспект цього фрагменту відео {label}. Виділи ключові ідеї, факти, поради. Відповідай українською.\n\nТекст:\n{chunk}"}]
    )
    return r.content[0].text

def final_summary(partials):
    combined = "\n\n---\n\n".join(partials)
    r = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role":"user","content":f"Зроби ОДИН фінальний структурований конспект.\nФормат:\n🎯 Головна тема\n📌 Ключові тези\n💡 Практичні поради\n✅ Висновок\n\nВідповідай українською.\n\n{combined}"}]
    )
    return r.content[0].text

async def start(update, context):
    await update.message.reply_text("👋 YouTube Конспектор\n\nСкинь посилання на YouTube відео — зроблю структурований конспект.")

async def handle_message(update, context):
    text = update.message.text.strip()
    video_id = extract_video_id(text)
    if not video_id:
        await update.message.reply_text("❌ Не розпізнав посилання.\nФормат: https://youtu.be/xxxxxxxx")
        return
    msg = await update.message.reply_text("⏳ Отримую транскрипт...")
    try:
        transcript = get_transcript(video_id)
    except Exception as e:
        await msg.edit_text(f"❌ Не вдалося отримати транскрипт:\n{e}")
        return
    await msg.edit_text(f"📝 Транскрипт готовий ({len(transcript.split())} слів). Створюю конспект...")
    try:
        chunks = chunk_text(transcript)
        partials = []
        for i, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                await msg.edit_text(f"🔄 Обробляю частину {i}/{len(chunks)}...")
            partials.append(summarize_chunk(chunk, i, len(chunks)))
        await msg.edit_text("✍️ Формую конспект...")
        summary = final_summary(partials) if len(partials) > 1 else partials[0]
        await msg.edit_text(summary)
    except Exception as e:
        await msg.edit_text(f"❌ Помилка AI: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    main()