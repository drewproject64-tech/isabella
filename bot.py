"""Trader Isabella, a Telegram bot for beginner forex education."""

import json
import logging
import os
import re
import time
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen

NAME = "Trader Isabella"
ABOUT = "Learn forex basics, practice EUR/USD pip calculations, and take a short quiz."
DESCRIPTION = (
    "Learn how currency pairs, pips, spreads, and leverage work. Practice calculating "
    "pip distances with hypothetical EUR/USD prices, then test your knowledge with "
    "five questions and explanations. Send /start to open the menu."
)
LESSONS = (
    "Currency pairs: EUR/USD shows how many US dollars one euro costs. "
    "At 1.1000, one euro costs 1.10 US dollars.\n\n"
    "Pips: For EUR/USD, one pip is 0.0001. Moving from 1.1000 to 1.1025 "
    "is a 25-pip rise.\n\n"
    "Spread: The spread is the difference between the bid and ask. A bid "
    "of 1.1000 and an ask of 1.1002 give a 2-pip spread.\n\n"
    "Leverage: Leverage lets a smaller deposit control a larger position. "
    "It magnifies both gains and losses relative to the amount deposited."
)
PIP_PROMPT = "Send two hypothetical EUR/USD prices, for example: 1.1000 1.1025"
PRICE = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,5})?")
QUESTIONS = (
    ("Which currency is the base currency in EUR/USD?", ("EUR", "USD"), 0,
     "The base currency is the first currency in the pair."),
    ("How large is one pip for EUR/USD?", ("0.0001", "0.01"), 0,
     "For EUR/USD, one pip is 0.0001."),
    ("How far apart are 1.1000 and 1.1025?", ("2.5 pips", "25 pips"), 1,
     "The difference is 0.0025. Dividing by 0.0001 gives 25 pips."),
    ("What does the spread measure?", ("The bid–ask difference", "Yesterday's price change"), 0,
     "The spread is the difference between the bid and ask prices."),
    ("What can leverage magnify?", ("Gains only", "Gains and losses"), 1,
     "Leverage magnifies both gains and losses relative to the deposit."),
)
MENU = {"keyboard": [[{"text": label}] for label in
                     ("Forex Basics", "Pip Practice", "Forex Quiz")],
        "resize_keyboard": True}


class TelegramError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(f"Telegram API error {code}")
        self.code = code
        self.retry_after = retry_after


def telegram(token, method, **payload):
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=40) as response:
            result = json.load(response)
    except URLError as error:
        if hasattr(error, "code"):
            with error:
                result = json.load(error)
        else:
            raise TelegramError("connection") from None
    except TimeoutError:
        raise TelegramError("timeout") from None
    if not result["ok"]:
        raise TelegramError(result["error_code"], result.get("parameters", {}).get("retry_after", 0))
    return result["result"]


def pip_result(text):
    prices = text.split()
    if len(prices) != 2 or not all(PRICE.fullmatch(price) for price in prices):
        return PIP_PROMPT
    first, second = map(Decimal, prices)
    if min(first, second) <= 0:
        return PIP_PROMPT
    distance = abs(second - first) / Decimal("0.0001")
    return f"Distance: {distance.normalize():f} pips."


def quiz_question(index, score, feedback=""):
    question, options, _, _ = QUESTIONS[index]
    return {
        "text": f"{feedback}Question {index + 1} of {len(QUESTIONS)}\n{question}",
        "reply_markup": {"inline_keyboard": [
            [{"text": option, "callback_data": f"quiz:{index}:{score}:{choice}"}]
            for choice, option in enumerate(options)
        ]},
    }


def handle_update(token, update):
    callback = update.get("callback_query")
    if callback:
        telegram(token, "answerCallbackQuery", callback_query_id=callback["id"])
        match = re.fullmatch(r"quiz:([0-4]):([0-4]):([01])", callback.get("data", ""))
        message = callback.get("message", {})
        if not match or not message.get("text"):
            return
        index, score, choice = map(int, match.groups())
        if score > index or QUESTIONS[index][0] not in message["text"]:
            return
        _, _, correct_choice, explanation = QUESTIONS[index]
        correct = choice == correct_choice
        score += correct
        feedback = f"{'Correct.' if correct else 'Incorrect.'} {explanation}\n\n"
        next_index = index + 1
        if next_index == len(QUESTIONS):
            reply = {"text": f"{feedback}Final score: {score}/{len(QUESTIONS)}.",
                     "reply_markup": {"inline_keyboard": []}}
        else:
            reply = quiz_question(next_index, score, feedback)
        telegram(token, "editMessageText", chat_id=message["chat"]["id"],
                 message_id=message["message_id"], **reply)
        return

    message = update.get("message", {})
    text = message.get("text", "").strip()
    if not text or message["chat"]["type"] != "private":
        return
    chat_id = message["chat"]["id"]
    command = text.split()[0].partition("@")[0]
    if command in ("/start", "/help"):
        answer = f"Welcome to {NAME}. Choose a button below to get started."
    elif text == "Forex Basics":
        answer = LESSONS
    elif text == "Pip Practice":
        answer = PIP_PROMPT
    elif text == "Forex Quiz":
        telegram(token, "sendMessage", chat_id=chat_id, **quiz_question(0, 0))
        return
    else:
        answer = pip_result(text)
    telegram(token, "sendMessage", chat_id=chat_id, text=answer, reply_markup=MENU)


def main():
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise SystemExit("Set BOT_TOKEN to the token from BotFather.")

    telegram(token, "setMyName", name=NAME)
    telegram(token, "setMyShortDescription", short_description=ABOUT)
    telegram(token, "setMyDescription", description=DESCRIPTION)
    telegram(token, "setMyCommands", commands=[
        {"command": "start", "description": "Open the main menu"},
        {"command": "help", "description": "Show the available tools"},
    ])

    offset = 0
    logging.info("Trader Isabella is polling for updates.")
    while True:
        try:
            updates = telegram(token, "getUpdates", offset=offset, timeout=25,
                               allowed_updates=["message", "callback_query"])
        except TelegramError as error:
            logging.warning("%s while polling", error)
            time.sleep(max(3, error.retry_after))
            continue
        for update in updates:
            try:
                handle_update(token, update)
            except TelegramError as error:
                logging.warning("%s while handling an update", error)
                if error.retry_after:
                    time.sleep(error.retry_after)
            offset = update["update_id"] + 1


if __name__ == "__main__":
    main()
