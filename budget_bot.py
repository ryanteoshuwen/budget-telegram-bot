import telebot
from telebot import types
import json
from datetime import datetime
from github import Github
import time
import threading
import os
from flask import Flask
from github import InputFileContent 

# ===== ENVIRONMENT VARIABLES (FOR DEPLOYMENT) =====
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://your-app.vercel.app')
PORT = int(os.environ.get('PORT', 10000))
# ==================================================

if not BOT_TOKEN or not GIST_ID or not GITHUB_TOKEN:
    print("❌ ERROR: Missing required environment variables!")
    print("Required: BOT_TOKEN, GIST_ID, GITHUB_TOKEN")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}
budget_data = None

# Category structure - will be loaded from Gist
CATEGORIES = {}

def load_budget_from_gist():
    """Load budget data from GitHub Gist"""
    global budget_data, CATEGORIES
    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        response = requests.get(f'https://api.github.com/gists/{GIST_ID}', headers=headers)
        
        if response.status_code == 200:
            gist_data = response.json()
            budget_json = gist_data['files']['budget.json']['content']
            budget_data = json.loads(budget_json)
            
            # Ensure activityLog exists
            if 'activityLog' not in budget_data:
                budget_data['activityLog'] = []
            
            # Build categories dynamically from budget data
            CATEGORIES = {}
            for master_cat in budget_data.get('masterCategories', []):
                subcategories = [
                    cat['name'] for cat in budget_data.get('categories', [])
                    if cat.get('group') == master_cat['id']
                ]
                CATEGORIES[master_cat['id']] = {
                    'name': f"{master_cat.get('icon', '📁')} {master_cat['name']}",
                    'subcategories': subcategories
                }
            
            print(f"✅ Budget data loaded: {len(budget_data.get('categories', []))} categories, {len(budget_data.get('transactions', []))} transactions, {len(budget_data.get('activityLog', []))} activities")
            return True
        else:
            print(f"❌ Failed to load from Gist: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error loading from Gist: {e}")
        return False

def save_budget_to_gist():
    """Save budget data to GitHub Gist"""
    global budget_data
    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'description': 'Budget Tracker Data - Full Sync',
            'files': {
                'budget.json': {
                    'content': json.dumps(budget_data, indent=2)
                }
            }
        }
        
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers=headers,
            data=json.dumps(payload)
        )
        
        if response.status_code == 200:
            print("✅ Budget data saved to Gist (including activityLog)")
            return True
        else:
            print(f"❌ Failed to save to Gist: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error saving to Gist: {e}")
        return False

def auto_sync_thread():
    """Background thread to sync data every 60 seconds"""
    while True:
        time.sleep(60)
        print("🔄 Auto-syncing from Gist...")
        load_budget_from_gist()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton('💸 Add Expense'),
        types.KeyboardButton('💰 Add Income'),
        types.KeyboardButton('📊 Analytics'),
        types.KeyboardButton('📱 Open App')
    )
    
    bot.reply_to(message, 
        f"👋 *Welcome to Budget Tracker Pro!*\n\n"
        f"📱 Your Chat ID: `{message.chat.id}`\n"
        f"_(Use this in web app settings)_\n\n"
        f"🆕 *Features:*\n"
        f"• Real-time sync via GitHub Gist\n"
        f"• Activity Log support (web app)\n"
        f"• Add expenses/income on-the-go\n"
        f"• Full analytics\n\n"
        f"Choose an option below:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['expense'])
def start_expense(message):
    load_budget_from_gist()
    
    if not CATEGORIES:
        bot.reply_to(message, "⚠️ No categories found. Please set up categories in the web app first.")
        return
    
    user_states[message.chat.id] = {'action': 'expense', 'step': 'master_category'}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat_id, cat_data in CATEGORIES.items():
        markup.add(types.InlineKeyboardButton(
            cat_data['name'], 
            callback_data=f'master_{cat_id}'
        ))
    
    bot.reply_to(message, 
        "💸 *Add Expense*\n\nSelect master category:",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('master_'))
def master_category_selected(call):
    chat_id = call.message.chat.id
    master_cat_id = call.data.replace('master_', '')
    
    if chat_id in user_states and user_states[chat_id]['action'] == 'expense':
        user_states[chat_id]['master_category'] = master_cat_id
        user_states[chat_id]['step'] = 'subcategory'
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        subcategories = CATEGORIES[master_cat_id]['subcategories']
        
        if not subcategories:
            bot.answer_callback_query(call.id, "⚠️ No subcategories in this group")
            return
        
        for subcat in subcategories:
            markup.add(types.InlineKeyboardButton(
                subcat, 
                callback_data=f'subcat_{subcat}'
            ))
        
        bot.edit_message_text(
            f"✅ {CATEGORIES[master_cat_id]['name']}\n\nSelect subcategory:",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('subcat_'))
def subcategory_selected(call):
    chat_id = call.message.chat.id
    subcategory = call.data.replace('subcat_', '')
    
    if chat_id in user_states and user_states[chat_id]['action'] == 'expense':
        user_states[chat_id]['category'] = subcategory
        user_states[chat_id]['step'] = 'amount'
        
        bot.edit_message_text(
            f"✅ Category: *{subcategory}*\n\nEnter amount (e.g., 25.50):",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode='Markdown'
        )
        bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.chat.id in user_states)
def handle_user_input(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)
    
    if not state:
        return
    
    if state['action'] == 'expense':
        if state['step'] == 'amount':
            try:
                amount = float(message.text.replace('$', '').replace(',', ''))
                if amount <= 0:
                    bot.reply_to(message, "❌ Amount must be greater than zero")
                    return
                
                state['amount'] = amount
                state['step'] = 'description'
                bot.reply_to(message, 
                    f"💰 Amount: ${amount:.2f}\n\nEnter description (e.g., 'Starbucks coffee'):"
                )
            except ValueError:
                bot.reply_to(message, "❌ Please enter a valid number (e.g., 25.50)")
        
        elif state['step'] == 'description':
            description = message.text
            category_name = state['category']
            amount = state['amount']
            
            # Load latest data
            load_budget_from_gist()
            
            # Find category ID
            category = next((c for c in budget_data['categories'] if c['name'] == category_name), None)
            
            if not category:
                bot.reply_to(message, "❌ Category not found. Please try again.")
                del user_states[chat_id]
                return
            
            # Add transaction
            transaction = {
                'id': int(time.time() * 1000),
                'payee': description,
                'categoryId': category['id'],
                'amount': amount,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            budget_data['transactions'].append(transaction)
            
            # Update category activity
            category['activity'] = (category.get('activity', 0) or 0) - amount
            
            # ✅ Log to activityLog (for web app Activity Log)
            if 'activityLog' not in budget_data:
                budget_data['activityLog'] = []
            budget_data['activityLog'].append({
                'id': transaction['id'],
                'type': 'expense',
                'date': transaction['date'],
                'payee': description,
                'categoryId': category['id'],
                'amount': amount
            })
            
            # Save to Gist
            if save_budget_to_gist():
                bot.reply_to(message, 
                    f"✅ *Expense Added Successfully!*\n\n"
                    f"💰 Amount: ${amount:.2f}\n"
                    f"📁 Category: {category_name}\n"
                    f"📝 Description: {description}\n"
                    f"📅 Date: {transaction['date']}\n\n"
                    f"🔄 Synced to cloud (Activity Log updated)\n"
                    f"📱 Open web app to see in Activity Log\n\n"
                    f"[Open App]({WEBAPP_URL})",
                    parse_mode='Markdown'
                )
            else:
                bot.reply_to(message, "❌ Failed to sync. Please try again.")
            
            del user_states[chat_id]
    
    elif state['action'] == 'income':
        if state['step'] == 'amount':
            try:
                amount = float(message.text.replace('$', '').replace(',', ''))
                if amount <= 0:
                    bot.reply_to(message, "❌ Amount must be greater than zero")
                    return
                
                state['amount'] = amount
                state['step'] = 'description'
                bot.reply_to(message, 
                    f"💰 Amount: ${amount:.2f}\n\nEnter description (e.g., 'Monthly salary'):"
                )
            except ValueError:
                bot.reply_to(message, "❌ Please enter a valid number")
        
        elif state['step'] == 'description':
            description = message.text
            amount = state['amount']
            
            # Load latest data
            load_budget_from_gist()
            
            # Add income
            income = {
                'id': int(time.time() * 1000),
                'amount': amount,
                'description': description,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            budget_data['income'].append(income)
            
            # ✅ Log to activityLog (for web app Activity Log)
            if 'activityLog' not in budget_data:
                budget_data['activityLog'] = []
            budget_data['activityLog'].append({
                'id': income['id'],
                'type': 'income',
                'date': income['date'],
                'amount': amount,
                'description': description
            })
            
            # Save to Gist
            if save_budget_to_gist():
                bot.reply_to(message, 
                    f"✅ *Income Added Successfully!*\n\n"
                    f"💰 Amount: ${amount:.2f}\n"
                    f"📝 Description: {description}\n"
                    f"📅 Date: {income['date']}\n\n"
                    f"🔄 Synced to cloud (Activity Log updated)\n"
                    f"📱 *To Be Budgeted: ${amount:.2f}*\n\n"
                    f"[Open App]({WEBAPP_URL})",
                    parse_mode='Markdown'
                )
            else:
                bot.reply_to(message, "❌ Failed to sync. Please try again.")
            
            del user_states[chat_id]

@bot.message_handler(commands=['income'])
def start_income(message):
    user_states[message.chat.id] = {'action': 'income', 'step': 'amount'}
    bot.reply_to(message, "💰 *Add Income*\n\nEnter amount:", parse_mode='Markdown')

@bot.message_handler(commands=['analytics', 'summary'])
def show_analytics(message):
    load_budget_from_gist()
    
    if not budget_
        bot.reply_to(message, "⚠️ No data available yet")
        return
    
    # Calculate stats
    total_income = sum(inc.get('amount', 0) for inc in budget_data.get('income', []))
    total_spent = sum(trans.get('amount', 0) for trans in budget_data.get('transactions', []))
    total_budgeted = sum(cat.get('budgeted', 0) for cat in budget_data.get('categories', []))
    to_be_budgeted = total_income - total_budgeted
    
    # Current month spending
    now = datetime.now()
    current_month = f"{now.year}-{now.month:02d}"
    month_transactions = [t for t in budget_data.get('transactions', []) if t.get('date', '').startswith(current_month)]
    month_spending = sum(t.get('amount', 0) for t in month_transactions)
    
    response = (
        f"📊 *Financial Summary*\n\n"
        f"💰 Total Income: ${total_income:.2f}\n"
        f"💸 Total Spent: ${total_spent:.2f}\n"
        f"📅 This Month: ${month_spending:.2f}\n"
        f"🎯 Total Budgeted: ${total_budgeted:.2f}\n"
        f"💎 To Be Budgeted: *${to_be_budgeted:.2f}*\n"
        f"📈 Activities: {len(budget_data.get('activityLog', []))}\n\n"
        f"[View Dashboard]({WEBAPP_URL})"
    )
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['categories'])
def list_categories(message):
    load_budget_from_gist()
    
    categories_text = "📁 *Your Budget Categories*\n\n"
    
    for cat_id, cat_data in CATEGORIES.items():
        categories_text += f"{cat_data['name']}\n"
        for subcat in cat_data['subcategories']:
            categories_text += f"  • {subcat}\n"
        categories_text += "\n"
    
    bot.reply_to(message, categories_text, parse_mode='Markdown')

@bot.message_handler(commands=['sync'])
def force_sync(message):
    bot.reply_to(message, "🔄 Syncing data from cloud...")
    if load_budget_from_gist():
        bot.reply_to(message, 
            f"✅ *Data synced successfully!*\n\n"
            f"📊 Categories: {len(budget_data.get('categories', []))}\n"
            f"💰 Income: ${sum(inc.get('amount', 0) for inc in budget_data.get('income', [])):.2f}\n"
            f"📈 Activities: {len(budget_data.get('activityLog', []))}", 
            parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ Sync failed. Check configuration.")

@bot.message_handler(commands=['help'])
def show_help(message):
    help_text = (
        "🤖 *Budget Tracker Pro Bot Commands*\n\n"
        "*Transaction Management:*\n"
        "/expense - Add expense (interactive)\n"
        "/income - Add income (interactive)\n\n"
        "*Analytics:*\n"
        "/analytics - View financial summary\n"
        "/categories - List all categories\n\n"
        "*Data Management:*\n"
        "/sync - Force sync from cloud\n\n"
        "*Other:*\n"
        "/help - Show this help message\n\n"
        f"[Open Full App]({WEBAPP_URL})"
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')

# Keyboard button handlers
@bot.message_handler(func=lambda message: message.text == '💸 Add Expense')
def expense_button(message):
    start_expense(message)

@bot.message_handler(func=lambda message: message.text == '💰 Add Income')
def income_button(message):
    start_income(message)

@bot.message_handler(func=lambda message: message.text == '📊 Analytics')
def analytics_button(message):
    show_analytics(message)

@bot.message_handler(func=lambda message: message.text == '📱 Open App')
def open_app_button(message):
    bot.reply_to(message, f"🌐 [Open Budget Tracker Pro]({WEBAPP_URL})", parse_mode='Markdown')

# Initialize
print("🔄 Loading initial data from Gist...")
if load_budget_from_gist():
    print("✅ Initial data loaded successfully")
else:
    print("⚠️ Failed to load initial data - will retry")

# Start auto-sync thread
sync_thread = threading.Thread(target=auto_sync_thread, daemon=True)
sync_thread.start()
print("🔄 Auto-sync enabled (every 60 seconds)")

print("\n" + "="*60)
print("✅ Budget Tracker Bot is RUNNING - FULL ACTIVITY LOG SUPPORT")
print("="*60)
print(f"🤖 Bot: @{bot.get_me().username}")
print("📊 Features: Real-time sync + Activity Log + Dynamic categories")
print("🔄 Auto-sync: Every 60 seconds")
print(f"🌍 Webhook Port: {PORT}")
print("="*60 + "\n")

bot.infinity_polling()
