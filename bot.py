import os
import base64
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import gspread
from google.oauth2.service_account import Credentials
import anthropic

# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')

# Categories for expense tracking
CATEGORIES = [
    "🍔 Food & Dining",
    "🚗 Transportation",
    "🛍️ Shopping",
    "🏠 Bills & Utilities",
    "💊 Healthcare",
    "🎬 Entertainment",
    "✈️ Travel",
    "🎓 Education",
    "💰 Investments",
    "🎁 Gifts",
    "👕 Clothing",
    "🏋️ Fitness",
    "💻 Technology",
    "🔧 Maintenance",
    "📱 Subscriptions",
    "🍺 Social",
    "🐕 Pets",
    "📚 Books",
    "💇 Personal Care",
    "🎮 Gaming",
    "☕ Coffee/Drinks",
    "🏪 Groceries",
    "⛽ Fuel",
    "🅿️ Parking",
    "🚕 Ride-sharing",
    "📦 Delivery",
    "💳 Others"
]

# Initialize Google Sheets
def init_google_sheets():
    """Initialize Google Sheets connection"""
    scope = ['https://www.googleapis.com/auth/spreadsheets', 
             'https://www.googleapis.com/auth/drive']
    
    # Load credentials from environment variable (JSON string)
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)

# Get or create monthly worksheet
def get_or_create_monthly_worksheet(sheet, date_str=None):
    """Get or create worksheet for the current month"""
    if date_str:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    else:
        date_obj = datetime.now()
    
    month_name = date_obj.strftime('%Y-%m %B')
    
    try:
        worksheet = sheet.worksheet(month_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=month_name, rows=1000, cols=10)
        headers = ['Date', 'Time', 'Merchant', 'Category', 'Amount', 'Currency', 'Payment Method', 'Description', 'Logged At']
        worksheet.append_row(headers)
        worksheet.format('A1:I1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.29, 'green': 0.53, 'blue': 0.91},
            'horizontalAlignment': 'CENTER'
        })
        worksheet.freeze(rows=1)
    
    return worksheet

# Archive old worksheet
def archive_worksheet(sheet, worksheet_title):
    """Move a worksheet to archived status by renaming with [ARCHIVED] prefix"""
    try:
        worksheet = sheet.worksheet(worksheet_title)
        if worksheet_title.startswith('[ARCHIVED]'):
            return True
        new_title = f"[ARCHIVED] {worksheet_title}"
        worksheet.update_title(new_title)
        worksheets = sheet.worksheets()
        worksheet.update_index(len(worksheets))
        return True
    except Exception as e:
        print(f"Error archiving worksheet: {e}")
        return False

# Extract transaction details using Claude API
async def extract_transaction_from_image(image_bytes):
    """Use Claude to extract transaction details from screenshot"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    image_type = "image/png"
    if image_bytes[:2] == b'\xff\xd8':
        image_type = "image/jpeg"
    
    prompt = f"""Analyze this transaction screenshot and extract the following information in JSON format:

{{
  "amount": "the transaction amount (number only, e.g., 45.50)",
  "currency": "MYR or other currency code",
  "merchant": "merchant/store name",
  "date": "transaction date in YYYY-MM-DD format (if visible, otherwise use today's date)",
  "time": "transaction time if visible (HH:MM format), otherwise empty string",
  "payment_method": "payment method (e.g., Apple Pay, Touch n Go, GrabPay, Credit Card, etc.)",
  "category": "suggested category from this list: {', '.join(CATEGORIES)}",
  "description": "brief description or any additional details visible"
}}

Return ONLY the JSON, no other text."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": image_base64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    
    response_text = message.content[0].text
    if response_text.strip().startswith('```'):
        response_text = response_text.strip().replace('```json', '').replace('```', '').strip()
    
    return json.loads(response_text)

# Log to Google Sheets
def log_to_sheets(sheet, data):
    """Add transaction to Google Sheets (monthly tab)"""
    date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
    worksheet = get_or_create_monthly_worksheet(sheet, date_str)
    row = [
        data.get('date', datetime.now().strftime('%Y-%m-%d')),
        data.get('time', ''),
        data.get('merchant', ''),
        data.get('category', ''),
        float(data.get('amount', 0)),
        data.get('currency', 'MYR'),
        data.get('payment_method', ''),
        data.get('description', ''),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ]
    worksheet.append_row(row)

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_message = """
👋 Welcome to Expense Tracker Bot!

📸 Send me a screenshot of your transaction (Apple Pay, Touch n Go, GrabPay, etc.) and I'll automatically:
✅ Extract the transaction details
✅ Let you confirm/edit the information
✅ Log it to your Google Sheet (organized by month!)

🔧 Commands:
/start - Show this welcome message
/stats - View spending statistics for current month
/archive - Archive current month after review
/months - List all monthly sheets
/categories - View all available categories
/help - Get help

📅 Each month gets its own tab automatically!
Just send a screenshot to get started! 💰
"""
    await update.message.reply_text(welcome_message)

async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available categories"""
    categories_text = "📋 Available Categories:\n\n" + "\n".join(CATEGORIES)
    await update.message.reply_text(categories_text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle received photos/screenshots"""
    await update.message.reply_text("📸 Processing your screenshot... Please wait.")
    
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        transaction_data = await extract_transaction_from_image(bytes(image_bytes))
        
        if 'error' in transaction_data:
            await update.message.reply_text(f"❌ {transaction_data['error']}\n\nPlease send a clear screenshot of your transaction.")
            return
        
        context.user_data['pending_transaction'] = transaction_data
        
        confirmation_text = f"""
✅ Transaction Details Extracted:

💰 Amount: {transaction_data.get('currency', 'MYR')} {transaction_data.get('amount', 0)}
🏪 Merchant: {transaction_data.get('merchant', 'Unknown')}
📅 Date: {transaction_data.get('date', 'N/A')}
⏰ Time: {transaction_data.get('time', 'N/A')}
💳 Payment: {transaction_data.get('payment_method', 'N/A')}
📂 Category: {transaction_data.get('category', 'Others')}
📝 Description: {transaction_data.get('description', 'N/A')}

Is this correct?
"""
        
        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Save", callback_data='confirm'), InlineKeyboardButton("✏️ Edit Category", callback_data='edit_category')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing image: {str(e)}\n\nPlease try again with a clearer screenshot.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm':
        try:
            transaction_data = context.user_data.get('pending_transaction')
            if not transaction_data:
                await query.edit_message_text("❌ No pending transaction found. Please send a screenshot again.")
                return
            
            sheet = init_google_sheets()
            log_to_sheets(sheet, transaction_data)
            await query.edit_message_text(f"✅ Transaction saved successfully!\n\n💰 {transaction_data.get('currency', 'MYR')} {transaction_data.get('amount', 0)} at {transaction_data.get('merchant', 'Unknown')}")
            context.user_data.pop('pending_transaction', None)
        except Exception as e:
            await query.edit_message_text(f"❌ Error saving to Google Sheets: {str(e)}")
    
    elif query.data == 'archive_confirm':
        try:
            month_to_archive = context.user_data.get('archive_month')
            summary = context.user_data.get('archive_summary', {})
            if not month_to_archive:
                await query.edit_message_text("❌ No month selected for archiving.")
                return
            sheet = init_google_sheets()
            success = archive_worksheet(sheet, month_to_archive)
            if success:
                await query.edit_message_text(f"✅ Successfully archived {month_to_archive}!\n\n📊 Final Summary:\n• Transactions: {summary.get('count', 0)}\n• Total: MYR {summary.get('total', 0):.2f}\n\nThe tab has been renamed to '[ARCHIVED] {month_to_archive}' and moved to the end of your sheets.")
            else:
                await query.edit_message_text("❌ Failed to archive the month. Please try again.")
            context.user_data.pop('archive_month', None)
            context.user_data.pop('archive_summary', None)
        except Exception as e:
            await query.edit_message_text(f"❌ Error archiving: {str(e)}")
    
    elif query.data == 'archive_cancel':
        context.user_data.pop('archive_month', None)
        context.user_data.pop('archive_summary', None)
        await query.edit_message_text("❌ Archive cancelled.")
    
    elif query.data == 'edit_category':
        keyboard = []
        for i in range(0, len(CATEGORIES), 2):
            row = [InlineKeyboardButton(CATEGORIES[i], callback_data=f'cat_{i}')]
            if i + 1 < len(CATEGORIES):
                row.append(InlineKeyboardButton(CATEGORIES[i+1], callback_data=f'cat_{i+1}'))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='back_to_confirm')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📂 Select a category:", reply_markup=reply_markup)
    
    elif query.data.startswith('cat_'):
        category_index = int(query.data.split('_')[1])
        selected_category = CATEGORIES[category_index]
        if 'pending_transaction' in context.user_data:
            context.user_data['pending_transaction']['category'] = selected_category
        transaction_data = context.user_data.get('pending_transaction', {})
        confirmation_text = f"""
✅ Transaction Details (Category Updated):

💰 Amount: {transaction_data.get('currency', 'MYR')} {transaction_data.get('amount', 0)}
🏪 Merchant: {transaction_data.get('merchant', 'Unknown')}
📅 Date: {transaction_data.get('date', 'N/A')}
⏰ Time: {transaction_data.get('time', 'N/A')}
💳 Payment: {transaction_data.get('payment_method', 'N/A')}
📂 Category: {transaction_data.get('category', 'Others')}
📝 Description: {transaction_data.get('description', 'N/A')}

Is this correct?
"""
        keyboard = [[InlineKeyboardButton("✅ Confirm & Save", callback_data='confirm'), InlineKeyboardButton("✏️ Edit Category", callback_data='edit_category')], [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(confirmation_text, reply_markup=reply_markup)
    
    elif query.data == 'cancel':
        context.user_data.pop('pending_transaction', None)
        await query.edit_message_text("❌ Transaction cancelled.")
    
    elif query.data == 'back_to_confirm':
        transaction_data = context.user_data.get('pending_transaction', {})
        confirmation_text = f"""
✅ Transaction Details:

💰 Amount: {transaction_data.get('currency', 'MYR')} {transaction_data.get('amount', 0)}
🏪 Merchant: {transaction_data.get('merchant', 'Unknown')}
📅 Date: {transaction_data.get('date', 'N/A')}
⏰ Time: {transaction_data.get('time', 'N/A')}
💳 Payment: {transaction_data.get('payment_method', 'N/A')}
📂 Category: {transaction_data.get('category', 'Others')}
📝 Description: {transaction_data.get('description', 'N/A')}

Is this correct?
"""
        keyboard = [[InlineKeyboardButton("✅ Confirm & Save", callback_data='confirm'), InlineKeyboardButton("✏️ Edit Category", callback_data='edit_category')], [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(confirmation_text, reply_markup=reply_markup)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show spending statistics"""
    try:
        sheet = init_google_sheets()
        current_month = datetime.now().strftime('%Y-%m %B')
        try:
            worksheet = sheet.worksheet(current_month)
            records = worksheet.get_all_records()
        except gspread.exceptions.WorksheetNotFound:
            await update.message.reply_text(f"📊 No expenses recorded for {current_month} yet!")
            return
        if not records:
            await update.message.reply_text(f"📊 No expenses recorded for {current_month} yet!")
            return
        total = sum(float(record.get('Amount', 0)) for record in records)
        count = len(records)
        avg = total / count if count > 0 else 0
        category_totals = {}
        for record in records:
            cat = record.get('Category', 'Others')
            amt = float(record.get('Amount', 0))
            category_totals[cat] = category_totals.get(cat, 0) + amt
        sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:5]
        stats_text = f"""
📊 Your Spending Statistics ({current_month})

💰 Total Spent: MYR {total:.2f}
📝 Total Transactions: {count}
📊 Average per Transaction: MYR {avg:.2f}

🔝 Top 5 Categories:
"""
        for i, (cat, amt) in enumerate(sorted_categories, 1):
            percentage = (amt / total * 100) if total > 0 else 0
            stats_text += f"\n{i}. {cat}: MYR {amt:.2f} ({percentage:.1f}%)"
        stats_text += f"\n\n💡 Use /archive to archive this month after review"
        await update.message.reply_text(stats_text)
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching statistics: {str(e)}")

async def archive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Archive the current month after confirmation"""
    try:
        sheet = init_google_sheets()
        current_month = datetime.now().strftime('%Y-%m %B')
        try:
            worksheet = sheet.worksheet(current_month)
        except gspread.exceptions.WorksheetNotFound:
            await update.message.reply_text(f"❌ No worksheet found for {current_month}")
            return
        records = worksheet.get_all_records()
        total = sum(float(record.get('Amount', 0)) for record in records)
        count = len(records)
        context.user_data['archive_month'] = current_month
        context.user_data['archive_summary'] = {'total': total, 'count': count}
        confirmation_text = f"""
📦 Archive Month: {current_month}

📊 Summary:
• Total Transactions: {count}
• Total Amount: MYR {total:.2f}

⚠️ This will:
1. Rename the tab to "[ARCHIVED] {current_month}"
2. Move it to the end of your sheets
3. Create a new tab for the current month

Are you sure you want to archive this month?
"""
        keyboard = [[InlineKeyboardButton("✅ Yes, Archive", callback_data='archive_confirm'), InlineKeyboardButton("❌ Cancel", callback_data='archive_cancel')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_months_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all monthly worksheets"""
    try:
        sheet = init_google_sheets()
        worksheets = sheet.worksheets()
        active_months = []
        archived_months = []
        for ws in worksheets:
            title = ws.title
            if title.startswith('[ARCHIVED]'):
                archived_months.append(title.replace('[ARCHIVED] ', ''))
            elif not title in ['Dashboard', 'Summary', 'Template']:
                active_months.append(title)
        message = "📅 Your Expense Sheets:\n\n"
        if active_months:
            message += "✅ Active Months:\n"
            for month in active_months:
                message += f"  • {month}\n"
        if archived_months:
            message += "\n📦 Archived Months:\n"
            for month in archived_months:
                message += f"  • {month}\n"
        if not active_months and not archived_months:
            message += "No expense sheets found yet!"
        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    help_text = """
ℹ️ How to use Expense Tracker Bot:

1️⃣ Take a screenshot of your transaction (Apple Pay, e-wallet, etc.)
2️⃣ Send the screenshot to this bot
3️⃣ Review the extracted details
4️⃣ Confirm or edit the category
5️⃣ Save to Google Sheets!

📅 Monthly Organization:
• Each month gets its own tab automatically
• Format: "2025-01 January", "2025-02 February", etc.
• At month end, use /archive to archive the month
• Archived tabs are renamed "[ARCHIVED] 2025-01 January"

💡 Tips:
• Make sure the screenshot is clear and readable
• Amount, merchant, and date should be visible
• Works with Apple Pay, Touch n Go, GrabPay, Boost, and more!

🔧 Commands:
/start - Welcome message
/stats - View current month statistics
/archive - Archive current month (after review)
/months - List all monthly sheets
/categories - View all categories
/help - Show this help message

🔄 Monthly Workflow:
1. Track expenses throughout the month
2. At month end, review with /stats
3. Verify calculations in Google Sheets
4. Run /archive to archive the month
5. Next expense auto-creates new month tab!

Need support? Contact your bot administrator.
"""
    await update.message.reply_text(help_text)

def main():
    """Start the bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("archive", archive_command))
    application.add_handler(CommandHandler("months", list_months_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("🤖 Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
