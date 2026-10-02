
import asyncio
import json
import smtplib
from email.mime.text import MIMEText
from io import BytesIO

import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from twilio.rest import Client as TwilioClient

from prompts import SUMMARY_REQUEST_PROMPT, SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE

MODEL_NAME = "gemini-3.5-flash"  # confirm this model ID is available to your API key
CHANNELS = ["WhatsApp", "Email", "Telegram"]

st.set_page_config(page_title="MacroSnap", page_icon="🥗")


GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_ACCOUNT_SID = st.secrets.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = st.secrets.get("TWILIO_WHATSAPP_FROM")
TWILIO_CONTENT_SID = st.secrets.get("TWILIO_CONTENT_SID")
GMAIL_ADDRESS = st.secrets.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = st.secrets.get("GMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID")


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


gemini_client = get_gemini_client()


# ---------- chat helpers ----------
def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append(
        {"role": role, "kind": kind, "content": content}
    )
    render_message(st.session_state.messages[-1])


def shrink_image(photo_bytes, max_side=768):
    """Resize + compress the photo so it uploads and processes much faster."""
    img = Image.open(BytesIO(photo_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")  # fix phone rotation
    img.thumbnail((max_side, max_side))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def ask_gemini(parts):
    try:
        return st.session_state.chat.send_message(parts).text
    except Exception as error:
        return f"Sorry, something went wrong: {error}"


# ---------- delivery channels ----------
def clean_text(text):
    if not text:
        return "No nutrition summary available."
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text[:1500] + "..." if len(text) > 1500 else text


def whatsapp_address(number):
    number = "".join(number.split())  # remove spaces
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def send_whatsapp(to_number, user_name, summary):
    # Content template expects {{1}} = name, {{2}} = summary.
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_CONTENT_SID]):
        return False, "Twilio keys are missing in .streamlit/secrets.toml"
    try:
        content_variables = json.dumps(
            {"1": user_name, "2": clean_text(summary)}, ensure_ascii=False
        )
        message = get_twilio_client().messages.create(
            from_=whatsapp_address(TWILIO_WHATSAPP_FROM),
            to=whatsapp_address(to_number),
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)


def send_email(to_address, user_name, summary):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return False, "GMAIL_ADDRESS / GMAIL_APP_PASSWORD are missing in secrets.toml"
    try:
        body = f"Hi {user_name},\n\n{clean_text(summary)}\n\n- MacroSnap"
        message = MIMEText(body, "plain", "utf-8")  # utf-8 so emojis work
        message["Subject"] = "Your MacroSnap nutrition summary"
        message["From"] = GMAIL_ADDRESS
        message["To"] = to_address
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(message)
        return True, "sent"
    except Exception as error:
        return False, str(error)


def send_telegram(chat_id, user_name, summary):
    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN is missing in secrets.toml"
    try:
        from telegram import Bot  # imported here so other channels work without it

        text = f"Hi {user_name}! {clean_text(summary)}"
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        asyncio.run(bot.send_message(chat_id=chat_id, text=text))
        return True, "sent"
    except Exception as error:
        return False, str(error)


def send_summary(channel, destination, user_name, summary):
    if channel == "WhatsApp":
        return send_whatsapp(destination, user_name, summary)
    if channel == "Email":
        return send_email(destination, user_name, summary)
    return send_telegram(destination, user_name, summary)


def validate_destination(channel, destination):
    """Return an error message, or None if the value looks fine."""
    if channel == "WhatsApp" and not destination.startswith("+"):
        return "WhatsApp number must start with + and the country code, e.g. +91XXXXXXXXXX."
    if channel == "Email" and ("@" not in destination or "." not in destination):
        return "Please enter a valid email address."
    if channel == "Telegram" and not destination.lstrip("-").isdigit():
        return "Telegram chat ID must be a number."
    return None


FIELD_INFO = {
    "WhatsApp": ("WhatsApp number (with country code)", "+91XXXXXXXXXX",
                 "MacroSnap will text your summary to this number."),
    "Email": ("Email address", "you@example.com",
              "MacroSnap will email your summary to this address."),
    "Telegram": ("Telegram chat ID", "123456789",
                 "Message your bot once first. Then use your numeric chat ID."),
}

# ---------- Step 1: onboarding ----------
if "onboarded" not in st.session_state:
    st.title("🥗 MacroSnap")
    st.caption("Snap it. Track it. Get the results sent to you.")

    # Outside the form so the field label below updates when this changes.
    channel = st.radio("Send my summary via", CHANNELS, horizontal=True)
    label, placeholder, help_text = FIELD_INFO[channel]

    with st.form("onboarding_form"):
        name = st.text_input("Your name")
        destination = st.text_input(label, placeholder=placeholder, help=help_text)
        submitted = st.form_submit_button("Let's go 🚀")

    if submitted:
        if not name.strip() or not destination.strip():
            st.warning("Please fill in both fields.")
        elif validate_destination(channel, destination.strip()):
            st.warning(validate_destination(channel, destination.strip()))
        else:
            st.session_state.name = name.strip()
            st.session_state.channel = channel
            st.session_state.destination = destination.strip()
            st.session_state.chat = gemini_client.chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=500,  # short answers = faster replies
                ),
            )
            st.session_state.messages = []
            st.session_state.onboarded = True
            st.rerun()
    st.stop()

# ---------- Step 2: chat interface ----------
header_col, button_col = st.columns([5, 2], vertical_alignment="center")

with header_col:
    st.title("🥗 MacroSnap")

with button_col:
    send_disabled = not any(m["role"] == "user" for m in st.session_state.messages)
    if st.button(
        f"📤 Send to {st.session_state.channel}",
        disabled=send_disabled,
        use_container_width=True,
    ):
        with st.spinner("Summarizing your day..."):
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT])
        success, info = send_summary(
            st.session_state.channel,
            st.session_state.destination,
            st.session_state.name,
            summary,
        )
        if success:
            st.success(f"Sent! Check your {st.session_state.channel} 📲")
        else:
            st.error(f"Couldn't send that: {info}")

st.caption(
    f"Logged in as {st.session_state.name} - "
    f"updates go to {st.session_state.destination} ({st.session_state.channel})"
)

if not st.session_state.messages:
    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name),
    )
else:
    for message in st.session_state.messages:
        render_message(message)

user_input = st.chat_input(
    "Ask a question, or attach a photo of your meal",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        small_bytes = shrink_image(photo_bytes)
        parts.append(types.Part.from_bytes(data=small_bytes, mime_type="image/jpeg"))

    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("What is this meal? Give me the calories and macros.")

    with st.spinner("Crunching the numbers..."):
        answer = ask_gemini(parts)
    add_message("assistant", "text", answer)
    st.rerun()  