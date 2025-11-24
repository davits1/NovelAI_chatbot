import os
import config # ¡NUEVO!
import logging
import requests
# from collections import deque # ¡YA NO SE USA!
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# --- CONFIGURACIÓN DESDE config.py ---
TELEGRAM_TOKEN = config.TELEGRAM_TOKEN
NOVELAI_API_KEY = config.NOVELAI_API_KEY
MODEL_NAME = config.MODEL_NAME
# Intentamos obtener BOT_NAME, si no existe usamos "Aura" por defecto
BOT_NAME = getattr(config, 'BOT_NAME', 'Aura')

NOVELAI_API_URL = "https://text.novelai.net/oa/v1/completions" # Esta la podemos dejar

# --- CARGAR SYSTEM PROMPT ---
# Obtenemos la ruta ABSOLUTA de la carpeta donde está ESTE script (.py)
script_dir = os.path.dirname(os.path.abspath(__file__))
# Unimos esa ruta con el nombre del archivo de prompt
prompt_path = os.path.join(script_dir, config.PROMPT_FILE)

try:
    # Abrimos la ruta completa y absoluta
    with open(prompt_path, 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT = f.read()
except FileNotFoundError:
    # Ahora el error es mucho más claro y te dirá la ruta exacta que falló
    logging.error(f"¡Error! No se encontró el archivo de prompt en: {prompt_path}")
    SYSTEM_PROMPT = "Hello."

# --- ¡LOGICA DE HISTORIAL QUITADA! ---
# MAX_HISTORY_TURNS = 10
# chat_histories = {}
# ¡YA NO SE USAN! El historial ahora es persistente.

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
        
        # Truncamiento: si el historial es más largo que el máximo,
        # nos quedamos solo con los últimos N caracteres.
        if len(history_text) > config.MAX_PROMPT_CHARS:
            logger.info(f"Historial de {chat_id} truncado (era {len(history_text)} chars)")
            return history_text[-config.MAX_PROMPT_CHARS:]
        
        return history_text
    
    except FileNotFoundError:
        # Es un chat nuevo, no hay historial.
        return ""

def append_to_history(chat_id: int, user_line: str, aura_line: str):
    """Añade las nuevas líneas de diálogo al archivo de historial."""
    filepath = get_history_filepath(chat_id)
    try:
        # 'a' (append) para añadir al final del archivo.
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(user_line + aura_line)
    except Exception as e:
        logger.error(f"¡Error! No se pudo escribir en el historial {filepath}: {e}")

# --- COMANDOS DE TELEGRAM (MODIFICADOS) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Ya no necesitamos inicializar el historial en memoria
    await update.message.reply_text(f"{BOT_NAME} initialized. Conversation history is now persistent. Use /reset to clear our conversation.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    filepath = get_history_filepath(chat_id)
    
    try:
        # Intentamos borrar el archivo de historial
        os.remove(filepath)
        await update.message.reply_text("Conversation history cleared. It's like we've never met. 😉")
    except FileNotFoundError:
        await update.message.reply_text("No history to clear. We haven't even talked!")
    except Exception as e:
        logger.error(f"Error al borrar historial {filepath}: {e}")
        await update.message.reply_text("An error occurred while trying to clear the history.")

# --- LÓGICA PRINCIPAL (REHECHA) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_message = update.message.text

    # ¡Ya no se usa el historial en memoria!
    # if chat_id not in chat_histories:
    #     chat_histories[chat_id] = deque(maxlen=MAX_HISTORY_TURNS * 2)

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # --- ¡CAMBIO CLAVE! Construcción del prompt desde el archivo ---
        
        # 1. Cargamos y truncamos el historial guardado
        loaded_history = load_and_truncate_history(chat_id)
        
        # 2. Empezamos con el prompt del sistema y formateamos el nombre
        prompt_string = SYSTEM_PROMPT.format(bot_name=BOT_NAME)
        
        # 3. Agregamos el historial de chat (que ya está formateado)
        prompt_string += loaded_history
            
        # 4. Agregamos el mensaje actual del usuario
        user_line = f"\nUSER: {user_message}"
        prompt_string += user_line
        
        # 5. Le decimos a la IA que es su turno
        prompt_string += f"\n{BOT_NAME}:"
        # -----------------------------------------------------------

        headers = {
            'Authorization': f'Bearer {NOVELAI_API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': 'GLM_Telegram_Bot/1.0'
        }

        # --- El payload ahora usa "prompt" y "stop" ---
        payload = {
            "model": MODEL_NAME, # Ya viene de config
            "prompt": prompt_string, 
            "temperature": config.TEMPERATURE, # ¡NUEVO!
            "max_tokens": config.MAX_TOKENS,   # ¡NUEVO!
            "top_p": config.TOP_P,           # ¡NUEVO!
            "stop": config.STOP_SEQUENCES,   # ¡NUEVO!
            "stream": False
        }
        
        # (Opcional) Loggear el payload puede ser muy largo,
        # mejor loggeamos solo el tamaño.
        logger.info(f"Sending payload ({len(prompt_string)} chars) to NAI for chat {chat_id}")

        response = requests.post(NOVELAI_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Failed to decode JSON from API. Response text: '{response.text}'")
            await update.message.reply_text("I received a garbled response from the API. This might be a temporary issue with NovelAI's servers. Please try again in a moment.")
            return

        logger.info("NovelAI response JSON (snippet): %s", str(data)[:200])

        # --- Lógica de extracción ---
        raw_response = None
        if data.get('choices') and isinstance(data['choices'], list) and len(data['choices']) > 0:
            raw_response = data['choices'][0].get('text')

        if raw_response:
            cleaned_response = raw_response.strip()
            
            # Limpiamos el stop token del final
            if cleaned_response.endswith("\nUSER:"):
                cleaned_response = cleaned_response[:-len("\nUSER:")].strip()
            elif cleaned_response.endswith("\nUSER"):
                cleaned_response = cleaned_response[:-len("\nUSER")].strip()
            
            # --- ¡CAMBIO CLAVE! Guardamos en el archivo ---
            aura_line = f"\n{BOT_NAME}: {cleaned_response}"
            append_to_history(chat_id, user_line, aura_line)
            
            await update.message.reply_text(cleaned_response)
        else:
            logger.info("API returned an empty 'text' field or no choices. Full response: %s", data)
            await update.message.reply_text("I... drew a blank. 😅 The model returned no content. Try rephrasing?")

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err} - {response.text}")
        error_message = f"Ouch. Hit a snag connecting to the API. Status code: {response.status_code}."
        if response.status_code == 401:
            error_message += "\nThe server said 'Unauthorized'. This almost always means the NovelAI API Key is incorrect, expired, or revoked. Please double-check your key or generate a new one in your NovelAI account."
        else:
            try:
                server_msg = response.json().get('message', 'No specific message from server.')
                error_message += f"\nThe server said: '{server_msg}'"
            except ValueError:
                error_message += "\nCould not decode a specific error message from the server."
        await update.message.reply_text(error_message)

    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
        await update.message.reply_text("Well, that wasn't supposed to happen. I've hit a critical error. Please try again later.")

def main() -> None:
    if not TELEGRAM_TOKEN or not NOVELAI_API_KEY:
        raise ValueError("TELEGRAM_TOKEN y NOVELAI_API_KEY deben estar definidos en config.py!")
    
    # --- ¡NUEVO! Crear el directorio de historial si no existe ---
    try:
        os.makedirs(config.HISTORY_DIR, exist_ok=True)
        logger.info(f"Directorio de historial verificado: {config.HISTORY_DIR}")
    except Exception as e:
        raise RuntimeError(f"¡Error fatal! No se pudo crear el directorio de historial: {e}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is starting up...")
    application.run_polling()

if __name__ == '__main__':
    main()
