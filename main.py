import os
from collections import defaultdict, deque
from dotenv import load_dotenv
import telebot
from openai import OpenAI
import time

# Загружаем переменные из файла .env в окружение
load_dotenv()

# ====== ХРАНИЛИЩА ======
user_history = defaultdict(lambda: deque(maxlen=2))
user_state = {}
user_answers = {}

user_question_mode = set()  # режим свободных вопросов

# ====== ТОКЕНЫ ======
# Получаем значения из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Хорошая практика: проверить, что токены действительно загрузились
if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise ValueError("Ошибка: Не найдены TELEGRAM_TOKEN или OPENAI_API_KEY в файле .env")


bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=OPENAI_API_KEY)

# ====== ВОПРОСЫ ======
QUESTIONS = [
    "Что сегодня получилось хорошо?",
    "Что вызвало трудности?",
    "Что ты чувствовал(а) в течение дня?",
    "Что можно улучшить завтра?"
]

# ====== ВСПОМОГАТЕЛЬНОЕ ======
def typing(uid, t=1):
    bot.send_chat_action(uid, "typing")
    time.sleep(t)


def clean_answers(a):
    return [x.strip() if x.strip() else "—" for x in a]


# ====== HELP ======
@bot.message_handler(commands=["help"])
def help_cmd(message):
    typing(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🆘 Помощь 🆘 \n\n"
        "/start — начать рефлексию\n"
        "/next — пропустить вопрос\n"
        "/analysis — сравнение 2 рефлексий\n\n"
        "/question — режим вопросов\n"
        "/cancel — выйти из режима вопросов\n\n"
        "❗️В режиме вопросов я отвечаю в контексте саморефлексии, используя искусственный интеллект❗️"
    )


# ====== START ======
@bot.message_handler(commands=["start"])
def start(message):
    uid = message.chat.id
    user_state[uid] = 0
    user_answers[uid] = []

    typing(uid)
    bot.send_message(
        uid,
        "Начнём рефлексию 🌱\n\n"
        "Команда /next, чтобы пропустить вопрос.\n"
        f"{QUESTIONS[0]}"
    )


# ====== NEXT ======
@bot.message_handler(commands=["next"])
def next_q(message):
    uid = message.chat.id

    if uid not in user_state:
        typing(uid)
        bot.send_message(uid, "Активной рефлексии сейчас нет.")
        return

    user_answers[uid].append(" ")
    step = user_state[uid] + 1

    typing(uid)

    if step < len(QUESTIONS):
        user_state[uid] = step
        bot.send_message(uid, QUESTIONS[step])
    else:
        finish_reflection(uid)


# ====== ОСНОВНАЯ РЕФЛЕКСИЯ ======
@bot.message_handler(
    func=lambda m:
    m.chat.id in user_state
    and m.chat.id not in user_question_mode
    and m.text
    and not m.text.startswith("/")
)
def reflection(message):
    uid = message.chat.id

    user_answers[uid].append(message.text)
    step = user_state[uid] + 1

    typing(uid)

    if step < len(QUESTIONS):
        user_state[uid] = step
        bot.send_message(uid, QUESTIONS[step])
    else:
        finish_reflection(uid)


def finish_reflection(uid):
    answers = clean_answers(user_answers[uid])
    user_history[uid].append(answers)

    summary = make_conclusion(answers)
    advice = get_ai_advice(answers)

    typing(uid, 2)
    bot.send_message(uid, summary + "\n\n🤖 Совет:\n" + advice)

    del user_state[uid]
    del user_answers[uid]


# ====== QUESTION MODE ======
@bot.message_handler(commands=["question"])
def enter_question_mode(message):
    uid = message.chat.id
    user_question_mode.add(uid)

    typing(uid)
    bot.send_message(
        uid,
        "💬 Режим вопросов включён.\n"
        "Пиши вопросы подряд.\n"
        "Я отвечаю в контексте рефлексии.\n\n"
        "Чтобы выйти — /cancel"
    )


@bot.message_handler(commands=["cancel"])
def exit_question_mode(message):
    uid = message.chat.id
    user_question_mode.discard(uid)

    typing(uid)
    if uid in user_state:
        bot.send_message(uid, f"Ок, вернёмся 😊\n{QUESTIONS[user_state[uid]]}")
    else:
        bot.send_message(uid, "Режим вопросов выключен.")


@bot.message_handler(
    func=lambda m:
    m.chat.id in user_question_mode
    and m.text
    and not m.text.startswith("/")
)
def question_chat(message):
    uid = message.chat.id
    question = message.text.strip()
    prompt = f"""
    Ты помощник по саморефлексии.

    Если вопрос не связан с эмоциями, состоянием,
    мыслями, мотивацией или прошедшим днём —
    мягко переведи разговор к размышлению о себе.

    Вопрос:
    {question}

    Ответ:
    """

    typing(uid, 2)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6
    )

    answer = response.choices[0].message.content.strip()

    if uid in user_state:
        answer += f"\n\n(Мы остановились на вопросе: {QUESTIONS[user_state[uid]]})"

    bot.send_message(uid, answer)


# ====== ANALYSIS ======
@bot.message_handler(commands=["analysis"])
def analysis(message):
    uid = message.chat.id
    history = user_history.get(uid)

    if not history or len(history) < 2:
        typing(uid)
        bot.send_message(uid, "Нужно минимум 2 рефлексии.")
        return

    d1, d2 = history[0], history[1]

    prompt = f"""
    Сравни две рефлексии мягко и поддерживающе.

    1) {d1}
    2) {d2}

    5–7 предложений:
    — изменения
    — эмоции
    — прогресс
    — что продолжить
    """

    typing(uid, 2)

    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6
    )

    bot.send_message(uid, "📊 Анализ:\n\n" + r.choices[0].message.content.strip())


# ====== ИТОГ ======
def make_conclusion(a):
    g, p, f, i = a
    t = "🧠 Итог:\n\n"
    t += f"✔️ Хорошо: {g}\n"
    t += f"⚠️ Трудности: {p}\n"
    t += f"❤️ Эмоции: {f}\n\n"
    t += "📌 Рекомендация:\n"
    t += f"- Завтра сфокусируйся на: {i if len(i) > 10 else 'одной простой цели'}"
    return t


def get_ai_advice(a):
    prompt = f"""
    Дай конкретный, тёплый совет на завтра.
    6–8 предложений.

    Ответы:
    {a}
    """
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return r.choices[0].message.content.strip()


# ====== RUN ======
print("Бот запущен")
bot.infinity_polling()

