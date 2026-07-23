"""
One-time script to authenticate Telethon with your Telegram account.
Run this once, enter your phone number and the code you receive.
After that, paygles_telethon.session file will be created and
the app will use it automatically.

Usage:
    cd backend
    ./paygles-env/bin/python auth_telegram.py
"""
import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient

load_dotenv()

api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
api_hash = os.getenv("TELEGRAM_API_HASH", "")

if not api_id or not api_hash:
    print("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
    exit(1)

client = TelegramClient("paygles_telethon", api_id, api_hash)
client.start()

me = client.get_me()
print(f"\nBasariyla giris yapildi: {me.first_name} (@{me.username})")
print("paygles_telethon.session dosyasi olusturuldu.")
print("Artik bu scripti tekrar calistirmaniza gerek yok.\n")

client.disconnect()
