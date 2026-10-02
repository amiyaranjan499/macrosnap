# 🥗 MacroSnap

**Snap it. Track it. Get the results sent to you.**

MacroSnap is a Streamlit chat app that estimates the calories and macros (protein, carbs, fat) of your meals from a photo or a text description. When you finish logging your day, it sends a one-message summary to your **WhatsApp**, **Email** or **Telegram**.

## Features

- 📸 Upload a meal photo (JPG/PNG) or type what you ate
- 🔥 Get estimated calories, protein, carbs and fat in seconds
- 💬 Chat memory: the app remembers every meal logged in the session
- 📤 One-click daily summary sent to your chosen channel:
  - WhatsApp (via Twilio)
  - Email (via Gmail SMTP)
  - Telegram (via a bot)
- ⚡ Photos are resized and compressed before upload for faster replies

## Tech stack

- [Streamlit](https://streamlit.io/): web UI
- [Google Gemini](https://ai.google.dev/) (`google-genai`): image and text analysis
- [Twilio](https://www.twilio.com/): WhatsApp delivery
- `smtplib`: Gmail delivery
- [python-telegram-bot](https://python-telegram-bot.org/): Telegram delivery
- Pillow: image resizing

## Project structure

```
macrosnap/
├── app.py                  # Streamlit app (UI, Gemini calls, delivery channels)
├── prompts.py              # System prompt, welcome message, summary prompt
├── requirements.txt        # Python dependencies
└── .streamlit/
    └── secrets.toml        # API keys (never commit this file)
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
streamlit
google-genai
twilio
pillow
python-telegram-bot
```

### 2. Get your keys

You need a **Gemini key** plus the keys for **at least one** delivery channel.

#### Gemini (required)

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Click **Create API key** and copy it.

#### Email (Gmail)

1. Sign in to the Gmail account you want to send from.
2. Turn on **2-Step Verification** in your Google account security settings.
3. Create an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
4. Copy the 16-character password (remove the spaces).

Use the App Password, not your real Gmail password.

#### Telegram

1. In Telegram, message **@BotFather** and send `/newbot`.
2. Choose a name and a username ending in `bot`, then copy the **bot token**.
3. Open your new bot and send it any message (the bot can only message people who have messaged it first).
4. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
5. Find `"chat":{"id":123456789,...}`. That number is your **chat ID**.

#### WhatsApp (Twilio)

1. Create a Twilio account and open the WhatsApp sandbox (Messaging → Try it out → Send a WhatsApp message).
2. From your phone, send the `join ...` code to the sandbox number.
3. In **Messaging → Content Template Builder**, create a template with two variables: `{{1}}` for the name and `{{2}}` for the summary. Copy its **Content SID** (starts with `HX`).
4. Copy your **Account SID** and **Auth Token** from the Twilio console.

### 3. Add your secrets

Create `.streamlit/secrets.toml` and fill in only the channels you use:

```toml
GEMINI_API_KEY = "your-gemini-key"

# WhatsApp (Twilio)
TWILIO_ACCOUNT_SID = "AC..."
TWILIO_AUTH_TOKEN = "..."
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
TWILIO_CONTENT_SID = "HX..."

# Email (Gmail)
GMAIL_ADDRESS = "yourname@gmail.com"
GMAIL_APP_PASSWORD = "abcdefghijklmnop"

# Telegram
TELEGRAM_BOT_TOKEN = "123456:ABC-your-token"
```

> ⚠️ Never share this file or upload it to GitHub. Add `.streamlit/secrets.toml` to your `.gitignore`.

### 4. Run the app

```bash
streamlit run app.py
```

Streamlit reads secrets at startup, so restart the app after editing `secrets.toml`.

## How to use

1. **Choose a channel**: WhatsApp, Email or Telegram.
2. **Enter your details**: your name, plus your WhatsApp number with country code (`+91XXXXXXXXXX`), your email address, or your Telegram chat ID.
3. Click **Let's go 🚀**.
4. **Log meals**: attach a meal photo or type a description (for example, "2 chapati and dal").
5. Keep adding meals through the day.
6. Click **Send to WhatsApp / Email / Telegram**. MacroSnap summarizes everything and sends it in one message.

Notes:

- The send button turns on after you have sent at least one message.
- Meal history lives in the browser session. Refreshing the page starts over.
- Calories and macros are **estimates**, not exact values.

## Configuration

| Setting | Where | Description |
|---|---|---|
| `MODEL_NAME` | `app.py` | Gemini model used for analysis |
| `max_output_tokens` | `app.py` | Caps reply length (default 500) for faster answers |
| `max_side` | `shrink_image()` in `app.py` | Max photo size in pixels before upload (default 768) |
| Prompts | `prompts.py` | System prompt, welcome message and summary prompt |

## Troubleshooting

| Problem | Fix |
|---|---|
| `KeyError: st.secrets has no key ...` | The key name in `secrets.toml` is misspelled, or the file is not inside the `.streamlit` folder |
| `No module named ...` | Run `pip install -r requirements.txt` |
| `ImportError ... circular import` | `prompts.py` must only define the three text variables and must not import from `prompts` or `app` |
| `429 RESOURCE_EXHAUSTED` | Gemini free-tier daily quota used up. Wait for the reset, switch model, use a key from another project, or enable billing |
| Gmail "Username and Password not accepted" | Use the 16-character App Password and make sure 2-Step Verification is on |
| Telegram "chat not found" or "Forbidden" | Send a message to your bot first and use the chat ID from `getUpdates` |
| WhatsApp message not received | Join the Twilio sandbox from your phone and check the Content SID |

## Limitations

- Nutrition values are AI estimates and are not medical or dietary advice.
- The Gemini free tier has a small daily request limit. Each photo, message and summary request counts as one request.
- WhatsApp template variables cannot contain line breaks, so the summary is sent as a single paragraph.

