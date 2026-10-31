
import asyncio
import json
import re
import smtplib
from email.mime.text import MIMEText

import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient
from telegram import Bot

from prompts import (
    SUMMARY_REQUEST_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "gemini-3-flash-preview"

st.set_page_config(
    page_title="MacroSnap",
    page_icon="🥗",
)


from pathlib import Path

css_path = Path(__file__).parent / "style.css"

if css_path.exists():
    with open(css_path, encoding="utf-8") as css_file:
        st.markdown(
            f"<style>{css_file.read()}</style>",
            unsafe_allow_html=True,
        )



GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

TWILIO_ACCOUNT_SID = st.secrets.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = st.secrets.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = st.secrets.get("TWILIO_WHATSAPP_FROM")
TWILIO_CONTENT_SID = st.secrets.get("TWILIO_CONTENT_SID")

GMAIL_ADDRESS = st.secrets.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = st.secrets.get("GMAIL_APP_PASSWORD")

TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN")


if not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY is missing from Streamlit secrets.")
    st.stop()


# ============================================================
# CLIENTS
# ============================================================

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return None

    return TwilioClient(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
    )


gemini_client = get_gemini_client()
twilio_client = get_twilio_client()


def create_chat(model_name=MODEL_NAME):
    return gemini_client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.4,
            max_output_tokens=800,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )


def get_or_create_chat():
    current_model = st.session_state.get("chat_model")
    if "chat" not in st.session_state or current_model != MODEL_NAME:
        st.session_state.chat = create_chat()
        st.session_state.chat_model = MODEL_NAME
    return st.session_state.chat


# ============================================================
# CHAT HELPERS
# ============================================================

def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])

        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    message = {
        "role": role,
        "kind": kind,
        "content": content,
    }

    st.session_state.messages.append(message)
    render_message(message)


def ask_gemini(parts):
    chat = get_or_create_chat()
    try:
        response = chat.send_message(parts)
        answer = response.text or ""
    except Exception as error:
        try:
            fallback_chat = create_chat(model_name="gemini-3.1-flash-lite-preview")
            response = fallback_chat.send_message(parts)
            answer = response.text or ""
            st.session_state.chat = fallback_chat
            st.session_state.chat_model = "gemini-3.1-flash-lite-preview"
        except Exception:
            return "Sorry, I couldn't analyze your meal. Please try again."

    if not answer.strip():
        return "I couldn't generate a response. Please try again."

    # Retry if Gemini only names the food and omits nutrition.
    required = ("calories", "protein", "carbs", "fat")

    if not all(item in answer.lower() for item in required):
        try:
            response = st.session_state.chat.send_message(
                "Your previous answer was incomplete. Finish the meal "
                "analysis. Include estimated calories in kcal, protein in g, "
                "carbs in g, fat in g, and a short note that the values are estimates."
            )
            if response.text and response.text.strip():
                answer = response.text
        except Exception:
            pass

    return answer.strip()


# ============================================================
# MESSAGE FORMATTING
# ============================================================

def clean_message(text, limit=1500):
    if not text:
        return "No nutrition summary available."

    text = " ".join(text.split())

    if len(text) > limit:
        text = text[:limit - 3] + "..."

    return text


def whatsapp_address(number):
    number = number.strip()

    if number.startswith("whatsapp:"):
        return number

    return f"whatsapp:{number}"


# ============================================================
# WHATSAPP DELIVERY
# ============================================================

def send_whatsapp(to_number, user_name, summary):
    if not all([
        twilio_client,
        TWILIO_WHATSAPP_FROM,
        TWILIO_CONTENT_SID,
    ]):
        return False, "WhatsApp configuration is missing from secrets."

    try:
        content_variables = json.dumps(
            {
                "1": user_name,
                "2": clean_message(summary),
            },
            ensure_ascii=False,
        )

        message = twilio_client.messages.create(
            from_=whatsapp_address(TWILIO_WHATSAPP_FROM),
            to=whatsapp_address(to_number),
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )

        return True, message.sid

    except Exception as error:
        return False, str(error)


# ============================================================
# EMAIL DELIVERY
# ============================================================

def send_email(to_address, user_name, summary):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return False, "Gmail settings are missing from Streamlit secrets."

    try:
        body = (
            f"Hi {user_name},\n\n"
            f"Here is your MacroSnap nutrition summary:\n\n"
            f"{clean_message(summary)}\n\n"
            "Remember, nutritional values are estimates.\n\n"
            "- MacroSnap 🥗"
        )

        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = "Your MacroSnap Nutrition Summary 🥗"
        message["From"] = GMAIL_ADDRESS
        message["To"] = to_address

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            timeout=20,
        ) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(message)

        return True, "Email sent successfully."

    except Exception as error:
        return False, str(error)


# ============================================================
# TELEGRAM DELIVERY
# ============================================================

def send_telegram(chat_id, user_name, summary):
    if not TELEGRAM_BOT_TOKEN:
        return False, "TELEGRAM_BOT_TOKEN is missing from secrets."

    try:
        async def deliver():
            bot = Bot(token=TELEGRAM_BOT_TOKEN)

            async with bot:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🥗 MacroSnap Nutrition Summary\n\n"
                        f"Hi {user_name}!\n\n"
                        f"{clean_message(summary)}\n\n"
                        "Nutrition values are estimates."
                    ),
                )

        asyncio.run(deliver())

        return True, "Telegram message sent successfully."

    except Exception as error:
        return False, str(error)


# ============================================================
# SELECTED CHANNEL DELIVERY
# ============================================================

def send_summary(channel, destination, user_name, summary):
    if channel == "WhatsApp":
        return send_whatsapp(
            destination,
            user_name,
            summary,
        )

    if channel == "Email":
        return send_email(
            destination,
            user_name,
            summary,
        )

    if channel == "Telegram":
        return send_telegram(
            destination,
            user_name,
            summary,
        )

    return False, "Unsupported delivery channel."


# ============================================================
# VALIDATION
# ============================================================

def validate_destination(channel, destination):
    destination = destination.strip()

    if channel == "WhatsApp":
        if not re.fullmatch(r"\+[1-9]\d{7,14}", destination):
            return "Enter a valid WhatsApp number, e.g. +91XXXXXXXXXX."

    elif channel == "Email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", destination):
            return "Enter a valid email address."

    elif channel == "Telegram":
        if not re.fullmatch(r"-?\d+", destination):
            return "Enter your numeric Telegram chat ID."

    return None


CHANNELS = ["WhatsApp", "Email", "Telegram"]

FIELD_INFO = {
    "WhatsApp": (
        "WhatsApp number",
        "+91XXXXXXXXXX",
        "Include your country code.",
    ),
    "Email": (
        "Email address",
        "you@example.com",
        "Your summary will be delivered to this email.",
    ),
    "Telegram": (
        "Telegram chat ID",
        "123456789",
        "Start your Telegram bot before sending a message.",
    ),
}


# ============================================================
# STEP 1: ONBOARDING
# ============================================================

if "onboarded" not in st.session_state:
    st.title("🥗 MacroSnap")
    st.caption("Snap it. Track it. Get your nutrition summary.")
    
    st.markdown(
        """
        <div class="macrosnap-banner">
            <div class="food-icons">🥗 🍓 🥑</div>
            <h3>Your personal nutrition buddy</h3>
            <p>
                Share your meal and discover its estimated calories,
                protein, carbs and fat.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


    channel = st.radio(
        "Send my summary via",
        CHANNELS,
        horizontal=True,
    )

    label, placeholder, help_text = FIELD_INFO[channel]

    with st.form("onboarding_form"):
        name = st.text_input("Your name")

        destination = st.text_input(
            label,
            placeholder=placeholder,
            help=help_text,
        )

        submitted = st.form_submit_button("Let's go 🚀")

    if submitted:
        name = name.strip()
        destination = destination.strip()

        if not name or not destination:
            st.warning("Please fill in both fields.")

        else:
            error = validate_destination(channel, destination)

            if error:
                st.warning(error)

            else:
                try:
                    chat = create_chat()

                    st.session_state.name = name
                    st.session_state.channel = channel
                    st.session_state.destination = destination
                    st.session_state.chat = chat
                    st.session_state.chat_model = MODEL_NAME
                    st.session_state.messages = []
                    st.session_state.onboarded = True

                    st.rerun()

                except Exception as error:
                    st.error(f"Could not start Gemini chat: {error}")

    st.stop()


# ============================================================
# STEP 2: CHAT INTERFACE
# ============================================================

header_col, button_col = st.columns(
    [5, 2],
    vertical_alignment="center",
)

with header_col:
    st.title("🥗 MacroSnap")

with button_col:
    has_user_messages = any(
        message["role"] == "user"
        for message in st.session_state.messages
    )

    if st.button(
        f"📤 Send to {st.session_state.channel}",
        disabled=not has_user_messages,
        use_container_width=True,
    ):
        with st.spinner("Summarizing your meals..."):
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT])

        if summary.startswith(("Sorry,", "I couldn't")):
            st.error("Could not generate the summary. Please try again.")

        else:
            with st.spinner(f"Sending via {st.session_state.channel}..."):
                success, info = send_summary(
                    st.session_state.channel,
                    st.session_state.destination,
                    st.session_state.name,
                    summary,
                )

            if success:
                st.success(f"Sent successfully via {st.session_state.channel}! 📲")
            else:
                st.error(f"Message delivery failed: {info}")


st.caption(
    f"Logged in as {st.session_state.name} · "
    f"Delivery: {st.session_state.channel}"
)


with st.expander("Delivery settings"):
    st.write(f"Destination: {st.session_state.destination}")

    if st.button("Start a new session"):
        for key in (
            "onboarded",
            "name",
            "channel",
            "destination",
            "chat",
            "chat_model",
            "messages",
        ):
            st.session_state.pop(key, None)

        st.rerun()


if not st.session_state.messages:
    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(
            name=st.session_state.name
        ),
    )
else:
    for message in st.session_state.messages:
        render_message(message)


# ============================================================
# TEXT AND IMAGE INPUT
# ============================================================

user_input = st.chat_input(
    "Ask a question, or attach a photo of your meal",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = (user_input.text or "").strip()
    parts = []

    if photo is not None:
        try:
            photo_bytes = photo.getvalue()

            from PIL import Image, ImageOps
            from io import BytesIO

            with Image.open(BytesIO(photo_bytes)) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.thumbnail((768, 768))

                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=82)
                small_bytes = buffer.getvalue()

            add_message("user", "image", photo_bytes)

            parts.append(
                types.Part.from_bytes(
                    data=small_bytes,
                    mime_type="image/jpeg",
                )
            )

        except Exception:
            st.error("Could not read the image. Please upload a valid JPG or PNG.")
            st.stop()

    if photo is not None and text:
        add_message("user", "text", text)
        parts.append(
            f"{text}\n\nIdentify this meal and estimate calories, protein, carbs, and fat."
        )

    elif photo is not None:
        parts.append(
            "What is this meal? Give me the calories and macros."
        )

    elif text:
        add_message("user", "text", text)
        parts.append(text)

    if parts:
        with st.spinner("Analyzing your meal..."):
            answer = ask_gemini(parts)

        add_message("assistant", "text", answer)
        st.rerun()
