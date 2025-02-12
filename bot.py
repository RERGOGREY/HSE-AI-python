import os
import json
import requests
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = ""
OPENWEATHER_API_KEY = ""
OPENFOODFACTS_API_URL = "https://world.openfoodfacts.org/cgi/search.pl?search_terms={}&search_simple=1&action=process&json=1"

users = {}

def save_data():
    with open("users.json", "w") as f:
        json.dump(users, f)

def load_data():
    global users
    if os.path.exists("users.json"):
        with open("users.json", "r") as f:
            users = json.load(f)

def get_weather(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("main", {}).get("temp", 20)  # Средняя температура по умолчанию
    return 20

def calculate_water_goal(weight, activity, temperature):
    water_goal = weight * 30 + (activity // 30) * 500
    if temperature > 25:
        water_goal += 500
    return water_goal

def calculate_calorie_goal(weight, height, age, gender, activity):
    if gender == "мужской":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    return bmr + (activity // 30) * 200

def get_food_info(product_name):
    response = requests.get(OPENFOODFACTS_API_URL.format(product_name))
    if response.status_code == 200:
        data = response.json()
        products = data.get('products', [])
        if products:
            first_product = products[0]
            return {
                'name': first_product.get('product_name', 'Неизвестно'),
                'calories': first_product.get('nutriments', {}).get('energy-kcal_100g', 0)
            }
    return None

async def log_food_prompt(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    users[chat_id]["step"] = "log_food"
    save_data()
    await context.bot.send_message(chat_id=chat_id, text="Введите название продукта:")


async def log_water_prompt(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    users[chat_id]["step"] = "log_water"
    await context.bot.send_message(chat_id=chat_id, text="Введите количество воды (мл):")


async def start(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    if chat_id not in users:
        users[chat_id] = {"step": "gender", "logged_water": 0, "logged_calories": 0, "burned_calories": 0}
    keyboard = [[InlineKeyboardButton("Настроить профиль", callback_data='set_profile')],
                [InlineKeyboardButton("Записать воду", callback_data='log_water')],
                [InlineKeyboardButton("Записать еду", callback_data='log_food')],
                [InlineKeyboardButton("Записать тренировку", callback_data='log_exercise')],
                [InlineKeyboardButton("Прогресс", callback_data='check_progress')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=reply_markup)


async def handle_message(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    user = users.get(chat_id, {})
    text = update.message.text.lower()
    logging.info(f"handle_message вызван с текстом: {text} для {chat_id}. Шаг: {user.get('step')}")
    
    if user.get("step") == "gender":
        users[chat_id]["gender"] = text.lower()
        users[chat_id]["step"] = "weight"
        save_data()
        await context.bot.send_message(chat_id=chat_id, text="Введите ваш вес (в кг):")
    elif user.get("step") == "weight":
        users[chat_id]["weight"] = float(text)
        users[chat_id]["step"] = "height"
        save_data()
        await context.bot.send_message(chat_id=chat_id, text="Введите ваш рост (в см):")
    elif user.get("step") == "height":
        users[chat_id]["height"] = float(text)
        users[chat_id]["step"] = "age"
        save_data()
        await context.bot.send_message(chat_id=chat_id, text="Введите ваш возраст:")
    elif user.get("step") == "age":
        users[chat_id]["age"] = int(text)
        users[chat_id]["step"] = "city"
        save_data()
        await context.bot.send_message(chat_id=chat_id, text="Введите ваш город:")
    elif user.get("step") == "city":
        users[chat_id]["city"] = text.capitalize()
        users[chat_id]["temperature"] = get_weather(text)
        users[chat_id]["step"] = None
        save_data()
        await context.bot.send_message(chat_id=chat_id, text="Профиль сохранен! Используйте /check_progress для проверки.")
    elif user.get("step") == "log_exercise":
        exercise_types = {"бег": 500, "велосипед": 400, "силовая": 300}
        calories_burned = exercise_types.get(text, 300)
        water_consumed = (calories_burned // 100) * 200
        users[chat_id]["burned_calories"] += calories_burned
        users[chat_id]["logged_water"] += water_consumed
        users[chat_id]["step"] = None
        save_data()
        await context.bot.send_message(chat_id=chat_id, text=f"Тренировка учтена! Сожжено {calories_burned} ккал, добавлено {water_consumed} мл воды.")
    elif user.get("step") == "log_water":
        try:
            amount = int(text)
            users[chat_id]["logged_water"] += amount
            users[chat_id]["step"] = None
            await context.bot.send_message(chat_id=chat_id, text=f"Записано {amount} мл воды. Всего: {users[chat_id]['logged_water']} мл.")
            save_data()
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="Введите корректное число.")
            save_data()
    elif user.get("step") == "log_food":
        food_info = get_food_info(text)
        if food_info:
            user["logged_calories"] += food_info["calories"]
            user["food_log"].append(food_info)
            user["step"] = None
            save_data()
            await context.bot.send_message(chat_id=chat_id, text=f"Добавлено {food_info['calories']} ккал из {food_info['name']}.")
        else:
            await context.bot.send_message(chat_id=chat_id, text="Продукт не найден.")
    save_data()


async def check_progress(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    user = users.get(chat_id, {})
    if not user or "weight" not in user:
        await context.bot.send_message(chat_id=chat_id, text="Сначала настройте профиль с помощью /set_profile.")
        return
    
    user.setdefault("logged_water", 0)
    user.setdefault("water_goal", calculate_water_goal(user.get("weight", 0), user.get("activity", 0), user.get("temperature", 20)))
    user.setdefault("calorie_goal", calculate_calorie_goal(user.get("weight", 0), user.get("height", 0), user.get("age", 0), user.get("gender", "мужской"), user.get("activity", 0)))
    save_data()
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Прогресс:\n"
             f"Вода: {user['logged_water']} мл из {user['water_goal']} мл.\n"
             f"Калории: {user.get('logged_calories', 0)} из {user['calorie_goal']}, \n"
             f"Сожжено {user.get('burned_calories', 0)} ккал."
    )

async def set_profile(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.effective_chat.id)
    users[chat_id] = {"step": "gender", "logged_water": 0, "logged_calories": 0, "burned_calories": 0}
    await context.bot.send_message(chat_id=chat_id, text="Введите ваш пол (мужской/женский):")


async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == 'set_profile':
        await set_profile(update, context)
    elif query.data == 'log_water':
        await log_water_prompt(update, context)
    elif query.data == 'log_food':
        users[str(query.message.chat_id)]["step"] = "log_food"
        await query.message.reply_text("Введите название продукта:")
    elif query.data == 'log_exercise':
        users[str(query.message.chat_id)]["step"] = "log_exercise"
        await query.message.reply_text("Введите тип тренировки (бег, велосипед, силовая):")
    elif query.data == 'check_progress':
        await check_progress(update, context)


def main():
    load_data()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == "__main__":
    main()