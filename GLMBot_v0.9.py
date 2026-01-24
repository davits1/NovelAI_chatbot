import os
import config
import logging
import requests
import re
import zipfile
import io
import asyncio
from datetime import datetime, timedelta
import time
from telegram import Update
from telegram.request import HTTPXRequest
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

def append_system_message(chat_id: int, message: str):
    """Escribe un mensaje del sistema en el historial sin intervención del usuario."""
    filepath = get_history_filepath(chat_id)
    try:
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(message)
    except Exception as e:
        logger.error(f"¡Error! No se pudo escribir system message en el historial: {e}")

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

# --- SUMMARIZATION FUNCTIONS ---

def get_summary_filepath(chat_id: int) -> str:
    return os.path.join(config.HISTORY_DIR, f"{chat_id}_summary.txt")

def load_summary(chat_id: int) -> str:
    filepath = get_summary_filepath(chat_id)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def save_summary(chat_id: int, summary_text: str):
    filepath = get_summary_filepath(chat_id)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(summary_text)
    except Exception as e:
        logger.error(f"Error saving summary: {e}")

def generate_summary_update(current_summary: str, new_chunk: str) -> str:
    """Invoca a la IA para actualizar el resumen."""
    
    summary_instruction = (
        "You are an objective summarizer. Read the Current Summary (if any) and the New Chat Log.\n"
        "Create an updated, concise summary that incorporates new key details from the log into the existing story/context.\n"
        "Do NOT speak as the bot. Write in third person or a neutral format.\n"
        "Focus on facts, user preferences, and important events.\n"
        "IMPORTANT: Output ONLY the summary text. Do not include introductory phrases like 'Here is the summary'.\n\n"
    )
    
    prompt = f"{summary_instruction}Current Summary:\n{current_summary}\n\nNew Chat Log:\n{new_chunk}\n\nSummary of the storyline so far:\n"
    
    headers = {
        'Authorization': f'Bearer {NOVELAI_API_KEY}',
        'Content-Type': 'application/json',
        'User-Agent': 'GLM_Telegram_Bot/0.8_Summarizer'
    }
    
    # Usamos parámetros alineados con config para evitar problemas de generación vacía
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "temperature": 1.05, # Ligeramente más alto para resumen creativo pero controlado
        "max_tokens": 600,
        "min_length": 20,
        "top_p": config.TOP_P,
        "top_k": config.TOP_K,
        "top_a": config.TOP_A,
        "typical_p": config.TYPICAL_P,
        "tail_free_sampling": config.TAIL_FREE_SAMPLING,
        "repetition_penalty": config.REPETITION_PENALTY,
        "repetition_penalty_range": config.REPETITION_PENALTY_RANGE,
        "repetition_penalty_slope": config.REPETITION_PENALTY_SLOPE,
        "repetition_penalty_frequency": config.REPETITION_PENALTY_FREQUENCY,
        "repetition_penalty_presence": config.REPETITION_PENALTY_PRESENCE,
        "min_p": config.MIN_P,
        "stream": False
    }
    
    logger.info(f"Summary Request Payload: {payload}")
    
    try:
        response = requests.post(NOVELAI_TEXT_API_URL, headers=headers, json=payload, timeout=60)
        
        # Log raw response for debugging
        logger.info(f"Summary Response Status: {response.status_code}")
        logger.info(f"Summary Response Content: {response.text}")
        
        response.raise_for_status()
        data = response.json()
        if data.get('choices'):
            result = data['choices'][0].get('text').strip()
            if not result:
                logger.warning("Summary generation returned empty string.")
                return None
            logger.info(f"Summary generation successful. Result length: {len(result)}")
            return result
        else:
            logger.error(f"Summary generation failed: No choices in response. Data: {data}")
            return None
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return None
    
    return None

def check_and_summarize_history(chat_id: int):
    """Verifica la longitud del historial y resume si es necesario."""
    if not getattr(config, 'SUMMARY_THRESHOLD', None): return
    
    history_path = get_history_filepath(chat_id)
    try:
        # Loop para reducir hasta que estemos bajo el umbral
        while True:
            with open(history_path, 'r', encoding='utf-8') as f:
                full_history = f.read()
                
            if len(full_history) <= config.SUMMARY_THRESHOLD:
                break # Ya estamos bien
                
            logger.info(f"Chat {chat_id} (len {len(full_history)}) > threshold {config.SUMMARY_THRESHOLD}. Summarizing chunk...")
            
            # 1. Definir el chunk a cortar
            chunk_size = config.SUMMARY_CHUNK_SIZE
            # Intentamos cortar en un salto de línea para no romper mensajes
            split_index = full_history.find('\n', chunk_size)
            if split_index == -1: # Si no encuentra salto cerca, corta a saco
                split_index = chunk_size
                
            chunk_to_summarize = full_history[:split_index]
            remaining_history = full_history[split_index:].strip()
            
            # 2. Generar resumen con retries
            current_summary = load_summary(chat_id)
            logger.info(f"Generating summary for chunk of size {len(chunk_to_summarize)}...")
            
            new_summary = None
            max_retries = 3
            for attempt in range(max_retries):
                new_summary = generate_summary_update(current_summary, chunk_to_summarize)
                if new_summary:
                    break
                logger.warning(f"Summary attempt {attempt + 1}/{max_retries} failed. Retrying in 2s...")
                time.sleep(2)
            
            # 3. Guardar cambios
            if new_summary and new_summary != current_summary:
                save_summary(chat_id, new_summary)
                
                # Sobrescribimos el log con lo que queda
                with open(history_path, 'w', encoding='utf-8') as f:
                    f.write(remaining_history)
                
                logger.info(f"Summarization iteration complete for {chat_id}. History shortened.")
            else:
                logger.warning("Summary generation failed after all retries or returned no change. Breaking loop to prevent infinite cycle.")
                break
            
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"Error in auto-summarization logic: {e}")

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

async def spontaneous_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not getattr(config, 'SPONTANEOUS_MESSAGES_ENABLED', False): return

    threshold = getattr(config, 'SPONTANEOUS_INACTIVITY_THRESHOLD', 7200)
    history_dir = config.HISTORY_DIR
    
    try:
        # Iterar sobre archivos .log en el directorio de historial
        for filename in os.listdir(history_dir):
            if not filename.endswith(".log"): continue
            
            filepath = os.path.join(history_dir, filename)
            
            # Extraer chat_id del nombre de archivo
            try:
                chat_id = int(filename.split('.')[0])
            except ValueError:
                continue

            # Verificar inactividad
            last_modified = os.path.getmtime(filepath)
            if (time.time() - last_modified) < threshold:
                continue
            
            logger.info(f"Checking spontaneous message for {chat_id} (inactive > {threshold}s)")

            # --- TIME AWARENESS INJECTION ---
            if getattr(config, 'TIME_AWARENESS_ENABLED', False):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                system_note = f"\n[System Note: The current time is {now_str}]"
                append_system_message(chat_id, system_note)
                logger.info(f"Injecting time marker for spontaneous msg in {chat_id}")


            # Leer historial para contexto
            history_text = load_and_truncate_history(chat_id)
            # Verificamos que no sea la IA la última en hablar para no hablarse a sí misma eternamente
            # (Aunque si el usuario no responde, eventualmente querremos un "ping", pero cuidando no spawnear)
            # Una heurística simple: si las últimas líneas son de la IA, quizás esperar más o no enviar.
            # Pero el requisito es "spontaneous message", así que asumimos que quiere romper el silencio.
            
            # Construir prompt especial
            current_system_prompt = SYSTEM_PROMPT.format(bot_name=BOT_NAME)
            summary_text = load_summary(chat_id)
            if summary_text:
                current_system_prompt += f"\n\n[Previous Conversation Summary:\n{summary_text}\n]"
            
            spontaneous_instruction = (
                f"\n[System Instruction: The user has been silent for a while. "
                f"Send a brief, spontaneous message to check in, share a thought, or send a photo based on the context. "
                f"Do not repeat previous goodbyes. Act naturally as {BOT_NAME}.]"
            )
            
            prompt_string = current_system_prompt + history_text + spontaneous_instruction + f"\n{BOT_NAME}:"

            # Generar respuesta
            headers = {
                'Authorization': f'Bearer {NOVELAI_API_KEY}',
                'Content-Type': 'application/json',
                'User-Agent': 'GLM_Telegram_Bot/0.8_Spontaneous'
            }
            payload = {
                "model": MODEL_NAME,
                "prompt": prompt_string,
                "temperature": 1.1, # Un poco más creativo
                "max_tokens": 150,  # Mensajes cortos
                "min_length": 5,
                "top_p": config.TOP_P,
                "stop": config.STOP_SEQUENCES,
                "stream": False
            }

            response = requests.post(NOVELAI_TEXT_API_URL, headers=headers, json=payload, timeout=60)
            if response.status_code != 200:
                logger.error(f"Failed to generate spontaneous message: {response.text}")
                continue
                
            data = response.json()
            if not data.get('choices'): continue
            
            generated_text = data['choices'][0].get('text').strip()
            if not generated_text: continue
            
            # Enviar mensaje
            logger.info(f"Sending spontaneous message to {chat_id}: {generated_text}")
            await context.bot.send_message(chat_id=chat_id, text=generated_text)
            
            # Actualizar historial
            # Es importante actualizar el mtime del archivo para reiniciar el contador de inactividad
            # Al escribir en el archivo, el mtime se actualiza automáticamente.
            bot_line_for_history = f"{spontaneous_instruction}\n{BOT_NAME}: {generated_text}"
            # Nota: Agregamos la instrucción al log para que la IA sepa por qué habló de la nada la próxima vez?
            # O mejor, solo fingimos que la IA habló. 
            # Si logueamos la instrucción de sistema, ensuciamos el log. 
            # Mejor loguear solo lo que dijo la IA, como si fuera una continuación natural.
            bot_line_real = f"\n{BOT_NAME}: {generated_text}"
            append_to_history(chat_id, "", bot_line_real)

    except Exception as e:
        logger.exception(f"Error in spontaneous_message_job: {e}")


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
        # --- TIME AWARENESS LOGIC ---
        if getattr(config, 'TIME_AWARENESS_ENABLED', False):
            filepath = get_history_filepath(chat_id)
            if os.path.exists(filepath):
                last_modified = os.path.getmtime(filepath)
                current_time = time.time()
                elapsed_seconds = current_time - last_modified
                elapsed_minutes = elapsed_seconds / 60

                threshold = getattr(config, 'TIME_AWARENESS_THRESHOLD_MINUTES', 30)
                
                logger.info(f"Time Check for {chat_id}: Elapsed {elapsed_minutes:.2f}m (Threshold {threshold}m)")

                if elapsed_minutes >= threshold:
                    # Han pasado muchas horas, inyectamos timestamp
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    system_note = f"\n[System Note: The current time is {now_str}]"
                    append_system_message(chat_id, system_note)
                    logger.info(f"Injecting time marker for chat {chat_id}: {system_note}")
                    
                    # Debug: Verify write
                    if not os.path.exists(filepath):
                        logger.error(f"File vanished?? {filepath}")
                    else:
                        mtime_after = os.path.getmtime(filepath)
                        logger.info(f"Timestamp injected. New mtime: {mtime_after} (Was {last_modified})")
        
        # --- AUTO-SUMMARIZATION CHECK ---
        check_and_summarize_history(chat_id)

        loaded_history = load_and_truncate_history(chat_id)
        current_system_prompt = SYSTEM_PROMPT.format(bot_name=BOT_NAME)
        
        # Inyectar resumen si existe
        summary_text = load_summary(chat_id)
        if summary_text:
            current_system_prompt += f"\n\n[Previous Conversation Summary:\n{summary_text}\n]"
        
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
            "min_length": config.MIN_LENGTH,
            "top_k": config.TOP_K,
            "top_a": config.TOP_A,
            "typical_p": config.TYPICAL_P,
            "tail_free_sampling": config.TAIL_FREE_SAMPLING,
            "repetition_penalty": config.REPETITION_PENALTY,
            "repetition_penalty_range": config.REPETITION_PENALTY_RANGE,
            "repetition_penalty_slope": config.REPETITION_PENALTY_SLOPE,
            "repetition_penalty_frequency": config.REPETITION_PENALTY_FREQUENCY,
            "repetition_penalty_presence": config.REPETITION_PENALTY_PRESENCE,
            "min_p": config.MIN_P,
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
            # Combinamos los del config con reglas locales más estrictas (como "USER:" pegado sin espacio)
            hallucination_markers = config.STOP_SEQUENCES + ["USER:", "USER :"]
            
            for marker in hallucination_markers:
                if marker in cleaned_response:
                    logger.warning(f"¡Alucinación detectada! Cortando respuesta en '{marker}'")
                    # Cortamos todo desde el marcador en adelante
                    cleaned_response = cleaned_response.split(marker)[0].strip()
                    # Rompemos el ciclo porque ya cortamos lo más importante
                    break
            
            # --- FIN DE LA GUILLOTINA ---

            # Guardamos la versión "sanitizada" en el historial ANTES de enviar
            # para evitar pérdida de datos si falla el envío (timeout, etc.)
            bot_line_for_history = f"\n{BOT_NAME}: {cleaned_response}"
            append_to_history(chat_id, user_line, bot_line_for_history)

            # Lógica de Split (Multimensaje)
            split_pattern = f"\n{BOT_NAME}:"
            parts = cleaned_response.split(split_pattern)

            for i, part in enumerate(parts):
                part = part.strip()
                if not part: continue

                if i > 0:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                    await asyncio.sleep(1.5)

                try:
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
                except Exception as e:
                    logger.error(f"Error sending message part: {e}")
                    # Intento de enviar mensaje de error al usuario si falla foto
                    try:
                        await update.message.reply_text(f"[Error sending content: {e}]")
                    except:
                        pass

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
    
    # Configurar timeouts más largos para evitar errores al subir fotos
    request = HTTPXRequest(connection_pool_size=8, read_timeout=60, write_timeout=60, connect_timeout=60)
    application = Application.builder().token(TELEGRAM_TOKEN).request(request).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Register Spontaneous Message Job
    if application.job_queue and getattr(config, 'SPONTANEOUS_MESSAGES_ENABLED', False):
        interval = getattr(config, 'SPONTANEOUS_CHECK_INTERVAL', 3600)
        application.job_queue.run_repeating(spontaneous_message_job, interval=interval, first=30)
        logger.info(f"Spontaneous messaging enabled. Checking every {interval}s.")

    
    logger.info(f"Bot {BOT_NAME} v0.8 starting polling...")
    application.run_polling()

if __name__ == '__main__':
    main()