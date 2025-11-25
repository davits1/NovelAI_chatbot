import os
import config
import logging
import requests
import re
import zipfile
import io
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# --- CONFIGURACIÓN DESDE config.py ---
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
NOVELAI_API_KEY = config.NOVELAI_API_KEY
MODEL_NAME = config.MODEL_NAME
BOT_NAME = getattr(config, 'BOT_NAME', 'Aura')

NOVELAI_TEXT_API_URL = "https://text.novelai.net/oa/v1/completions"
NOVELAI_IMAGE_API_URL = "https://image.novelai.net/ai/generate-image"

# --- CARGAR SYSTEM PROMPT ---
script_dir = os.path.dirname(os.path.abspath(__file__))
prompt_path = os.path.join(script_dir, config.PROMPT_FILE)

try:
    with open(prompt_path, 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    logging.error(f"¡Error! No se encontró el archivo de prompt en: {prompt_path}")
    SYSTEM_PROMPT = "Hello."

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- FUNCIONES DE HISTORIAL ---

def get_history_filepath(chat_id: int) -> str:
    return os.path.join(config.HISTORY_DIR, f"{chat_id}.log")

def load_and_truncate_history(chat_id: int) -> str:
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            history_text = f.read()
        if len(history_text) > config.MAX_PROMPT_CHARS:
            return history_text[-config.MAX_PROMPT_CHARS:]
        return history_text
    except FileNotFoundError:
        return ""

def append_to_history(chat_id: int, user_line: str, bot_line: str):
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(user_line + bot_line)
    except Exception as e:
        logger.error(f"¡Error! No se pudo escribir en el historial: {e}")

def undo_last_turn(chat_id: int) -> bool:
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        if not content: return False
        last_user_index = content.rfind("\nUSER:")
        if last_user_index == -1: new_content = ""
        else: new_content = content[:last_user_index]
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        logger.error(f"Error en undo: {e}")
        return False

# --- FUNCIÓN DE IMAGEN ---

def generate_image_novelai(prompt_core: str) -> bytes:
    full_prompt = f"{config.DEFAULT_QUALITY_TAGS}, {prompt_core}"
    negative_prompt = config.DEFAULT_NEGATIVE_PROMPT

    payload = {
        "input": full_prompt,
        "model": "nai-diffusion-4-5-full",
        "action": "generate",
        "parameters": {
            "params_version": 3,
            "width": config.IMAGE_WIDTH,
            "height": config.IMAGE_HEIGHT,
            "scale": config.IMAGE_SCALE,
            "sampler": config.IMAGE_SAMPLER,
            "steps": config.IMAGE_STEPS,
            "n_samples": 1,
            "ucPreset": 3,
            "qualityToggle": True,
            "sm": False,
            "sm_dyn": False,
            "dynamic_thresholding": False,
            "controlnet_strength": 1,
            "legacy": False,
            "add_original_image": False,
            "uncond_scale": 1,
            "cfg_rescale": 0,
            "noise_schedule": config.IMAGE_NOISE_SCHEDULE,
            "negative_prompt": negative_prompt,
            "v4_prompt": {
                "caption": {
                    "base_caption": full_prompt, "char_captions": []
                },
                "use_coords": False, "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative_prompt, "char_captions": []
                },
                "legacy_uc": False
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {NOVELAI_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "GLM_Telegram_Bot/0.8"
    }

    try:
        response = requests.post(NOVELAI_IMAGE_API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            filename = z.namelist()[0]
            return z.read(filename)
    except Exception as e:
        logger.error(f"Error generando imagen: {e}")
        return None

# --- COMANDOS Y LÓGICA PRINCIPAL ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"{BOT_NAME} v0.8 Online. 'Impersonation' protection active.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    filepath = get_history_filepath(chat_id)
    try:
        os.remove(filepath)
        await update.message.reply_text("Memory wiped clean.")
    except FileNotFoundError:
        await update.message.reply_text("Nothing to clear.")

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if undo_last_turn(chat_id):
        await update.message.reply_text("⏪ Undo successful. Last interaction forgotten.")
    else:
        await update.message.reply_text("⚠️ Cannot undo.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        loaded_history = load_and_truncate_history(chat_id)
        current_system_prompt = SYSTEM_PROMPT.format(bot_name=BOT_NAME)
        
        prompt_string = current_system_prompt + loaded_history
        user_line = f"\nUSER: {user_message}"
        prompt_string += user_line + f"\n{BOT_NAME}:"

        headers = {
            'Authorization': f'Bearer {NOVELAI_API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': 'GLM_Telegram_Bot/0.8'
        }
        payload = {
            "model": MODEL_NAME,
            "prompt": prompt_string,
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
            "top_p": config.TOP_P,
            "stop": config.STOP_SEQUENCES,
            "stream": False
        }

        response = requests.post(NOVELAI_TEXT_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        raw_response = None
        if data.get('choices'):
            raw_response = data['choices'][0].get('text')

        if raw_response:
            cleaned_response = raw_response.strip()

            # --- LA GUILLOTINA (NUEVO EN v0.8) ---
            # Revisamos si la IA intentó escribir por el usuario.
            # Buscamos variaciones comunes que la IA usa cuando se equivoca.
            hallucination_markers = ["\nUSER:", "\nUser:", "\nuser:", "\nUSER :"]
            
            for marker in hallucination_markers:
                if marker in cleaned_response:
                    logger.warning(f"¡Alucinación detectada! Cortando respuesta en '{marker}'")
                    # Cortamos todo desde el marcador en adelante
                    cleaned_response = cleaned_response.split(marker)[0].strip()
                    # Rompemos el ciclo porque ya cortamos lo más importante
                    break
            
            # --- FIN DE LA GUILLOTINA ---

            # Lógica de Split (Multimensaje)
            split_pattern = f"\n{BOT_NAME}:"
            parts = cleaned_response.split(split_pattern)

            for i, part in enumerate(parts):
                part = part.strip()
                if not part: continue

                if i > 0:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                    await asyncio.sleep(1.5)

                image_match = re.search(r"\[(.*?)\]", part, re.DOTALL)
                
                if image_match:
                    prompt_content = image_match.group(1).replace("\n", " ")
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    image_bytes = generate_image_novelai(prompt_content)
                    
                    if image_bytes:
                        caption_text = part.replace(image_match.group(0), "").strip()
                        if len(caption_text) > 1000: caption_text = caption_text[:1000]
                        await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption_text)
                    else:
                        await update.message.reply_text(part)
                else:
                    await update.message.reply_text(part)

            # Guardamos la versión "sanitizada" (cortada) en el historial.
            bot_line_for_history = f"\n{BOT_NAME}: {cleaned_response}"
            append_to_history(chat_id, user_line, bot_line_for_history)

        else:
            await update.message.reply_text("...")

    except Exception as e:
        logger.exception(f"Error general: {e}")
        await update.message.reply_text("Error processing request.")

def main() -> None:
    if not TELEGRAM_TOKEN or not NOVELAI_API_KEY:
        raise ValueError("Check config.py!")
    try:
        os.makedirs(config.HISTORY_DIR, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"No se pudo crear directorio de historial: {e}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"Bot {BOT_NAME} v0.8 starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main()