# NovelAI GLM-4.6 + Image Generation Telegram Bot (v0.9)

A conversational Python bot that brings NovelAI's powerful text and image models to Telegram.

This bot connects to NovelAI's `glm-4-6` text model for chatting and seamlessly integrates with the `nai-diffusion-4-5-full` (V4) image model. It uses an **"Intercept & Render"** logic, allowing the bot to "decide" when to send an image based on the conversation context.

## Features

* **Conversational AI:** Powered by NovelAI's `glm-4-6` model for high-quality roleplay and chat.
* **Visual Capabilities (NEW):** The bot can generate and send images on the fly. When the persona writes a prompt inside `[brackets]`, the bot intercepts it, generates the image using NovelAI's V4 model, and sends it to the chat.
* **Dynamic Identity:** Easily change the bot's name and personality via `config.py` and `prompt.txt`.
* **Spontaneous Messaging (NEW):** The bot can initiate conversation after a period of inactivity, making it feel more alive.
* **Time Awareness (NEW):** The bot is aware of the passage of time and can reference the current time in the conversation context.
* **Auto-Summarization (NEW):** Automatically summarizes long conversations to maintain context without exceeding token limits.
* **Quality Control:** Includes hidden "Quality Tags" and "Negative Prompts" injection to ensure high-quality, aesthetic image outputs automatically.
* **Persistent Memory:** Conversations are stored in local log files so the bot remembers context between restarts.

## Tech Stack

* [Python 3](https://www.python.org/)
* [python-telegram-bot](https://python-telegram-bot.org/)
* [requests](https://requests.readthedocs.io/en/latest/)

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/davits1/novelai_chatbot.git
cd novelai_chatbot
```

### 2. Create a Virtual Environment (Recommended)

```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install python-telegram-bot requests
```

### 4. Configuration

1.  Rename `config.py.template` to `config.py`.
2.  Open `config.py` and paste your **Telegram Token** and **NovelAI API Key**.
3.  (Optional) Adjust the `BOT_NAME`, `DEFAULT_QUALITY_TAGS` (for image style), or the `DEFAULT_NEGATIVE_PROMPT` if you want to filter specific content.

### 5. Customizing the Personality

Edit `prompt.txt` to change how the bot behaves. To enable image generation, ensure your system prompt includes the instructions for the bot to use square brackets (already included in the default system prompt).

**Example Instruction:**

> "If the user asks for a selfie, describe the image inside square brackets like this: [1girl, selfie, smile]"

## Usage

Run the script to start the bot:

```bash
python GLMBot_v0.9.py
```

The bot is now online!

### Commands

* `/start` - Initialize the conversation.
* `/reset` - Delete the conversation history and start fresh.
* `/undo` - Undo the last interaction (remove user message and bot response).
