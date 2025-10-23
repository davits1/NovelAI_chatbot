# NovelAI GLM-4.6 Telegram Bot

A simple, conversational Python bot that connects Telegram to NovelAI's GLM-4.6 text completion model.

This bot is designed to be a straightforward example of how to interact with NovelAI's OpenAI-compatible API (specifically the `/oa/v1/completions` endpoint) using Python. It uses the `python-telegram-bot` library for the Telegram interface and `requests` for API calls.

## Features

* **Conversational AI:** Connects to NovelAI's powerful `glm-4-6` model.
* **Conversation Memory:** Maintains a rolling in-memory conversation history to provide context for the AI.
* **Customizable Persona:** Easily change the bot's personality by editing the `SYSTEM_PROMPT` variable.
* **Simple Commands:** Includes `/start` and `/reset` commands to manage the conversation flow.

## Tech Stack

* [Python 3](https://www.python.org/)
* [python-telegram-bot](https://python-telegram-bot.org/)
* [requests](https://requests.readthedocs.io/en/latest/)

## Installation & Setup

Follow these steps to get the bot running on your own machine.

### 1. Clone the Repository

```bash
git clone [https://github.com/davits1/novelai_chatbot.git](https://github.com/davits1/novelai_chatbot.git)
cd novelai_chatbot
````

### 2\. Create a Virtual Environment (Recommended)

```bash
# For Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# For macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3\. Install Dependencies

This project requires `python-telegram-bot` and `requests`. You can install them using pip:

```bash
pip install python-telegram-bot requests
```

### 4\. Configuration

You must add your secret tokens to the script before running it.

1.  Open `GLMBot_v0.2.py` in your code editor.

2.  Find the following lines near the top:

    ```python
    # --- CONFIGURACIÓN ---
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PASTE_YOUR_TELEGRAM_TOKEN_HERE")
    NOVELAI_API_KEY = os.getenv("NOVELAI_API_KEY", "PASTE_YOUR_NAI_API_KEY_HERE")
    ```

3.  Replace `"PASTE_YOUR_TELEGRAM_TOKEN_HERE"` with your actual Telegram Bot Token from BotFather.

4.  Replace `"PASTE_YOUR_NAI_API_KEY_HERE"` with your NovelAI Persistent API Key.

**(Optional) Customize Persona:**
You can change the bot's entire personality by editing the `SYSTEM_PROMPT` variable in the same file.

## Usage

Once your virtual environment is activated and your tokens are set, simply run the script:

```bash
python GLMBot_v0.2.py
```

Your bot is now online\! You can interact with it on Telegram.

## License

This project is licensed under the MIT License.

```
```
