import telebot
from telebot import types
import json
from datetime import datetime
from github import Github
import time
import threading
import os

# Environment variables
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')

if not BOT_TOKEN or not GIST_ID or not GITHUB_TOKEN:
    print("❌ Missing environment variables!")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
g = Github(GITHUB_TOKEN)
user_states = {}

def sync_gist():
    """Sync budget data with GitHub Gist"""
    try:
        gist = g.get_gist(GIST_ID)
        content = gist.files['budget.json'].content
        return json.loads(content)
    except Exception as e:
        print(f"Sync error: {e}")
        return {"categories": [], "transactions": [], "income": [], "masterCategories": [], "unallocated": 0}

def update_gist(budget_data):
    """Update Gist with new budget data"""
    try:
        gist = g.get_gist(GIST_ID)
        gist.edit(files={'budget.json': {'content': json.dumps(budget_data, indent=2)}})
        print(f"✅ Synced at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"❌ Sync error: {e}")

def calculate_unallocated(budget):
    """Calculate unallocated funds"""
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    return total_income - total_budgeted

@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add('💸 Add Expense', '💰 Add Income')
    markup.add('📊 Set Budget', '💵 Unallocated')
    markup.add('📈 Dashboard', '🔄 Sync')
    
    bot.send_message(message.chat.id, 
        f"👋 *Budget Tracker Pro*\n\n"
        f"💳 Chat ID: `{message.chat.id}`\n"
        f"☁️ Real-time sync enabled!\n\n"
        f"*Features:*\n"
        f"💸 Add expenses\n"
        f"💰 Add income\n"
        f"📊 Set category budgets\n"
        f"💵 Check unallocated funds\n"
        f"📈 View dashboard\n\n"
        f"🤖 Bot running 24/7 on cloud",
        reply_markup=markup, parse_mode='Markdown')

# ============== SET BUDGET ==============
@bot.message_handler(func=lambda m: m.text == '📊 Set Budget')
def set_budget_start(message):
    budget = sync_gist()
    categories = budget.get('categories', [])
    
    if not categories:
        bot.reply_to(message, "📝 Add categories in web app first!")
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
        f"💵 Unallocated: *${unallocated:.2f}*\n\n"
        f"Select category:",
        reply_markup=markup, parse_mode='Markdown')

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
        f"Current: ${current:.2f}\n"
        f"💵 Available: ${unallocated:.2f}\n\n"
        f"💰 Enter new budget:",
        call.message.chat.id, call.message.id,
        parse_mode='Markdown'
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'set_budget')
def budget_amount_entered(message):
    try:
        amount = float(message.text)
        state = user_states[message.chat.id]
        budget = sync_gist()
        
        for cat in budget['categories']:
            if cat['id'] == state['category_id']:
                cat['budgeted'] = amount
                break
        
        update_gist(budget)
        unallocated = calculate_unallocated(budget)
        
        bot.reply_to(message,
            f"✅ *Budget Updated!*\n\n"
            f"📁 {state['category_name']}\n"
            f"💰 ${amount:.2f}\n"
            f"💵 Unallocated: ${unallocated:.2f}\n\n"
            f"🔄 Synced to web app!",
            parse_mode='Markdown')
        
        del user_states[message.chat.id]
    except ValueError:
        bot.reply_to(message, "❌ Enter valid number")

# ============== UNALLOCATED ==============
@bot.message_handler(func=lambda m: m.text == '💵 Unallocated')
def show_unallocated(message):
    budget = sync_gist()
    
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    unallocated = total_income - total_budgeted
    
    status = "✅" if unallocated >= 0 else "⚠️"
    
    response = (
        f"*Budget Summary*\n\n"
        f"💰 Income: ${total_income:.2f}\n"
        f"📊 Budgeted: ${total_budgeted:.2f}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{status} Unallocated: *${unallocated:.2f}*\n\n"
    )
    
    if unallocated > 0:
        response += "💡 Use 📊 Set Budget to allocate"
    elif unallocated < 0:
        response += "⚠️ Over-budgeted!"
    else:
        response += "✅ Perfectly allocated!"
    
    bot.send_message(message.chat.id, response, parse_mode='Markdown')

# ============== ADD EXPENSE ==============
@bot.message_handler(func=lambda m: m.text == '💸 Add Expense')
def expense(message):
    budget = sync_gist()
    categories = budget.get('categories', [])
    
    if not categories:
        bot.reply_to(message, "📝 Add categories in web app first!")
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
        reply_markup=markup, parse_mode='Markdown')

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
            f"💰 Enter amount:",
            call.message.chat.id, call.message.id,
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
        bot.reply_to(message, f"💰 ${amount:.2f}\n\n📝 Description:")
    except ValueError:
        bot.reply_to(message, "❌ Enter valid number")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'expense' and user_states[m.chat.id].get('step') == 'description')
def expense_complete(message):
    state = user_states[message.chat.id]
    budget = sync_gist()
    
    transaction = {
        "id": int(time.time() * 1000),
        "payee": message.text,
        "categoryId": state['category_id'],
        "amount": state['amount'],
        "date": datetime.now().strftime('%Y-%m-%d')
    }
    
    budget['transactions'].append(transaction)
    
    for cat in budget['categories']:
        if cat['id'] == state['category_id']:
            cat['activity'] = (cat.get('activity', 0) or 0) - state['amount']
            available = (cat.get('budgeted', 0) or 0) + cat['activity']
            break
    
    update_gist(budget)
    
    bot.reply_to(message, 
        f"✅ *Expense Added!*\n\n"
        f"📁 {state['category_name']}\n"
        f"💰 ${state['amount']:.2f}\n"
        f"📝 {message.text}\n"
        f"💵 Left: ${available:.2f}\n\n"
        f"🔄 Synced!",
        parse_mode='Markdown')
    
    del user_states[message.chat.id]

# ============== ADD INCOME ==============
@bot.message_handler(func=lambda m: m.text == '💰 Add Income')
def income_start(message):
    user_states[message.chat.id] = {'action': 'income', 'step': 'amount'}
    bot.send_message(message.chat.id, "💰 *Add Income*\n\n💵 Enter amount:", parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'income' and user_states[m.chat.id].get('step') == 'amount')
def income_amount(message):
    try:
        amount = float(message.text)
        state = user_states[message.chat.id]
        state['amount'] = amount
        state['step'] = 'description'
        bot.reply_to(message, f"💰 ${amount:.2f}\n\n📝 Description:")
    except ValueError:
        bot.reply_to(message, "❌ Enter valid number")

@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id].get('action') == 'income' and user_states[m.chat.id].get('step') == 'description')
def income_complete(message):
    state = user_states[message.chat.id]
    budget = sync_gist()
    
    income_entry = {
        "id": int(time.time() * 1000),
        "amount": state['amount'],
        "description": message.text,
        "date": datetime.now().strftime('%Y-%m-%d')
    }
    
    budget['income'].append(income_entry)
    update_gist(budget)
    
    unallocated = calculate_unallocated(budget)
    
    bot.reply_to(message,
        f"✅ *Income Added!*\n\n"
        f"💰 ${state['amount']:.2f}\n"
        f"📝 {message.text}\n"
        f"💵 Unallocated: ${unallocated:.2f}\n\n"
        f"💡 Use 📊 Set Budget\n"
        f"🔄 Synced!",
        parse_mode='Markdown')
    
    del user_states[message.chat.id]

# ============== DASHBOARD ==============
@bot.message_handler(func=lambda m: m.text == '📈 Dashboard')
def dashboard(message):
    budget = sync_gist()
    
    total_income = sum(inc.get('amount', 0) for inc in budget.get('income', []))
    total_budgeted = sum(cat.get('budgeted', 0) or 0 for cat in budget.get('categories', []))
    total_spent = sum(t.get('amount', 0) for t in budget.get('transactions', []))
    unallocated = total_income - total_budgeted
    
    cat_summary = "\n*Top Categories:*\n"
    for cat in budget.get('categories', [])[:5]:
        budgeted = cat.get('budgeted', 0) or 0
        activity = cat.get('activity', 0) or 0
        available = budgeted + activity
        status = "✅" if available >= 0 else "⚠️"
        cat_summary += f"{status} {cat['name']}: ${available:.0f}/${budgeted:.0f}\n"
    
    response = (
        f"📈 *Dashboard*\n\n"
        f"💰 Income: ${total_income:.2f}\n"
        f"📊 Budgeted: ${total_budgeted:.2f}\n"
        f"💸 Spent: ${total_spent:.2f}\n"
        f"💵 Unallocated: ${unallocated:.2f}\n"
        f"{cat_summary}"
    )
    
    bot.send_message(message.chat.id, response, parse_mode='Markdown')

# ============== SYNC ==============
@bot.message_handler(func=lambda m: m.text == '🔄 Sync')
def manual_sync(message):
    budget = sync_gist()
    unallocated = calculate_unallocated(budget)
    bot.reply_to(message, 
        f"✅ *Synced!*\n\n"
        f"💵 Unallocated: ${unallocated:.2f}\n"
        f"📊 Categories: {len(budget.get('categories', []))}\n"
        f"💸 Transactions: {len(budget.get('transactions', []))}",
        parse_mode='Markdown')

def auto_sync():
    """Auto-sync every 60 seconds"""
    while True:
        time.sleep(60)
        try:
            sync_gist()
        except:
            pass

threading.Thread(target=auto_sync, daemon=True).start()

print("🚀 Budget Bot running 24/7!")
print(f"📊 Gist: {GIST_ID[:10]}...")
print(f"⏰ Auto-sync: Every 60s")
bot.infinity_polling()
