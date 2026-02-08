import telebot
from telebot import types
import json
import requests
from datetime import datetime
import time
import threading
import os
from flask import Flask, request

# ===== ENVIRONMENT VARIABLES =====
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://your-app.vercel.app')
PORT = int(os.environ.get('PORT', 10000))

if not BOT_TOKEN or not GIST_ID or not GITHUB_TOKEN:
    print("❌ ERROR: Missing environment variables!")
    print("Required: BOT_TOKEN, GIST_ID, GITHUB_TOKEN")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}
budget_data = None
CATEGORIES = {}

def load_budget_from_gist():
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
            
            if 'activityLog' not in budget_
                budget_data['activityLog'] = []
            
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
            
            print(f"✅ Loaded: {len(budget_data.get('categories', []))} cats, {len(budget_data.get('activityLog', []))} activities")
            return True
        else:
            print(f"❌ Gist load failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def save_budget_to_gist():
    global budget_data
    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'description': 'Budget Tracker Data',
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
            print("✅ Saved to Gist")
            return True
        else:
            print(f"❌ Save failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Save error: {e}")
        return False

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
        f"👋 *Budget Tracker Pro*\n\n"
        f"📱 Chat ID: `{message.chat.id}`\n\n"
        f"✅ Activity Log support\n"
        f"✅ Real-time cloud sync",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['expense'])
def start_expense(message):
    load_budget_from_gist()
    
    if not CATEGORIES:
        bot.reply_to(message, "⚠️ Set up categories in web app first")
        return
    
    user_states[message.chat.id] = {'action': 'expense', 'step': 'master_category'}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for cat_id, cat_data in CATEGORIES.items():
        markup.add(types.InlineKeyboardButton(cat_data['name'], callback_data=f'master_{cat_id}'))
    
    bot.reply_to(message, "💸 *Add Expense*\n\nSelect category:", parse_mode='Markdown', reply_markup=markup)

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
            bot.answer_callback_query(call.id, "⚠️ No subcategories")
            return
        
        for subcat in subcategories:
            markup.add(types.InlineKeyboardButton(subcat, callback_data=f'subcat_{subcat}'))
        
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
            f"✅ Category: *{subcategory}*\n\nEnter amount:",
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
                    bot.reply_to(message, "❌ Amount must be > 0")
                    return
                
                state['amount'] = amount
                state['step'] = 'description'
                bot.reply_to(message, f"💰 ${amount:.2f}\n\nEnter description:")
            except ValueError:
                bot.reply_to(message, "❌ Invalid number")
        
        elif state['step'] == 'description':
            description = message.text
            category_name = state['category']
            amount = state['amount']
            
            load_budget_from_gist()
            
            category = next((c for c in budget_data['categories'] if c['name'] == category_name), None)
            
            if not category:
                bot.reply_to(message, "❌ Category not found")
                del user_states[chat_id]
                return
            
            transaction = {
                'id': int(time.time() * 1000),
                'payee': description,
                'categoryId': category['id'],
                'amount': amount,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            budget_data['transactions'].append(transaction)
            category['activity'] = (category.get('activity', 0) or 0) - amount
            
            if 'activityLog' not in budget_
                budget_data['activityLog'] = []
            
            budget_data['activityLog'].append({
                'id': transaction['id'],
                'type': 'expense',
                'date': transaction['date'],
                'payee': description,
                'categoryId': category['id'],
                'amount': amount
            })
            
            if save_budget_to_gist():
                bot.reply_to(message, 
                    f"✅ *Expense Added!*\n\n"
                    f"💰 ${amount:.2f} | {category_name}\n"
                    f"📝 {description}\n"
                    f"🔄 Activity Log synced",
                    parse_mode='Markdown'
                )
            else:
                bot.reply_to(message, "❌ Sync failed")
            
            del user_states[chat_id]
    
    elif state['action'] == 'income':
        if state['step'] == 'amount':
            try:
                amount = float(message.text.replace('$', '').replace(',', ''))
                if amount <= 0:
                    bot.reply_to(message, "❌ Amount must be > 0")
                    return
                
                state['amount'] = amount
                state['step'] = 'description'
                bot.reply_to(message, f"💰 ${amount:.2f}\n\nEnter description:")
            except ValueError:
                bot.reply_to(message, "❌ Invalid number")
        
        elif state['step'] == 'description':
            description = message.text
            amount = state['amount']
            
            load_budget_from_gist()
            
            income = {
                'id': int(time.time() * 1000),
                'amount': amount,
                'description': description,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            
            budget_data['income'].append(income)
            
            if 'activityLog' not in budget_
                budget_data['activityLog'] = []
            
            budget_data['activityLog'].append({
                'id': income['id'],
                'type': 'income',
                'date': income['date'],
                'amount': amount,
                'description': description
            })
            
            if save_budget_to_gist():
                bot.reply_to(message, 
                    f"✅ *Income Added!*\n\n"
                    f"💰 ${amount:.2f}\n"
                    f"📝 {description}\n"
                    f"🔄 Activity Log synced",
                    parse_mode='Markdown'
                )
            else:
                bot.reply_to(message, "❌ Sync failed")
            
            del user_states[chat_id]

@bot.message_handler(commands=['income'])
def start_income(message):
    user_states[message.chat.id] = {'action': 'income', 'step': 'amount'}
    bot.reply_to(message, "💰 *Add Income*\n\nEnter amount:", parse_mode='Markdown')

@bot.message_handler(commands=['analytics'])
def show_analytics(message):
    load_budget_from_gist()
    
    if not budget_
        bot.reply_to(message, "⚠️ No data")
        return
    
    total_income = sum(inc.get('amount', 0) for inc in budget_data.get('income', []))
    total_spent = sum(t.get('amount', 0) for t in budget_data.get('transactions', []))
    total_budgeted = sum(c.get('budgeted', 0) for c in budget_data.get('categories', []))
    
    bot.reply_to(message, 
        f"📊 *Summary*\n\n"
        f"💰 Income: ${total_income:.2f}\n"
        f"💸 Spent: ${total_spent:.2f}\n"
        f"🎯 Budgeted: ${total_budgeted:.2f}\n"
        f"📈 Activities: {len(budget_data.get('activityLog', []))}",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['sync'])
def force_sync(message):
    if load_budget_from_gist():
        bot.reply_to(message, "✅ Synced!")
    else:
        bot.reply_to(message, "❌ Sync failed")

@bot.message_handler(func=lambda m: m.text == '💸 Add Expense')
def expense_button(message):
    start_expense(message)

@bot.message_handler(func=lambda m: m.text == '💰 Add Income')
def income_button(message):
    start_income(message)

@bot.message_handler(func=lambda m: m.text == '📊 Analytics')
def analytics_button(message):
    show_analytics(message)

@bot.message_handler(func=lambda m: m.text == '📱 Open App')
def open_app_button(message):
    bot.reply_to(message, f"🌐 [Open App]({WEBAPP_URL})", parse_mode='Markdown')

# Flask webhook setup
app = Flask(__name__)

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '!', 200

@app.route('/')
def index():
    return 'Budget Bot is running!', 200

@app.route('/health')
def health():
    return 'OK', 200

if __name__ == '__main__':
    print("🔄 Loading data...")
    if load_budget_from_gist():
        print("✅ Data loaded")
    else:
        print("⚠️ Initial load failed")
    
    print("\n" + "="*50)
    print("✅ BOT RUNNING - WEBHOOK MODE")
    print("="*50)
    print(f"Port: {PORT}")
    print("="*50 + "\n")
    
    bot.remove_webhook()
    time.sleep(1)
    
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://budget-bot.onrender.com')
    bot.set_webhook(url=f'{webhook_url}/{BOT_TOKEN}')
    print(f"✅ Webhook set to: {webhook_url}/{BOT_TOKEN[:10]}...")
    
    app.run(host='0.0.0.0', port=PORT)
