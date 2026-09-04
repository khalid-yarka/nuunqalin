# bot/handlers.py
# Message and callback handlers for telebot

import logging
import telebot
from telebot import types

from bot.utils import (
    is_duplicate_pdf, save_pending_pdf, get_pending_pdfs_count,
    get_pending_pdf_list, is_admin
)

logger = logging.getLogger(__name__)

def handle_start(bot: telebot.TeleBot, message: telebot.types.Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ''
    text = (
        f"👋 Hello {first_name}!\n\n"
        "I am the PDF intake bot for the learning platform.\n"
        "Send me a PDF document and it will be forwarded to the admin for review.\n\n"
        "Commands:\n"
        "/start - Show this message\n"
        "/help - Show help"
    )
    markup = None
    if is_admin(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📚 Pending PDFs", callback_data="pdf_admin_pending"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

def handle_help(bot: telebot.TeleBot, message: telebot.types.Message):
    bot.send_message(
        message.chat.id,
        "📖 Help:\n\n"
        "Send me a PDF document (any file with .pdf extension).\n"
        "I will check if it's already in the system.\n"
        "If it's new, it will be added to the pending queue for admin review.\n\n"
        "Admins: Use the Pending PDFs button to manage uploads."
    )

def handle_document(bot: telebot.TeleBot, message: telebot.types.Message):
    document = message.document
    if not document:
        bot.reply_to(message, "❌ Please send a document file (PDF).")
        return

    if document.mime_type != 'application/pdf' and not document.file_name.endswith('.pdf'):
        bot.reply_to(message, "❌ Only PDF files are accepted.")
        return

    file_id = document.file_id
    file_unique_id = document.file_unique_id
    filename = document.file_name or 'unknown.pdf'
    user_id = message.from_user.id

    if is_duplicate_pdf(file_unique_id):
        bot.reply_to(
            message,
            "⚠️ This PDF is already in the system (either already published or pending review)."
        )
        return

    pending_id = save_pending_pdf(file_id, file_unique_id, filename, user_id)
    if pending_id:
        bot.reply_to(
            message,
            f"✅ PDF received and is pending admin review.\n"
            f"Filename: {filename}\n"
            f"Pending ID: #{pending_id}"
        )
    else:
        bot.reply_to(message, "❌ Failed to save the PDF. Please try again later.")

def handle_admin_pending(bot: telebot.TeleBot, call: telebot.types.CallbackQuery):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "You are not authorized.", show_alert=True)
        return

    bot.answer_callback_query(call.id)

    if call.data == "pdf_admin_pending":
        count = get_pending_pdfs_count()
        pending_list = get_pending_pdf_list(limit=5)
        text = f"📚 Pending PDFs: {count}\n\n"
        if pending_list:
            for p in pending_list:
                text += f"• {p['filename']} (ID: {p['id']}) - uploaded {p['uploaded_at']}\n"
            text += "\nUse the web admin panel to process them.\n"
            text += "Web panel: <your-secret-url> (configured by admin)"
        else:
            text += "No pending PDFs."
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)