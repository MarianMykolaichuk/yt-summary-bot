import os
import re
import anthropic
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

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
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["uk","ru","en"])
    except NoTranscriptFound:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcripts)).fetch()
    return " ".join(t["text"] for t in transcript)

def chunk_text(text, chunk_size=6000):
    words = text.split()
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

def summarize_chunk(chunk, chunk_num, total):
    label = f"(частина {chunk_num}/{total})" if total > 1 else ""
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        messages=[{"role":"user","content":f"Зроби стислий конспект цього фрагменту відео {label}. Виділи ключові ідеї, факти, поради. Відповідай українською.\n\nТекст:\n{chunk}"}]
    )
    return response.content[0].text

def final_summary(partials):
    combined = "\n\n---\n\n".join(partials)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role":"user","content":f"Зроби ОДИН фінальний структурований конспект.\nФормат:\n🎯 *Головна тема*\n📌 *Ключові тези*\n💡 *Практичні поради*\n✅ *Висновок*\n\nВідповідай українською. Markdown.\n\n{combined}"}]
    )
    return response.content[0].text

async def start(update, context):
    await update.message.reply_text(
        "👋 *YouTube Конспектор*\n\nСкинь посилання на YouTube відео — зроблю структурований конспект.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def handle_message(update, context):
    text = update.message.text.strip()
    video_id = extract_video_id(text)
    if not video_id:
        await update.message.reply_text("❌ Не розпізнав посилання. Надішли у форматі:\nhttps://youtu.be/xxxxxxxx")
        return
    msg = await update.message.reply_text("⏳ Отримую транскрипт...")
    try:
        transcript = get_transcript(video_id)
    except TranscriptsDisabled:
        await msg.edit_text("❌ Субтитри вимкнені для цього відео.")
        return
    except Exception as e:
        await msg.edit_text(f"❌ Не вдалося отримати транскрипт: {e}")
        return
    word_count = len(transcript.split())
    await msg.edit_text(f"📝 Транскрипт отримано ({word_count} слів). Створюю конспект...")
    try:
        chunks = chunk_text(transcript)
        partials = []
        for i, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                await msg.edit_text(f"🔄 Обробляю частину {i}/{len(chunks)}...")
            partials.append(summarize_chunk(chunk, i, len(chunks)))
        await msg.edit_text("✍️ Формую фінальний конспект...")
        summary = final_summary(partials) if len(partials) > 1 else partials[0]
        await msg.edit_text(summary, parse_mode=constants.ParseMode.MARKDOWN)
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