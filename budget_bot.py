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

# Environment variables for cloud deployment
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
PORT = int(os.environ.get('PORT', 10000))

# Validate environment variables
if not BOT_TOKEN or not GIST_ID or not GITHUB_TOKEN:
    print("❌ ERROR: Missing environment variables!")
    print("Required: BOT_TOKEN, GIST_ID, GITHUB_TOKEN")
    exit(1)

# Initialize bot and GitHub
bot = telebot.TeleBot(BOT_TOKEN)
g = Github(GITHUB_TOKEN)
user_states = {}

# Flask app for Render.com health checks
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Budget Bot is running! 🤖", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    """Run Flask server for health checks"""
    app.run(host='0.0.0.0', port=PORT, debug=False)

def sync_gist():
    """Sync budget data from GitHub Gist"""
    try:
        gist = g.get_gist(GIST_ID)
        content = gist.files['budget.json'].content
        return json.loads(content)
    except Exception as e:
        print(f"❌ Sync error: {e}")
        return {
            "categories": [],
            "transactions": [],
            "income": [],
            "masterCategories": [],
            "unallocated": 0
        }

def update_gist(budget_data):
    """Update GitHub Gist with new budget data"""
    try:
        gist = g.get_gist(GIST_ID)
        
        # Use InputFileContent for existing file
        file_content = InputFileContent(
            content=json.dumps(budget_data, indent=2)
        )
        
        # Update the budget.json file
        gist.edit(
            files={
                'budget.json': file_content
            }
        )
        
        print(f"✅ Synced to Gist at {datetime.now().strftime('%H:%M:%S')}")
        return True
    except Exception as e:
        print(f"❌ Gist update error: {e}")
        return False

def calculate_unallocated(budget):
    """Calculate unallocated funds"""
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    return total_income - total_budgeted

# ============== START COMMAND ==============
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add('💸 Add Expense', '💰 Add Income')
    markup.add('📊 Set Budget', '💵 Unallocated')
    markup.add('📈 Dashboard', '🔄 Sync')
    
    bot.send_message(message.chat.id,
        f"👋 *Welcome to Budget Tracker Pro!*\n\n"
        f"💳 Your Chat ID: `{message.chat.id}`\n"
        f"☁️ Real-time sync enabled\n"
        f"🤖 Running 24/7 on cloud\n\n"
        f"*Quick Start:*\n"
        f"1️⃣ Add Income (💰)\n"
        f"2️⃣ Set Budgets (📊)\n"
        f"3️⃣ Track Expenses (💸)\n\n"
        f"All changes sync to your web app instantly!",
        reply_markup=markup,
        parse_mode='Markdown')

# ============== SET BUDGET ==============
@bot.message_handler(func=lambda m: m.text == '📊 Set Budget')
def set_budget_start(message):
    budget = sync_gist()
    categories = budget.get('categories', [])
    
    if not categories:
        bot.reply_to(message, "📝 Please add categories in your web app first!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat in categories:
        current_budgeted = cat.get('budgeted', 0) or 0
        markup.add(types.InlineKeyboardButton(
            f"{cat['name']} (${current_budgeted:.0f})",
            callback_data=f'budget_{cat["id"]}'
        ))
    
    unallocated = calculate_unallocated(budget)
    
    bot.send_message(message.chat.id,
        f"📊 *Set Category Budgets*\n\n"
        f"💵 Available to allocate: *${unallocated:.2f}*\n\n"
        f"Select a category:",
        reply_markup=markup,
        parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('budget_'))
def budget_category_selected(call):
    cat_id = int(call.data.split('_')[1])
    budget = sync_gist()
    
    category = next((c for c in budget['categories'] if c['id'] == cat_id), None)
    if not category:
        bot.answer_callback_query(call.id, "❌ Category not found")
        return
    
    user_states[call.message.chat.id] = {
        'action': 'set_budget',
        'category_id': cat_id,
        'category_name': category['name']
    }
    
    current = category.get('budgeted', 0) or 0
    unallocated = calculate_unallocated(budget)
    
    bot.edit_message_text(
        f"📊 *{category['name']}*\n\n"
        f"Current budget: ${current:.2f}\n"
        f"💵 Available to allocate: ${unallocated:.2f}\n\n"
        f"💰 Enter new budget amount:",
        call.message.chat.id,
        call.message.id,
        parse_mode='Markdown'
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'set_budget')
def budget_amount_entered(message):
    try:
        amount = float(message.text)
        state = user_states[message.chat.id]
        budget = sync_gist()
        
        # Update category budget
        for cat in budget['categories']:
            if cat['id'] == state['category_id']:
                cat['budgeted'] = amount
                break
        
        # Save to Gist
        if update_gist(budget):
            unallocated = calculate_unallocated(budget)
            
            bot.reply_to(message,
                f"✅ *Budget Updated!*\n\n"
                f"📁 Category: {state['category_name']}\n"
                f"💰 Budget: ${amount:.2f}\n"
                f"💵 Remaining: ${unallocated:.2f}\n\n"
                f"🔄 Synced to web app!",
                parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Sync failed. Please try again.")
        
        del user_states[message.chat.id]
        
    except ValueError:
        bot.reply_to(message, "❌ Please enter a valid number (e.g., 500)")

# ============== UNALLOCATED ==============
@bot.message_handler(func=lambda m: m.text == '💵 Unallocated')
def show_unallocated(message):
    budget = sync_gist()
    
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    unallocated = total_income - total_budgeted
    
    status = "✅" if unallocated >= 0 else "⚠️"
    
    response = (
        f"💰 *Budget Summary*\n\n"
        f"Total Income: ${total_income:.2f}\n"
        f"Total Budgeted: ${total_budgeted:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{status} Unallocated: *${unallocated:.2f}*\n\n"
    )
    
    if unallocated > 0:
        response += "💡 Tip: Use '📊 Set Budget' to allocate these funds"
    elif unallocated < 0:
        response += "⚠️ Warning: You've over-budgeted!\nReduce budgets or add more income."
    else:
        response += "✅ Perfect! Every dollar is assigned."
    
    bot.send_message(message.chat.id, response, parse_mode='Markdown')

# ============== ADD EXPENSE ==============
@bot.message_handler(func=lambda m: m.text == '💸 Add Expense')
def expense(message):
    budget = sync_gist()
    categories = budget.get('categories', [])
    
    if not categories:
        bot.reply_to(message, "📝 Please add categories in your web app first!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat in categories:
        available = (cat.get('budgeted', 0) or 0) + (cat.get('activity', 0) or 0)
        markup.add(types.InlineKeyboardButton(
            f"{cat['name']} (${available:.0f})",
            callback_data=f'exp_{cat["id"]}'
        ))
    
    user_states[message.chat.id] = {'action': 'expense', 'step': 'category'}
    bot.send_message(message.chat.id,
        "💸 *Add Expense*\n\nSelect category:",
        reply_markup=markup,
        parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('exp_'))
def expense_category(call):
    cat_id = int(call.data.split('_')[1])
    budget = sync_gist()
    category = next((c for c in budget['categories'] if c['id'] == cat_id), None)
    
    if category:
        available = (category.get('budgeted', 0) or 0) + (category.get('activity', 0) or 0)
        
        user_states[call.message.chat.id] = {
            'action': 'expense',
            'category_id': cat_id,
            'category_name': category['name'],
            'step': 'amount'
        }
        
        bot.edit_message_text(
            f"✅ *{category['name']}*\n"
            f"💵 Available: ${available:.2f}\n\n"
            f"💰 Enter expense amount:",
            call.message.chat.id,
            call.message.id,
            parse_mode='Markdown'
        )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'expense' and user_states[m.chat.id].get('step') == 'amount')
def expense_amount(message):
    try:
        amount = float(message.text)
        state = user_states[message.chat.id]
        state['amount'] = amount
        state['step'] = 'description'
        
        bot.reply_to(message, f"💰 ${amount:.2f}\n\n📝 Enter description (e.g., 'Starbucks coffee'):")
    except ValueError:
        bot.reply_to(message, "❌ Please enter a valid number (e.g., 12.50)")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'expense' and user_states[m.chat.id].get('step') == 'description')
def expense_complete(message):
    state = user_states[message.chat.id]
    budget = sync_gist()
    
    # Add transaction
    transaction = {
        "id": int(time.time() * 1000),
        "payee": message.text,
        "categoryId": state['category_id'],
        "amount": state['amount'],
        "date": datetime.now().strftime('%Y-%m-%d')
    }
    
    budget['transactions'].append(transaction)
    
    # Update category activity
    available = 0
    for cat in budget['categories']:
        if cat['id'] == state['category_id']:
            cat['activity'] = (cat.get('activity', 0) or 0) - state['amount']
            available = (cat.get('budgeted', 0) or 0) + cat['activity']
            break
    
    # Save to Gist
    if update_gist(budget):
        status_emoji = "✅" if available >= 0 else "⚠️"
        
        bot.reply_to(message,
            f"✅ *Expense Added!*\n\n"
            f"📁 Category: {state['category_name']}\n"
            f"💰 Amount: ${state['amount']:.2f}\n"
            f"📝 Description: {message.text}\n"
            f"{status_emoji} Remaining: ${available:.2f}\n"
            f"📅 Date: {datetime.now().strftime('%b %d, %Y')}\n\n"
            f"🔄 Synced to web app!",
            parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ Failed to save expense. Please try again.")
    
    del user_states[message.chat.id]

# ============== ADD INCOME ==============
@bot.message_handler(func=lambda m: m.text == '💰 Add Income')
def income_start(message):
    user_states[message.chat.id] = {'action': 'income', 'step': 'amount'}
    bot.send_message(message.chat.id,
        "💰 *Add Income*\n\n💵 Enter income amount:",
        parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'income' and user_states[m.chat.id].get('step') == 'amount')
def income_amount(message):
    try:
        amount = float(message.text)
        state = user_states[message.chat.id]
        state['amount'] = amount
        state['step'] = 'description'
        
        bot.reply_to(message, f"💰 ${amount:.2f}\n\n📝 Enter description (e.g., 'February Salary'):")
    except ValueError:
        bot.reply_to(message, "❌ Please enter a valid number (e.g., 3000)")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'income' and user_states[m.chat.id].get('step') == 'description')
def income_complete(message):
    state = user_states[message.chat.id]
    budget = sync_gist()
    
    # Add income
    income_entry = {
        "id": int(time.time() * 1000),
        "amount": state['amount'],
        "description": message.text,
        "date": datetime.now().strftime('%Y-%m-%d')
    }
    
    budget['income'].append(income_entry)
    
    # Save to Gist
    if update_gist(budget):
        unallocated = calculate_unallocated(budget)
        
        bot.reply_to(message,
            f"✅ *Income Added!*\n\n"
            f"💰 Amount: ${state['amount']:.2f}\n"
            f"📝 Description: {message.text}\n"
            f"📅 Date: {datetime.now().strftime('%b %d, %Y')}\n\n"
            f"💵 Unallocated: ${unallocated:.2f}\n"
            f"💡 Use '📊 Set Budget' to allocate\n\n"
            f"🔄 Synced to web app!",
            parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ Failed to save income. Please try again.")
    
    del user_states[message.chat.id]

# ============== DASHBOARD ==============
@bot.message_handler(func=lambda m: m.text == '📈 Dashboard')
def dashboard(message):
    budget = sync_gist()
    
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    total_spent = sum(t.get('amount', 0) for t in budget.get('transactions', []))
    unallocated = total_income - total_budgeted
    
    # Top 5 categories
    cat_summary = "\n*Top Categories:*\n"
    for cat in budget.get('categories', [])[:5]:
        budgeted = cat.get('budgeted', 0) or 0
        activity = cat.get('activity', 0) or 0
        available = budgeted + activity
        
        if budgeted > 0:
            status = "✅" if available >= 0 else "⚠️"
            cat_summary += f"{status} {cat['name']}: ${available:.0f} / ${budgeted:.0f}\n"
    
    response = (
        f"📈 *Financial Dashboard*\n\n"
        f"💰 Total Income: ${total_income:.2f}\n"
        f"📊 Total Budgeted: ${total_budgeted:.2f}\n"
        f"💸 Total Spent: ${total_spent:.2f}\n"
        f"💵 Unallocated: ${unallocated:.2f}\n"
        f"{cat_summary}"
    )
    
    bot.send_message(message.chat.id, response, parse_mode='Markdown')

# ============== MANUAL SYNC ==============
@bot.message_handler(func=lambda m: m.text == '🔄 Sync')
def manual_sync(message):
    budget = sync_gist()
    unallocated = calculate_unallocated(budget)
    
    bot.reply_to(message,
        f"✅ *Synced Successfully!*\n\n"
        f"💵 Unallocated: ${unallocated:.2f}\n"
        f"📊 Categories: {len(budget.get('categories', []))}\n"
        f"💸 Transactions: {len(budget.get('transactions', []))}\n"
        f"💰 Income entries: {len(budget.get('income', []))}",
        parse_mode='Markdown')

# Auto-sync in background every 60 seconds
def auto_sync_loop():
    """Background sync to keep data fresh"""
    while True:
        time.sleep(60)
        try:
            sync_gist()
            print(f"🔄 Auto-sync completed at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"❌ Auto-sync error: {e}")

# Start background threads
def start_bot():
    """Start bot with Flask and auto-sync"""
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"✅ Flask health server started on port {PORT}")
    
    # Start auto-sync in background
    sync_thread = threading.Thread(target=auto_sync_loop, daemon=True)
    sync_thread.start()
    print("✅ Auto-sync enabled (every 60s)")
    
    # Start bot polling
    print("🚀 Budget Bot is running!")
    print(f"📊 Gist ID: {GIST_ID[:8]}...")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    bot.infinity_polling()

if __name__ == '__main__':
    start_bot()
