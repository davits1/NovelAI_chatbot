import os
import config
import logging
import requests
import re
import zipfile
import io
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# --- CONFIGURACIÓN DESDE config.py ---
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
NOVELAI_API_KEY = config.NOVELAI_API_KEY
MODEL_NAME = config.MODEL_NAME
# Obtenemos BOT_NAME, si no existe usamos "Aura" por defecto
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

# --- FUNCIONES DE MANEJO DE HISTORIAL ---

def get_history_filepath(chat_id: int) -> str:
    """Devuelve la ruta completa al archivo de historial para un chat_id."""
    return os.path.join(config.HISTORY_DIR, f"{chat_id}.log")

def load_and_truncate_history(chat_id: int) -> str:
    """Carga el historial, lo trunca al tamaño máximo, y lo devuelve."""
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            history_text = f.read()
        
        if len(history_text) > config.MAX_PROMPT_CHARS:
            logger.info(f"Historial de {chat_id} truncado (era {len(history_text)} chars)")
            return history_text[-config.MAX_PROMPT_CHARS:]
        
        return history_text
    except FileNotFoundError:
        return ""

def append_to_history(chat_id: int, user_line: str, bot_line: str):
    """Añade las nuevas líneas de diálogo al archivo de historial."""
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(user_line + bot_line)
    except Exception as e:
        logger.error(f"¡Error! No se pudo escribir en el historial {filepath}: {e}")

# --- FUNCIÓN DE GENERACIÓN DE IMAGEN (NOVELAI V4) ---

def generate_image_novelai(prompt_core: str) -> bytes:
    """
    Construye el payload para NovelAI V4, envía la request y extrae la imagen del ZIP.
    Retorna los bytes de la imagen o None si falla.
    """
    # 1. Combinar prompt del bot con los Quality Tags ocultos
    full_prompt = f"{config.DEFAULT_QUALITY_TAGS}, {prompt_core}"
    negative_prompt = config.DEFAULT_NEGATIVE_PROMPT

    # 2. Construir el payload complejo que requiere V4
    # Nota: V4 requiere el prompt tanto en 'input' como dentro de 'parameters.v4_prompt'
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
            # Estructura específica para V4
            "v4_prompt": {
                "caption": {
                    "base_caption": full_prompt,
                    "char_captions": []
                },
                "use_coords": False,
                "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative_prompt,
                    "char_captions": []
                },
                "legacy_uc": False
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {NOVELAI_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "GLM_Telegram_Bot/0.5"
    }

    try:
        logger.info(f"Generando imagen V4 con prompt: {prompt_core[:50]}...")
        response = requests.post(NOVELAI_IMAGE_API_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        # NovelAI devuelve un ZIP (binary)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            # Tomamos el primer archivo dentro del ZIP
            filename = z.namelist()[0]
            return z.read(filename)

    except Exception as e:
        logger.error(f"Error generando imagen: {e}")
        if 'response' in locals():
            logger.error(f"Respuesta API (si existe): {response.text[:200]}")
        return None

# --- COMANDOS DE TELEGRAM ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"{BOT_NAME} v0.5 initialized (Vision Module Online). Conversation history is persistent. Use /reset to clear.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    filepath = get_history_filepath(chat_id)
    try:
        os.remove(filepath)
        await update.message.reply_text("Conversation history cleared. New slate!")
    except FileNotFoundError:
        await update.message.reply_text("No history to clear.")
    except Exception as e:
        logger.error(f"Error al borrar historial: {e}")
        await update.message.reply_text("Error clearing history.")

# --- LÓGICA PRINCIPAL ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # 1. Preparar Prompt de Texto
        loaded_history = load_and_truncate_history(chat_id)
        # Formateamos el System Prompt con el nombre del bot
        current_system_prompt = SYSTEM_PROMPT.format(bot_name=BOT_NAME)
        
        prompt_string = current_system_prompt + loaded_history
        user_line = f"\nUSER: {user_message}"
        prompt_string += user_line + f"\n{BOT_NAME}:"

        # 2. Llamada a API de TEXTO
        headers = {
            'Authorization': f'Bearer {NOVELAI_API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': 'GLM_Telegram_Bot/0.5'
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
            
            # Limpieza de stop sequences
            if cleaned_response.endswith("\nUSER:"):
                cleaned_response = cleaned_response[:-len("\nUSER:")].strip()

            # --- DETECCIÓN DE IMAGEN (INTERCEPT & RENDER) ---
            # Buscamos contenido entre corchetes: [1girl, red hair...]
            image_match = re.search(r"\[(.*?)\]", cleaned_response)

            bot_line_for_history = f"\n{BOT_NAME}: {cleaned_response}"

            if image_match:
                # ¡Encontramos una solicitud de imagen!
                prompt_content = image_match.group(1) # El texto dentro de los corchetes
                
                # Le avisamos a Telegram que estamos "subiendo una foto"
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                
                # Generamos la imagen
                image_bytes = generate_image_novelai(prompt_content)
                
                if image_bytes:
                    # Enviamos SOLO la foto (el texto con los tags queda oculto para el usuario)
                    # Opcional: Podrías mandar el texto que esté FUERA de los corchetes si quisieras
                    # Pero en este diseño, asumimos que si hay corchetes, es un mensaje de "toma la foto".
                    
                    # Extraer texto amigable si existe (lo que está antes de los corchetes)
                    # Ejemplo: "Here is your selfie! [tags...]" -> manda "Here is your selfie!" como caption
                    caption_text = cleaned_response.replace(f"[{prompt_content}]", "").strip()
                    if len(caption_text) > 1000: caption_text = caption_text[:1000] # Límite de caption de Telegram
                    
                    await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption_text)
                else:
                    await update.message.reply_text("(Me falló la cámara... intenté generar la imagen pero algo salió mal con la API).")
            else:
                # Respuesta de texto normal
                await update.message.reply_text(cleaned_response)

            # Guardamos SIEMPRE la respuesta completa (con corchetes) en el historial
            # para que el bot recuerde que generó la imagen y con qué tags.
            append_to_history(chat_id, user_line, bot_line_for_history)

        else:
            await update.message.reply_text("...")

    except Exception as e:
        logger.exception(f"Error general: {e}")
        await update.message.reply_text("Error processing request.")

def main() -> None:
    if not TELEGRAM_TOKEN or not NOVELAI_API_KEY:
        raise ValueError("TELEGRAM_TOKEN y NOVELAI_API_KEY deben estar definidos en config.py!")
    
    try:
        os.makedirs(config.HISTORY_DIR, exist_ok=True)
    except Exception as e:
        raise RuntimeError(f"No se pudo crear directorio de historial: {e}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"Bot {BOT_NAME} v0.5 starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main()