#!/usr/bin/env python3
"""
🇮🇹  Italiano Bot — Beginner → Intermediate Italian for travellers.

Free stack (no paid / non-free API):
  • python-telegram-bot  (MIT)
  • gTTS                 (free Google-Translate TTS, no key needed)

20 lessons across 4 levels:
  🟢 BEGINNER    L01-L05  — alphabet sounds, greetings, numbers, self-intro, colours
  🔵 ELEMENTARY  L06-L10  — at the hotel, transport, shopping, restaurant, emergencies
  🟡 PRE-INTER   L11-L15  — directions, time/dates, body/health, phone/internet, weather
  🟠 INTERMEDIATE L16-L20 — opinions, Italian culture chat, subjunctive taste, travel tips

SETUP
  1. Message @BotFather → /newbot → copy the token.
  2. pip install "python-telegram-bot>=20" gTTS
  3. export BOT_TOKEN="your-token"  (Windows: set BOT_TOKEN=...)
  4. python italiano_bot.py
"""

import asyncio
import math
import os
import random
import tempfile
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from gtts import gTTS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_TOKEN_FROM_BOTFATHER_HERE")

# ─────────────────────────────────────────────────────────────────────────────
#  SPACED REPETITION ENGINE  (SM-2 algorithm — same core as Anki / Duolingo)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Each word gets a card stored in user_data["srs"][key] with:
#    interval   — days until next review (starts at 1)
#    easiness   — difficulty multiplier (starts at 2.5, min 1.3)
#    due        — ISO date string when the card is next due
#    streak     — consecutive correct answers
#
#  Quality scores we use:
#    5 = perfect  (first try correct)
#    3 = correct after hesitation / second try
#    1 = wrong
#
#  After each answer the interval is recalculated:
#    wrong  → reset to 1 day
#    right  → interval = round(interval * easiness)
#    easiness adjusted by: easiness += 0.1 - (5-q)*(0.08+(5-q)*0.02)
# ─────────────────────────────────────────────────────────────────────────────

def _srs_key(italian: str) -> str:
    """Stable dict key from an Italian phrase."""
    return italian.lower().strip()


def _today() -> str:
    return date.today().isoformat()


def _card_default() -> dict:
    """A brand-new card — NOT due yet. Due date is set when the word is seeded."""
    return {"interval": 1, "easiness": 2.5, "due": None, "streak": 0}


def srs_seed(user_data: dict, italian: str) -> None:
    """
    Mark a word as 'seen in a lesson' — schedule its first review for today.
    Only seeds if the card doesn't exist yet (so we never overwrite progress).
    """
    cards = user_data.setdefault("srs", {})
    key = _srs_key(italian)
    if key not in cards:
        card = _card_default()
        card["due"] = _today()   # first review: right now / today
        cards[key] = card


def srs_update(user_data: dict, italian: str, quality: int) -> dict:
    """
    Update the SRS card for `italian` with answer quality (1/3/5).
    Also seeds the card if it has never been seen (e.g. quiz without prior lesson).
    Returns the updated card.
    """
    srs_seed(user_data, italian)          # ensure card exists
    cards = user_data["srs"]
    key = _srs_key(italian)
    card = cards[key]

    if quality >= 3:  # correct
        if card["streak"] == 0:
            new_interval = 1
        elif card["streak"] == 1:
            new_interval = 6
        else:
            new_interval = round(card["interval"] * card["easiness"])
        card["streak"] += 1
    else:  # wrong — reset to 1 day
        new_interval = 1
        card["streak"] = 0

    card["easiness"] = max(1.3, card["easiness"] + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    card["interval"] = new_interval
    card["due"] = (date.today() + timedelta(days=new_interval)).isoformat()
    cards[key] = card
    return card


def srs_due_cards(user_data: dict, level_key: str) -> list[tuple[str, str]]:
    """
    Return all (italian, english) pairs that:
      - have been seeded (lesson opened or quizzed at least once), AND
      - are due for review today or overdue.
    Words never seen are NOT included.
    """
    cards = user_data.get("srs", {})
    today = _today()
    pool = level_items(level_key)
    due = []
    for italian, english in pool:
        key = _srs_key(italian)
        card = cards.get(key)
        # card must exist AND have a due date (not None) AND be due
        if card and card.get("due") and card["due"] <= today:
            due.append((italian, english))
    return due


def srs_stats(user_data: dict) -> dict:
    """Return summary stats: total seeded, due today, mastered (interval>=21)."""
    cards = user_data.get("srs", {})
    today = _today()
    seeded = [c for c in cards.values() if c.get("due") is not None]
    due = sum(1 for c in seeded if c["due"] <= today)
    mastered = sum(1 for c in seeded if c["interval"] >= 21)
    return {"total": len(seeded), "due": due, "mastered": mastered}


# ─────────────────────────────────────────────────────────────────────────────
#  LEVELS
# ─────────────────────────────────────────────────────────────────────────────
LEVELS = {
    "beginner":     {"emoji": "🟢", "label": "Beginner",      "lessons": list(range(0,  5))},
    "elementary":   {"emoji": "🔵", "label": "Elementary",    "lessons": list(range(5,  10))},
    "preinter":     {"emoji": "🟡", "label": "Pre-Intermediate","lessons": list(range(10, 15))},
    "intermediate": {"emoji": "🟠", "label": "Intermediate",  "lessons": list(range(15, 20))},
}

# ─────────────────────────────────────────────────────────────────────────────
#  LESSONS  — (Italian phrase/word,  English translation)
# ─────────────────────────────────────────────────────────────────────────────
LESSONS = [

    # ── BEGINNER ─────────────────────────────────────────────────────────────
    {
        "level": "beginner",
        "title": "L01 🟢 Greetings (Saluti)",
        "tip": "💡 'Ciao' works for both hello and goodbye with friends. Use 'Buongiorno' with strangers.",
        "items": [
            ("Ciao",                "Hi / Bye (informal)"),
            ("Buongiorno",          "Good morning / Good day"),
            ("Buonasera",           "Good evening"),
            ("Buonanotte",          "Good night"),
            ("Arrivederci",         "Goodbye (formal)"),
            ("A presto",            "See you soon"),
            ("Salve",               "Hello (neutral, safe with anyone)"),
            ("Ci vediamo",          "See you later"),
        ],
    },
    {
        "level": "beginner",
        "title": "L02 🟢 Courtesy & Basics (Cortesia)",
        "tip": "💡 'Prego' is incredibly versatile — it means 'you're welcome', 'please go ahead', and 'here you are'.",
        "items": [
            ("Grazie",              "Thank you"),
            ("Grazie mille",        "Thank you very much"),
            ("Prego",               "You're welcome / Go ahead / Here you are"),
            ("Per favore",          "Please"),
            ("Per piacere",         "Please (alternative)"),
            ("Scusa",               "Sorry / Excuse me (informal)"),
            ("Mi scusi",            "Excuse me (formal)"),
            ("Mi dispiace",         "I'm sorry"),
            ("Sì",                  "Yes"),
            ("No",                  "No"),
            ("Forse",               "Maybe"),
        ],
    },
    {
        "level": "beginner",
        "title": "L03 🟢 Numbers & Money (Numeri e Soldi)",
        "tip": "💡 Italy uses euros (€). Knowing numbers is essential for prices, addresses and menus.",
        "items": [
            ("uno",                 "1"),
            ("due",                 "2"),
            ("tre",                 "3"),
            ("quattro",             "4"),
            ("cinque",              "5"),
            ("sei",                 "6"),
            ("sette",               "7"),
            ("otto",                "8"),
            ("nove",                "9"),
            ("dieci",               "10"),
            ("venti",               "20"),
            ("cinquanta",           "50"),
            ("cento",               "100"),
            ("Quanto costa?",       "How much does it cost?"),
            ("È troppo caro",       "It's too expensive"),
        ],
    },
    {
        "level": "beginner",
        "title": "L04 🟢 Introducing Yourself (Presentarsi)",
        "tip": "💡 Italians often ask 'Di dove sei?' — be ready with 'Sono di...' + your city/country.",
        "items": [
            ("Come ti chiami?",     "What's your name? (informal)"),
            ("Come si chiama?",     "What's your name? (formal)"),
            ("Mi chiamo...",        "My name is..."),
            ("Piacere di conoscerti","Nice to meet you (informal)"),
            ("Quanti anni hai?",    "How old are you?"),
            ("Ho ... anni",         "I am ... years old"),
            ("Di dove sei?",        "Where are you from?"),
            ("Sono di...",          "I am from..."),
            ("Sono inglese",        "I am English"),
            ("Parli italiano?",     "Do you speak Italian?"),
            ("Un po'",              "A little bit"),
            ("Non capisco",         "I don't understand"),
            ("Puoi ripetere?",      "Can you repeat that?"),
            ("Più lentamente, per favore","More slowly, please"),
        ],
    },
    {
        "level": "beginner",
        "title": "L05 🟢 Colours & Descriptions (Colori)",
        "tip": "💡 Adjectives in Italian change ending by gender: rosso (m) / rossa (f).",
        "items": [
            ("rosso / rossa",       "red"),
            ("blu",                 "blue"),
            ("verde",               "green"),
            ("giallo / gialla",     "yellow"),
            ("bianco / bianca",     "white"),
            ("nero / nera",         "black"),
            ("arancione",           "orange"),
            ("rosa",                "pink"),
            ("grande",              "big"),
            ("piccolo / piccola",   "small"),
            ("bello / bella",       "beautiful"),
            ("buono / buona",       "good"),
            ("nuovo / nuova",       "new"),
            ("vecchio / vecchia",   "old"),
        ],
    },

    # ── ELEMENTARY ───────────────────────────────────────────────────────────
    {
        "level": "elementary",
        "title": "L06 🔵 At the Hotel (All'Albergo)",
        "tip": "💡 Always confirm checkout time ('l'orario del check-out') on arrival to avoid surprises.",
        "items": [
            ("Ho una prenotazione",         "I have a reservation"),
            ("Vorrei una camera",           "I would like a room"),
            ("una camera singola",          "a single room"),
            ("una camera doppia",           "a double room"),
            ("con bagno",                   "with bathroom"),
            ("con aria condizionata",       "with air conditioning"),
            ("la colazione è inclusa?",     "Is breakfast included?"),
            ("A che ora è il check-out?",   "What time is check-out?"),
            ("Il WiFi funziona?",           "Does the WiFi work?"),
            ("C'è un problema con la camera","There is a problem with the room"),
            ("Può chiamare un taxi?",       "Can you call a taxi?"),
            ("Dov'è l'ascensore?",          "Where is the elevator?"),
            ("la chiave",                   "the key"),
            ("il piano",                    "the floor / storey"),
        ],
    },
    {
        "level": "elementary",
        "title": "L07 🔵 Transport (Trasporti)",
        "tip": "💡 Validate your train/bus ticket BEFORE boarding — inspectors fine even innocent tourists.",
        "items": [
            ("Dove si compra il biglietto?","Where do I buy the ticket?"),
            ("Un biglietto per..., per favore","A ticket to..., please"),
            ("andata e ritorno",            "return / round trip"),
            ("solo andata",                 "one way"),
            ("A che ora parte il treno?",   "What time does the train leave?"),
            ("Il treno è in ritardo?",      "Is the train delayed?"),
            ("binario",                     "platform / track"),
            ("la fermata dell'autobus",     "the bus stop"),
            ("la metropolitana",            "the underground / metro"),
            ("l'aeroporto",                 "the airport"),
            ("la stazione",                 "the station"),
            ("Vorrei noleggiare una macchina","I would like to rent a car"),
            ("pieno di benzina",            "full of petrol"),
            ("È lontano?",                  "Is it far?"),
        ],
    },
    {
        "level": "elementary",
        "title": "L08 🔵 Shopping (Fare la Spesa)",
        "tip": "💡 Many Italian shops close 1–4pm for riposo (rest). Plan accordingly!",
        "items": [
            ("Posso aiutarla?",             "Can I help you? (staff to customer)"),
            ("Sto solo guardando, grazie",  "I'm just looking, thanks"),
            ("Avete questo in un'altra taglia?","Do you have this in another size?"),
            ("piccolo / medio / grande",    "small / medium / large"),
            ("Posso provarlo?",             "Can I try it on?"),
            ("Quanto costa questo?",        "How much does this cost?"),
            ("Accettate carte di credito?", "Do you accept credit cards?"),
            ("Vorrei un sacchetto",         "I would like a bag"),
            ("Vorrei un rimborso",          "I would like a refund"),
            ("il mercato",                  "the market"),
            ("il supermercato",             "the supermarket"),
            ("la farmacia",                 "the pharmacy"),
            ("aperto / chiuso",             "open / closed"),
            ("gli sconti",                  "the discounts / sales"),
        ],
    },
    {
        "level": "elementary",
        "title": "L09 🔵 At the Restaurant (Al Ristorante)",
        "tip": "💡 'Coperto' is a cover charge (bread + table). It's legal and normal — check the menu.",
        "items": [
            ("Un tavolo per due, per favore","A table for two, please"),
            ("Avete un menu in inglese?",   "Do you have a menu in English?"),
            ("Cosa consiglia?",             "What do you recommend?"),
            ("Vorrei...",                   "I would like..."),
            ("il primo piatto",             "the first course (pasta/soup)"),
            ("il secondo piatto",           "the second course (meat/fish)"),
            ("il contorno",                 "the side dish"),
            ("il dolce",                    "the dessert"),
            ("acqua naturale o frizzante?", "still or sparkling water?"),
            ("Il conto, per favore",        "The bill, please"),
            ("È incluso il servizio?",      "Is service included?"),
            ("Sono vegetariano/a",          "I am vegetarian"),
            ("Sono allergico/a a...",       "I am allergic to..."),
            ("Era delizioso!",              "It was delicious!"),
        ],
    },
    {
        "level": "elementary",
        "title": "L10 🔵 Emergencies & Help (Emergenze)",
        "tip": "💡 112 is the universal emergency number in Italy for police, fire, and ambulance.",
        "items": [
            ("Aiuto!",                      "Help!"),
            ("Al ladro!",                   "Stop thief!"),
            ("Chiami la polizia!",          "Call the police!"),
            ("Chiami un'ambulanza!",        "Call an ambulance!"),
            ("Mi hanno rubato il portafoglio","Someone stole my wallet"),
            ("Ho perso il passaporto",      "I have lost my passport"),
            ("Mi sono perso/a",             "I am lost"),
            ("Ho bisogno di un medico",     "I need a doctor"),
            ("Dove è l'ospedale?",          "Where is the hospital?"),
            ("Sto male",                    "I feel ill"),
            ("Sono ferito/a",               "I am injured"),
            ("Dov'è il consolato?",         "Where is the consulate?"),
            ("È un'emergenza",              "It is an emergency"),
            ("Non toccarmi!",               "Don't touch me!"),
        ],
    },

    # ── PRE-INTERMEDIATE ─────────────────────────────────────────────────────
    {
        "level": "preinter",
        "title": "L11 🟡 Directions (Indicazioni Stradali)",
        "tip": "💡 Italians often give directions using landmarks ('dopo la chiesa...') not street names.",
        "items": [
            ("Dove si trova...?",           "Where is...?"),
            ("Come arrivo a...?",           "How do I get to...?"),
            ("Vai dritto",                  "Go straight ahead"),
            ("Gira a sinistra",             "Turn left"),
            ("Gira a destra",               "Turn right"),
            ("Al semaforo",                 "At the traffic lights"),
            ("All'incrocio",                "At the crossroads"),
            ("di fronte a",                 "opposite / in front of"),
            ("accanto a",                   "next to"),
            ("dietro",                      "behind"),
            ("vicino",                      "near / nearby"),
            ("lontano",                     "far"),
            ("la piazza",                   "the square / piazza"),
            ("il ponte",                    "the bridge"),
            ("il centro storico",           "the historic centre"),
        ],
    },
    {
        "level": "preinter",
        "title": "L12 🟡 Time & Dates (Tempo e Date)",
        "tip": "💡 Italy uses 24-hour time in timetables. 'Sono le 14:30' = 2:30pm.",
        "items": [
            ("Che ora è?",                  "What time is it?"),
            ("Sono le tre",                 "It is 3 o'clock"),
            ("mezzogiorno",                 "noon"),
            ("mezzanotte",                  "midnight"),
            ("stamattina",                  "this morning"),
            ("questo pomeriggio",           "this afternoon"),
            ("stasera",                     "this evening"),
            ("ieri",                        "yesterday"),
            ("oggi",                        "today"),
            ("domani",                      "tomorrow"),
            ("la settimana prossima",       "next week"),
            ("lunedì",                      "Monday"),
            ("martedì",                     "Tuesday"),
            ("mercoledì",                   "Wednesday"),
            ("giovedì",                     "Thursday"),
            ("venerdì",                     "Friday"),
            ("sabato",                      "Saturday"),
            ("domenica",                    "Sunday"),
        ],
    },
    {
        "level": "preinter",
        "title": "L13 🟡 Body & Health (Corpo e Salute)",
        "tip": "💡 In Italy, pharmacists (farmacisti) can give basic medical advice and prescribe mild treatments.",
        "items": [
            ("la testa",                    "head"),
            ("gli occhi",                   "eyes"),
            ("la bocca",                    "mouth"),
            ("il collo",                    "neck"),
            ("il petto",                    "chest"),
            ("lo stomaco",                  "stomach"),
            ("la schiena",                  "back"),
            ("il braccio",                  "arm"),
            ("la mano",                     "hand"),
            ("la gamba",                    "leg"),
            ("il piede",                    "foot"),
            ("Mi fa male...",               "...hurts / I have pain in..."),
            ("Ho la febbre",                "I have a fever"),
            ("Ho il raffreddore",           "I have a cold"),
            ("Ho bisogno di medicine",      "I need medicine"),
            ("Sono diabetico/a",            "I am diabetic"),
        ],
    },
    {
        "level": "preinter",
        "title": "L14 🟡 Phone, Internet & Tech (Tecnologia)",
        "tip": "💡 Ask 'C'è il WiFi?' (Is there WiFi?) everywhere — most cafés give it free with a drink.",
        "items": [
            ("C'è il WiFi?",                "Is there WiFi?"),
            ("Qual è la password?",         "What is the password?"),
            ("Il mio telefono non funziona","My phone isn't working"),
            ("Ho bisogno di un caricatore", "I need a charger"),
            ("Posso caricare il telefono?", "Can I charge my phone?"),
            ("Vorrei una SIM italiana",     "I would like an Italian SIM card"),
            ("mandare un messaggio",        "to send a message"),
            ("fare una foto",               "to take a photo"),
            ("Posso fare una foto qui?",    "Can I take a photo here?"),
            ("la connessione è lenta",      "the connection is slow"),
            ("il numero di telefono",       "the phone number"),
            ("Puoi scriverlo?",             "Can you write it down?"),
        ],
    },
    {
        "level": "preinter",
        "title": "L15 🟡 Weather & Seasons (Meteo e Stagioni)",
        "tip": "💡 August (agosto) is peak heat AND many Romans/Milanese flee — some shops close. Plan wisely.",
        "items": [
            ("Che tempo fa?",               "What is the weather like?"),
            ("Fa caldo",                    "It is hot"),
            ("Fa freddo",                   "It is cold"),
            ("Piove",                       "It is raining"),
            ("Nevica",                      "It is snowing"),
            ("C'è il sole",                 "It is sunny"),
            ("C'è vento",                   "It is windy"),
            ("temporale",                   "thunderstorm"),
            ("la primavera",                "spring"),
            ("l'estate",                    "summer"),
            ("l'autunno",                   "autumn"),
            ("l'inverno",                   "winter"),
            ("la previsione del tempo",     "the weather forecast"),
            ("Devo portare un ombrello?",   "Should I bring an umbrella?"),
        ],
    },

    # ── INTERMEDIATE ─────────────────────────────────────────────────────────
    {
        "level": "intermediate",
        "title": "L16 🟠 Opinions & Feelings (Opinioni e Sentimenti)",
        "tip": "💡 Italians are expressive — don't be shy! Enthusiasm ('Che bello!') is always welcome.",
        "items": [
            ("Penso che...",                "I think that..."),
            ("Secondo me...",               "In my opinion..."),
            ("Sono d'accordo",              "I agree"),
            ("Non sono d'accordo",          "I disagree"),
            ("Hai ragione",                 "You are right"),
            ("Hai torto",                   "You are wrong"),
            ("Mi piace molto",              "I like it a lot"),
            ("Non mi piace",                "I don't like it"),
            ("È interessante",              "It is interesting"),
            ("Che bello!",                  "How beautiful! / How great!"),
            ("Che peccato!",                "What a shame!"),
            ("Per fortuna",                 "Fortunately / Luckily"),
            ("Purtroppo",                   "Unfortunately"),
            ("Dipende",                     "It depends"),
        ],
    },
    {
        "level": "intermediate",
        "title": "L17 🟠 Italian Culture & Sightseeing (Cultura)",
        "tip": "💡 Dress code matters! Cover shoulders and knees to enter churches — carry a scarf.",
        "items": [
            ("il museo",                    "the museum"),
            ("la chiesa",                   "the church"),
            ("il castello",                 "the castle"),
            ("la galleria d'arte",          "the art gallery"),
            ("l'affresco",                  "the fresco"),
            ("il Rinascimento",             "the Renaissance"),
            ("il biglietto d'ingresso",     "the entry ticket"),
            ("a che ora apre/chiude?",      "what time does it open/close?"),
            ("È patrimonio UNESCO",         "It is a UNESCO World Heritage site"),
            ("la guida turistica",          "the tour guide / guidebook"),
            ("Posso entrare?",              "May I enter?"),
            ("il codice di abbigliamento",  "the dress code"),
            ("vietato fotografare",         "photography prohibited"),
            ("la sagra",                    "the local food festival"),
        ],
    },
    {
        "level": "intermediate",
        "title": "L18 🟠 Food Culture & Ordering Like a Local",
        "tip": "💡 Order 'un caffè' and you get espresso. Cappuccino is a breakfast drink — after 11am locals raise an eyebrow!",
        "items": [
            ("un caffè",                    "an espresso"),
            ("un cappuccino",               "a cappuccino (breakfast only!)"),
            ("un cornetto",                 "a croissant"),
            ("aperitivo",                   "pre-dinner drinks + snacks hour"),
            ("Prosecco",                    "Italian sparkling wine"),
            ("la pizza margherita",         "pizza with tomato, mozzarella, basil"),
            ("al dente",                    "pasta cooked firm to the bite"),
            ("antipasto",                   "starter / appetiser"),
            ("il risotto",                  "creamy rice dish"),
            ("la gelato artigianale",       "artisan ice cream"),
            ("il tiramisù",                 "tiramisu dessert"),
            ("pane e coperto",              "bread & cover charge"),
            ("Con ghiaccio?",               "With ice?"),
            ("Da portare via",              "To take away"),
        ],
    },
    {
        "level": "intermediate",
        "title": "L19 🟠 Grammar: Verbs in Action (Verbi Utili)",
        "tip": "💡 The 'io' (I) form of -are verbs ends in -o: parLO, mangIO, viaggIO.",
        "items": [
            ("Parlo italiano",              "I speak Italian"),
            ("Capisco un po'",              "I understand a little"),
            ("Voglio visitare...",          "I want to visit..."),
            ("Devo andare",                 "I have to go"),
            ("Posso avere...?",             "Can I have...?"),
            ("Sto cercando...",             "I am looking for..."),
            ("Mi serve...",                 "I need... (literally: I need to me...)"),
            ("Ho fame",                     "I am hungry"),
            ("Ho sete",                     "I am thirsty"),
            ("Ho sonno",                    "I am sleepy"),
            ("Andiamo!",                    "Let's go!"),
            ("Aspetta!",                    "Wait!"),
            ("Senta!",                      "Excuse me! (to get attention, formal)"),
            ("Non so",                      "I don't know"),
        ],
    },
    {
        "level": "intermediate",
        "title": "L20 🟠 Advanced Travel Phrases (Frasi da Viaggiatore)",
        "tip": "💡 Locals love it when tourists try Italian. Even broken Italian beats silence — smile and try!",
        "items": [
            ("Sto viaggiando da solo/a",    "I am travelling alone"),
            ("Siamo un gruppo di...",       "We are a group of..."),
            ("Cerco un posto tranquillo",   "I am looking for a quiet place"),
            ("Quali sono le specialità locali?","What are the local specialities?"),
            ("Che cosa si fa qui la sera?", "What is there to do here in the evening?"),
            ("C'è uno spettacolo stasera?", "Is there a show tonight?"),
            ("Vorrei prenotare un tour",    "I would like to book a tour"),
            ("Quanto ci vuole per arrivare?","How long does it take to get there?"),
            ("C'è uno sciopero?",           "Is there a strike?"),
            ("Posso lasciare i bagagli?",   "Can I leave my luggage?"),
            ("Sono rimasto/a senza soldi",  "I have run out of money"),
            ("Dov'è il bancomat?",          "Where is the ATM?"),
            ("Che meraviglia!",             "How wonderful!"),
            ("L'Italia mi ha rubato il cuore","Italy has stolen my heart"),
        ],
    },
]

# Flat list of all vocab — for quiz pool
ALL_ITEMS = [pair for lesson in LESSONS for pair in lesson["items"]]


# ─────────────────────────────────────────────────────────────────────────────
#  TEXT-TO-SPEECH  (gTTS — free, no API key)
# ─────────────────────────────────────────────────────────────────────────────
def _make_mp3(text: str) -> str:
    tts = gTTS(text=text, lang="it", slow=False)
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    tts.save(path)
    return path


async def pronounce(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
    path = await asyncio.to_thread(_make_mp3, text)
    try:
        with open(path, "rb") as audio:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio,
                title=text,
                performer="🇮🇹 Italiano Bot",
            )
    finally:
        os.remove(path)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def user_level(user_data: dict) -> str:
    return user_data.get("level", "beginner")


def level_items(level_key: str) -> list:
    lesson_indices = LEVELS[level_key]["lessons"]
    return [pair for i in lesson_indices for pair in LESSONS[i]["items"]]


# ─────────────────────────────────────────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    text = (
        f"Ciao {name}! 👋  Benvenuto/a — I'm *Italiano Bot*, your Italian tutor.\n\n"
        "I'll take you from *zero Italian* all the way to confidently chatting with "
        "locals in Italy 🇮🇹\n\n"
        "*20 lessons across 4 levels:*\n"
        "🟢 Beginner · 🔵 Elementary · 🟡 Pre-Intermediate · 🟠 Intermediate\n\n"
        "*🧠 Spaced Repetition (SRS)*\n"
        "I track every word you learn and bring it back at the *perfect moment* "
        "before you forget it — the same science used by Anki & Duolingo.\n\n"
        "*Commands*\n"
        "🔁 /review — study words due today ← *start here daily*\n"
        "📚 /lessons — browse all 20 lessons\n"
        "🗺 /level — set your level\n"
        "✈️ /travel — travel phrasebook\n"
        "🔊 /say <text> — hear any Italian phrase\n"
        "📝 /quiz — random quiz question\n"
        "📊 /progress — your score & SRS stats\n"
        "❓ /help — show this again\n\n"
        "_Tip: type any Italian text and I'll pronounce it._\n\n"
        "👉 Start with /level, then do /review every day!"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def level_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current = user_level(context.user_data)
    keyboard = []
    for key, info in LEVELS.items():
        label = f"{info['emoji']} {info['label']}"
        if key == current:
            label += " ✅"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"setlevel|{key}")])
    await update.message.reply_text(
        "Choose your level (controls which lessons appear and quiz difficulty):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def lessons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current_level = user_level(context.user_data)
    keyboard = []
    for i, lesson in enumerate(LESSONS):
        lvl = lesson["level"]
        info = LEVELS[lvl]
        # Show all lessons but mark unlocked ones
        label = f"{info['emoji']} {lesson['title']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"lesson|{i}")])
    await update.message.reply_text(
        f"📚 All lessons (your level: {LEVELS[current_level]['emoji']} {LEVELS[current_level]['label']}).\n"
        "Tap any lesson to study it:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def say_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: `/say buongiorno`", parse_mode=ParseMode.MARKDOWN)
        return
    await pronounce(context, update.effective_chat.id, text)


async def travel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick-reference phrasebook for Italy travel scenarios."""
    categories = {
        "✈️ Airport & Arrivals": [
            ("Dove si ritira il bagaglio?", "Where is baggage claim?"),
            ("Ho perso il bagaglio",         "I've lost my luggage"),
            ("Niente da dichiarare",         "Nothing to declare"),
        ],
        "🏨 Hotel": [
            ("Ho una prenotazione",          "I have a reservation"),
            ("La camera non è pronta",       "The room isn't ready"),
            ("Il WiFi funziona?",            "Does the WiFi work?"),
        ],
        "🍕 Restaurant": [
            ("Un tavolo per due",            "A table for two"),
            ("Cosa consiglia?",              "What do you recommend?"),
            ("Il conto, per favore",         "The bill, please"),
        ],
        "🚌 Transport": [
            ("Un biglietto per Roma",        "A ticket to Rome"),
            ("A che ora parte?",             "What time does it leave?"),
            ("Devo convalidare il biglietto?","Do I need to validate the ticket?"),
        ],
        "🆘 Emergency": [
            ("Aiuto!",                       "Help!"),
            ("Chiami la polizia",            "Call the police"),
            ("Ho bisogno di un medico",      "I need a doctor"),
        ],
    }
    lines = ["✈️ *Italy Travel Phrasebook* — tap any phrase to hear it!\n"]
    buttons = []
    for cat, phrases in categories.items():
        lines.append(f"\n*{cat}*")
        for it, en in phrases:
            lines.append(f"  • *{it}* — {en}")
            buttons.append([InlineKeyboardButton(f"🔊 {it}", callback_data=f"sayraw|{it}")])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    score = context.user_data.get("score", 0)
    answered = context.user_data.get("answered", 0)
    level = user_level(context.user_data)
    linfo = LEVELS[level]
    stats = srs_stats(context.user_data)

    if answered == 0:
        await update.message.reply_text(
            "No answers yet — try /review or /quiz 📝\n\n"
            "_Your spaced repetition schedule builds up as you answer questions._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    pct = round(100 * score / answered)
    bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)

    if pct >= 80:
        verdict = "🏆 Magnifico! You're crushing it!"
    elif pct >= 60:
        verdict = "👍 Molto bene! Keep it up!"
    else:
        verdict = "💪 Keep practising — you've got this!"

    msg = (
        f"📊 *Your Progress*\n"
        f"Level: {linfo['emoji']} {linfo['label']}\n\n"
        f"*Quiz accuracy*\n"
        f"Correct: {score}/{answered}  ({pct}%)\n"
        f"[{bar}]\n"
        f"{verdict}\n\n"
        f"*Spaced Repetition (SRS)*\n"
        f"📚 Words seen: {stats['total']}\n"
        f"🔁 Due for review today: {stats['due']}\n"
        f"🧠 Mastered (21+ day interval): {stats['mastered']}\n\n"
        f"_Use /review to study words due today._"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if text:
        await pronounce(context, update.effective_chat.id, text)


# ─────────────────────────────────────────────────────────────────────────────
#  QUIZ ENGINE  (SRS-aware)
# ─────────────────────────────────────────────────────────────────────────────
def build_quiz(level_key: str, user_data: dict) -> dict:
    """
    Pick the next word to quiz:
      1. Prefer cards that are due for SRS review today.
      2. Fall back to random from the level pool.
    """
    due = srs_due_cards(user_data, level_key)
    pool = level_items(level_key) if level_key else ALL_ITEMS
    if len(pool) < 4:
        pool = ALL_ITEMS

    if due:
        italian, english = random.choice(due)
    else:
        italian, english = random.choice(pool)

    ask_meaning = random.random() < 0.5

    if ask_meaning:
        prompt = f"🇮🇹➡️🇬🇧  What does *{italian}* mean?"
        correct = english
        distractors = [en for (_, en) in pool if en != english]
    else:
        prompt = f"🇬🇧➡️🇮🇹  How do you say *{english}* in Italian?"
        correct = italian
        distractors = [it for (it, _) in pool if it != italian]

    options = random.sample(distractors, min(3, len(distractors))) + [correct]
    random.shuffle(options)
    return {
        "prompt": prompt,
        "correct": correct,
        "options": options,
        "italian": italian,
        "is_srs": bool(due),
    }


async def send_quiz(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_data: dict) -> None:
    quiz = build_quiz(user_level(user_data), user_data)
    user_data["quiz"] = quiz

    due_count = len(srs_due_cards(user_data, user_level(user_data)))
    header = f"🔁 *Review* ({due_count} due)\n" if quiz["is_srs"] else ""

    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"ans|{i}")]
        for i, opt in enumerate(quiz["options"])
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=header + quiz["prompt"],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_quiz(context, update.effective_chat.id, context.user_data)


async def review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a focused SRS review session (due cards only)."""
    due = srs_due_cards(context.user_data, user_level(context.user_data))
    if not due:
        await update.message.reply_text(
            "🎉 *Ottimo!* No words due for review right now.\n"
            "Come back tomorrow — your next session will be ready then!\n\n"
            "Want a random /quiz in the meantime?",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"🔁 *Review session* — {len(due)} word(s) due today.\nLet's go!",
        parse_mode=ParseMode.MARKDOWN,
    )
    await send_quiz(context, update.effective_chat.id, context.user_data)


# ─────────────────────────────────────────────────────────────────────────────
#  CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────────────────────
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # ── set level ────────────────────────────────────────────────────────────
    if data.startswith("setlevel|"):
        key = data.split("|")[1]
        context.user_data["level"] = key
        info = LEVELS[key]
        lesson_range = f"L{info['lessons'][0]+1:02d}–L{info['lessons'][-1]+1:02d}"
        await query.message.reply_text(
            f"{info['emoji']} Level set to *{info['label']}* ({lesson_range}).\n"
            "Quizzes will now use vocabulary from this level.\n\n"
            "👉 /lessons to study · /quiz to practise",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── show lesson ──────────────────────────────────────────────────────────
    if data.startswith("lesson|"):
        idx = int(data.split("|")[1])
        lesson = LESSONS[idx]

        # Seed every word in this lesson into the user's SRS deck (first-time only)
        for italian, _ in lesson["items"]:
            srs_seed(context.user_data, italian)
        newly_seeded = len(lesson["items"])

        lines = [f"*{lesson['title']}*"]
        if lesson.get("tip"):
            lines.append(f"\n{lesson['tip']}\n")
        for it, en in lesson["items"]:
            lines.append(f"• *{it}* — {en}")
        lines.append(f"\n_✅ {newly_seeded} words added to your review deck!_")
        buttons = [
            [InlineKeyboardButton(f"🔊 {it}", callback_data=f"say|{idx}|{i}")]
            for i, (it, _) in enumerate(lesson["items"])
        ]
        buttons.append([InlineKeyboardButton("🔁 Review these words now", callback_data="newquiz")])
        # Split into chunks to avoid Telegram's 4096-char limit
        full = "\n".join(lines)
        if len(full) > 4000:
            mid = len(lines) // 2
            await query.message.reply_text("\n".join(lines[:mid]), parse_mode=ParseMode.MARKDOWN)
            await context.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines[mid:]),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            await query.message.reply_text(
                full,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return

    # ── pronounce lesson item ─────────────────────────────────────────────────
    if data.startswith("say|"):
        _, li, ii = data.split("|")
        italian = LESSONS[int(li)]["items"][int(ii)][0]
        await pronounce(context, chat_id, italian)
        return

    # ── pronounce raw text (travel phrasebook) ───────────────────────────────
    if data.startswith("sayraw|"):
        text = data[len("sayraw|"):]
        await pronounce(context, chat_id, text)
        return

    # ── new quiz question ─────────────────────────────────────────────────────
    if data == "newquiz":
        await send_quiz(context, chat_id, context.user_data)
        return

    # ── hear current quiz word ────────────────────────────────────────────────
    if data == "hearquiz":
        quiz = context.user_data.get("quiz")
        if quiz:
            await pronounce(context, chat_id, quiz["italian"])
        return

    # ── answer quiz question ──────────────────────────────────────────────────
    if data.startswith("ans|"):
        quiz = context.user_data.get("quiz")
        if not quiz:
            await query.message.reply_text("Quiz expired — send /quiz for a new one.")
            return
        chosen = quiz["options"][int(data.split("|")[1])]
        correct = quiz["correct"]
        italian = quiz["italian"]

        context.user_data["answered"] = context.user_data.get("answered", 0) + 1

        if chosen == correct:
            context.user_data["score"] = context.user_data.get("score", 0) + 1
            quality = 5
            result = f"✅ *Esatto!*  The answer is *{correct}*"
        else:
            quality = 1
            result = (
                f"❌ Not quite.\n"
                f"You chose: *{chosen}*\n"
                f"Correct: *{correct}*"
            )

        # Update SRS card
        card = srs_update(context.user_data, italian, quality)
        due_days = card["interval"]
        streak = card["streak"]

        if quality >= 3:
            if due_days == 1:
                srs_line = f"🔁 Review again *tomorrow*"
            elif due_days <= 7:
                srs_line = f"🔁 Next review in *{due_days} days*  (streak: {streak} ✨)"
            else:
                srs_line = f"🧠 Well known! Next review in *{due_days} days*  (streak: {streak} 🔥)"
        else:
            srs_line = "🔁 Added back to *review tomorrow* — you'll nail it next time!"

        # Check remaining due cards
        due_left = len(srs_due_cards(context.user_data, user_level(context.user_data)))
        due_line = f"\n_{due_left} card(s) still due today_" if due_left > 0 else "\n_All reviews done for today! 🎉_"

        follow = [[
            InlineKeyboardButton("🔊 Hear it", callback_data="hearquiz"),
            InlineKeyboardButton("➡️ Next", callback_data="newquiz"),
        ]]
        await query.edit_message_text(
            f"{quiz['prompt']}\n\n{result}\n\n{srs_line}{due_line}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(follow),
        )
        return



# ─────────────────────────────────────────────────────────────────────────────
#  KEEP-ALIVE HTTP SERVER
#  Render free Web Services need an HTTP port to stay alive.
#  This tiny server runs in a background thread and answers /health.
#  Point cron-job.org at  https://<your-app>.onrender.com/health  every 10 min
#  to prevent the free-tier sleep.
# ─────────────────────────────────────────────────────────────────────────────
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK - Italiano Bot is running!"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # silence HTTP access logs


def _start_health_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    print(f"🌐 Health endpoint listening on port {port}")
    server.serve_forever()


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    if BOT_TOKEN.startswith("PASTE_"):
        raise SystemExit(
            "❗ Set your bot token first:\n"
            '   export BOT_TOKEN="your-token-here"'
        )

    # ── 1. Start HTTP keep-alive server FIRST (Render checks port on startup) ─
    t = threading.Thread(target=_start_health_server, daemon=True)
    t.start()

    # ── 2. Use /tmp for pickle — writable on Render's ephemeral filesystem ────
    #       (scores reset on redeploy; acceptable for a free-tier bot)
    pickle_path = os.environ.get("PICKLE_PATH", "/tmp/italiano_bot_data.pickle")
    persistence = PicklePersistence(filepath=pickle_path)

    # ── 3. Build app with error handler so crashes are logged, not silent ─────
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        import traceback
        print(f"❌ Exception:\n{''.join(traceback.format_exception(None, context.error, context.error.__traceback__))}")

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_cmd))
    app.add_handler(CommandHandler("lessons",  lessons_cmd))
    app.add_handler(CommandHandler("level",    level_cmd))
    app.add_handler(CommandHandler("travel",   travel_cmd))
    app.add_handler(CommandHandler("say",      say_cmd))
    app.add_handler(CommandHandler("quiz",     quiz_cmd))
    app.add_handler(CommandHandler("review",   review_cmd))
    app.add_handler(CommandHandler("progress", progress_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_text))

    print("🇮🇹 Italiano Bot is running — 20 lessons, 4 levels. Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # ignore messages sent while bot was offline
    )


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────────────
#  OPTIONAL: nicer neural voices with edge-tts (still free, no key)
# ─────────────────────────────────────────────────────────────────────────────
#  pip install edge-tts
#
#  import edge_tts
#  async def _make_mp3_edge(text: str) -> str:
#      fd, path = tempfile.mkstemp(suffix=".mp3")
#      os.close(fd)
#      communicate = edge_tts.Communicate(text, voice="it-IT-IsabellaNeural")
#      await communicate.save(path)
#      return path
#
#  # In pronounce(): replace
#  #   path = await asyncio.to_thread(_make_mp3, text)
#  # with
#  #   path = await _make_mp3_edge(text)
# ─────────────────────────────────────────────────────────────────────────────
