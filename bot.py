import os
import logging
import io
import time

# Libraries for Telegram Bot and Audio Processing
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from pydub import AudioSegment
from gtts import gTTS

# --- Configuration & Setup ---

# The bot token must be set in Heroku Config Vars (Settings -> Config Vars)
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration for Languages and Speeds ---

# gTTS supports languages by code (e.g., 'en', 'hi')
VOICE_MAP = {
    'en': {'code': 'en', 'label': 'English', 'flag': '🇺🇸'},
    'hi': {'code': 'hi', 'label': 'Hindi', 'flag': '🇮🇳'},
    'fr': {'code': 'fr', 'label': 'French', 'flag': '🇫🇷'},
    'es': {'code': 'es', 'label': 'Spanish', 'flag': '🇪🇸'},
}

# Speeds available for the user to select. Emojis added for better visual distinction.
SPEED_MAP = {
    '1.0': {'multiplier': 1.0, 'label': '🚶 1x (Normal)'},
    '1.5': {'multiplier': 1.5, 'label': '🏃 1.5x'},
    '2.0': {'multiplier': 2.0, 'label': '💨 2x (Fast)'},
    '2.5': {'multiplier': 2.5, 'label': '🚀 2.5x'},
    '3.0': {'multiplier': 3.0, 'label': '⚡ 3x (Very Fast)'},
}

DEFAULT_LANG_KEY = 'hi'
DEFAULT_SPEED_KEY = '1.0'

# In-memory storage for user settings:
# {chat_id: {'lang_key': 'en', 'lang_code': 'en', 'speed_key': '1.0', 'speed_multiplier': 1.0}}
user_settings = {}

# --- Utility Functions ---

def get_user_settings(chat_id):
    """Retrieves or initializes user settings."""
    if chat_id not in user_settings:
        user_settings[chat_id] = {
            'lang_key': DEFAULT_LANG_KEY, 
            'lang_code': VOICE_MAP[DEFAULT_LANG_KEY]['code'],
            'speed_key': DEFAULT_SPEED_KEY,
            'speed_multiplier': SPEED_MAP[DEFAULT_SPEED_KEY]['multiplier']
        }
    return user_settings[chat_id]

def generate_tts_audio(text, lang_code, speed_multiplier):
    """
    Generates MP3 audio using gTTS, applies speed via FFmpeg's atempo filter, 
    then converts to OGG/Opus in memory for high quality voice notes.
    Requires FFmpeg buildpack on Heroku.
    """
    logger.info(f"Generating TTS for language {lang_code} at {speed_multiplier}x speed.")

    try:
        # 1. Generate audio using gTTS (outputs MP3 format)
        tts = gTTS(text=text, lang=lang_code, slow=False)
        mp3_bytes_io = io.BytesIO()
        tts.write_to_fp(mp3_bytes_io)
        mp3_bytes_io.seek(0)

        # 2. Load audio
        audio = AudioSegment.from_file(mp3_bytes_io, format="mp3")
        
        # Ensure mono channel for voice note compatibility
        audio = audio.set_channels(1)

        # 3. Prepare FFmpeg parameters for export
        export_params = ["-codec:a", "libopus"]
        
        # Use FFmpeg's 'atempo' filter for high-quality speed adjustment 
        if speed_multiplier != 1.0:
            # atempo filter changes the speed without changing the pitch
            export_params.extend(["-filter:a", f"atempo={speed_multiplier}"])


        # 4. Convert to OGG/Opus using the calculated parameters
        ogg_bytes_io = io.BytesIO()
        
        # Export uses the custom FFmpeg parameters
        audio.export(ogg_bytes_io, format="ogg", parameters=export_params)
        ogg_bytes_io.seek(0)
        return ogg_bytes_io

    except Exception as e:
        logger.error(f"Error during audio generation or processing with gTTS/pydub: {e}")
        return None

def split_text(text, max_length=3500):
    """
    Splits a long text into smaller chunks, trying to preserve sentences.
    """
    chunks = []
    text = text.replace('\r', '').replace('\n\n', '\n')

    while len(text) > max_length:
        split_at = -1
        # Try to split at sentence endings first, searching backwards
        for p in ['.', '!', '?']:
            pos = text.rfind(p, 0, max_length)
            if pos != -1:
                split_at = max(split_at, pos)
        
        # If no sentence end, try newline
        if split_at == -1:
            pos = text.rfind('\n', 0, max_length)
            if pos != -1:
                split_at = pos

        # If still no split point, find the last space
        if split_at == -1:
            pos = text.rfind(' ', 0, max_length)
            if pos != -1:
                split_at = pos
        
        # If no natural split point is found, do a hard split
        if split_at == -1:
            split_point = max_length
        else:
            split_point = split_at + 1
        
        chunks.append(text[:split_point])
        text = text[split_point:]
        
    if text.strip():
        chunks.append(text)
        
    return chunks

# --- Dashboard & Menu Generation ---

def get_dashboard_markup(settings) -> InlineKeyboardMarkup:
    """Generates the main settings dashboard keyboard."""
    lang_info = VOICE_MAP[settings['lang_key']]
    speed_label = SPEED_MAP[settings['speed_key']]['label']
    
    keyboard = [
        [InlineKeyboardButton(f"🗣️ Language: {lang_info['flag']} {lang_info['label']}", callback_data='open:lang')],
        [InlineKeyboardButton(f"⏱️ Speed: {speed_label}", callback_data='open:speed')],
        [InlineKeyboardButton("↩️ Back to Chat", callback_data='close:settings')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_language_markup(settings) -> InlineKeyboardMarkup:
    """Generates the language selection menu."""
    keyboard = []
    current_lang_key = settings['lang_key']
    
    for key, info in VOICE_MAP.items():
        label = f"{info['flag']} {info['label']}"
        if key == current_lang_key:
            label = f"✅ {label}"
        keyboard.append(InlineKeyboardButton(label, callback_data=f'set:lang:{key}'))
    
    lang_buttons = [keyboard[i:i + 2] for i in range(0, len(keyboard), 2)]
    lang_buttons.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='open:dashboard')])
    return InlineKeyboardMarkup(lang_buttons)

def get_speed_markup(settings) -> InlineKeyboardMarkup:
    """Generates the speed selection menu."""
    keyboard = []
    current_speed_key = settings['speed_key']
    
    for key, info in SPEED_MAP.items():
        label = info['label']
        if key == current_speed_key:
            label = f"✅ {label}"
        keyboard.append(InlineKeyboardButton(label, callback_data=f'set:speed:{key}'))
    
    speed_buttons = [keyboard[i:i + 3] for i in range(0, len(keyboard), 3)]
    speed_buttons.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='open:dashboard')])
    return InlineKeyboardMarkup(speed_buttons)

# --- Telegram Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message with instructions."""
    settings = get_user_settings(update.effective_chat.id)
    current_language = VOICE_MAP[settings['lang_key']]['label']
    current_speed = SPEED_MAP[settings['speed_key']]['label']

    help_text = (
        "👋 Welcome to the Multi-Language TTS Bot!\n\n"
        "I can convert any text you send me into a voice note.\n\n"
        "📝 <b>How to use me:</b>\n"
        "1. <b>Send a text message</b> (max 4000 characters).\n"
        "2. <b>Upload a <code>.txt</code> file</b> (even large ones are okay!).\n\n"
        "⚙️ <b>Configuration:</b>\n"
        "Use the <code>/settings</code> command to adjust the language and speech pace.\n\n"
        f"🗣️ <b>Current Default Settings:</b> {current_language} at {current_speed}."
    )
    
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Open Settings Dashboard", callback_data='open:dashboard')]])
    await update.message.reply_html(help_text, reply_markup=reply_markup)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Opens the main settings dashboard."""
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    await update.message.reply_text(
        "⚙️ **TTS Settings Dashboard**\n\nChoose an option to modify, or send me text to generate audio.",
        reply_markup=get_dashboard_markup(settings),
        parse_mode='Markdown'
    )

async def process_dashboard_update(query) -> None:
    """Updates the message with the current dashboard view."""
    chat_id = query.message.chat_id
    settings = get_user_settings(chat_id)
    await query.edit_message_text(
        "⚙️ **TTS Settings Dashboard**\n\nChoose an option to modify, or send me text to generate audio.",
        reply_markup=get_dashboard_markup(settings),
        parse_mode='Markdown'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline button presses for navigation and setting updates."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id
    settings = get_user_settings(chat_id)
    action, *params = data.split(':')

    if action == 'open':
        menu_type = params[0]
        if menu_type == 'lang':
            await query.edit_message_text(
                "🗣️ **Language Selection**\n\nChoose the language for the TTS voice:",
                reply_markup=get_language_markup(settings), parse_mode='Markdown'
            )
        elif menu_type == 'speed':
            await query.edit_message_text(
                "⏱️ **Speed Selection**\n\nChoose the pace of speech:",
                reply_markup=get_speed_markup(settings), parse_mode='Markdown'
            )
        elif menu_type == 'dashboard':
            await process_dashboard_update(query)
            
    elif action == 'set':
        setting_type, key = params[0], params[1]
        if setting_type == 'lang':
            settings['lang_key'] = key
            settings['lang_code'] = VOICE_MAP[key]['code']
        elif setting_type == 'speed':
            settings['speed_key'] = key
            settings['speed_multiplier'] = SPEED_MAP[key]['multiplier']
        await process_dashboard_update(query)

    elif action == 'close':
        await query.edit_message_text("Settings closed. I'm ready for your text! ✍️")

async def process_text_and_send_audio(update: Update, text_to_speak: str) -> None:
    """Central function to generate and send audio for short texts."""
    if len(text_to_speak) > 4000:
        await update.message.reply_text("⚠️ Text too long. Truncating to 4000 characters.")
        text_to_speak = text_to_speak[:4000]

    await update.effective_chat.send_chat_action(action="record_voice")
    
    chat_id = update.effective_chat.id
    settings = get_user_settings(chat_id)
    
    ogg_audio_bytes = generate_tts_audio(text_to_speak, settings['lang_code'], settings['speed_multiplier'])

    if ogg_audio_bytes:
        lang_label = VOICE_MAP[settings['lang_key']]['label']
        speed_label = SPEED_MAP[settings['speed_key']]['label']
        audio_file = InputFile(ogg_audio_bytes, filename=f"voice_note_{chat_id}.ogg")
        await update.message.reply_voice(
            voice=audio_file,
            caption=f"🗣️ Spoken in {lang_label} at {speed_label}"
        )
    else:
        await update.message.reply_text(
            "❌ Sorry, I could not generate the audio. Ensure FFmpeg is available and the text is valid."
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming standard text messages."""
    await process_text_and_send_audio(update, update.message.text)

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles .txt files, with support for splitting large text into chunks."""
    doc = update.message.document
    if doc.mime_type != 'text/plain':
        await update.message.reply_text("❌ Please send a plain `.txt` file.")
        return

    file_bytes = io.BytesIO()
    file_obj = await context.bot.get_file(doc.file_id)
    await file_obj.download_to_memory(file_bytes)
    file_bytes.seek(0)

    try:
        text_to_speak = file_bytes.read().decode('utf-8')
        if not text_to_speak.strip():
            await update.message.reply_text("The text file is empty.")
            return

        if len(text_to_speak) <= 4000:
            await process_text_and_send_audio(update, text_to_speak)
            return

        # --- Logic for handling large text files ---
        chat_id = update.effective_chat.id
        settings = get_user_settings(chat_id)
        lang_code = settings['lang_code']
        speed_multiplier = settings['speed_multiplier']

        await update.message.reply_text(f"📝 Large file detected ({len(text_to_speak)} characters). Processing in chunks. This may take a moment...")
        await update.effective_chat.send_chat_action(action="record_voice")

        text_chunks = split_text(text_to_speak)
        combined_audio = AudioSegment.empty()
        
        for i, chunk in enumerate(text_chunks):
            logger.info(f"Processing chunk {i+1}/{len(text_chunks)} for chat {chat_id}")
            if not chunk.strip(): continue
            try:
                tts = gTTS(text=chunk, lang=lang_code, slow=False)
                mp3_bytes_io = io.BytesIO()
                tts.write_to_fp(mp3_bytes_io)
                mp3_bytes_io.seek(0)
                audio_chunk = AudioSegment.from_file(mp3_bytes_io, format="mp3")
                combined_audio += audio_chunk
            except Exception as e:
                logger.error(f"Error processing chunk {i+1}: {e}")
                await update.message.reply_text(f"❌ An error occurred while processing part {i+1}. Aborting.")
                return

        logger.info(f"All chunks processed for chat {chat_id}. Exporting final audio.")
        await update.effective_chat.send_chat_action(action="record_voice")

        if len(combined_audio) == 0:
            await update.message.reply_text("❌ Could not generate any audio from the text.")
            return

        combined_audio = combined_audio.set_channels(1)
        
        export_params = ["-codec:a", "libopus"]
        if speed_multiplier != 1.0:
            export_params.extend(["-filter:a", f"atempo={speed_multiplier}"])

        ogg_bytes_io = io.BytesIO()
        combined_audio.export(ogg_bytes_io, format="ogg", parameters=export_params)
        ogg_bytes_io.seek(0)
        
        lang_label = VOICE_MAP[settings['lang_key']]['label']
        speed_label = SPEED_MAP[settings['speed_key']]['label']
        audio_file = InputFile(ogg_bytes_io, filename=f"voice_note_{chat_id}_combined.ogg")
        await update.message.reply_voice(
            voice=audio_file,
            caption=f"🗣️ Spoken in {lang_label} at {speed_label} ({len(text_chunks)} parts combined)"
        )

    except UnicodeDecodeError:
        await update.message.reply_text("❌ Could not read the file. Please ensure it's a UTF-8 encoded text file.")
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text("❌ An unexpected error occurred while processing the file.")
        
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles unrecognised messages."""
    if update.message:
        await update.message.reply_text("❌ I can only process plain text messages or `.txt` files.")

def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set. The bot cannot start.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("settings", settings_command)) 

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), document_handler))

    application.add_handler(CallbackQueryHandler(button_callback))

    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, fallback_handler))

    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
