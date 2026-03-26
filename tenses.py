TENSES = {
    "present_simple": {
        "name": "Present Simple",
        "formula": "Подлежащее + глагол (he/she/it — добавляем -s)",
        "markers": "always, every day, usually, often, sometimes, never",
        "example": "She goes to school every day. — Она ходит в школу каждый день.",
        "forms": (
            "✅ Утверждение: I work / He works\n"
            "❌ Отрицание: I don't work / He doesn't work\n"
            "❓ Вопрос: Do I work? / Does he work?"
        ),
    },
    "present_continuous": {
        "name": "Present Continuous",
        "formula": "Подлежащее + am/is/are + глагол с -ing",
        "markers": "now, right now, at the moment, currently, look!, listen!",
        "example": "She is reading a book right now. — Она читает книгу прямо сейчас.",
        "forms": (
            "✅ Утверждение: I am working / He is working\n"
            "❌ Отрицание: I am not working / He isn't working\n"
            "❓ Вопрос: Am I working? / Is he working?"
        ),
    },
    "present_perfect": {
        "name": "Present Perfect",
        "formula": "Подлежащее + have/has + глагол в 3-й форме",
        "markers": "already, just, yet, ever, never, since, for, recently",
        "example": "I have finished my work. — Я закончил свою работу.",
        "forms": (
            "✅ Утверждение: I have done / He has done\n"
            "❌ Отрицание: I haven't done / He hasn't done\n"
            "❓ Вопрос: Have I done? / Has he done?"
        ),
    },
    "present_perfect_continuous": {
        "name": "Present Perfect Continuous",
        "formula": "Подлежащее + have/has been + глагол с -ing",
        "markers": "for, since, all day, all morning, lately, recently",
        "example": "He has been working all day. — Он работает весь день (и продолжает).",
        "forms": (
            "✅ Утверждение: I have been working\n"
            "❌ Отрицание: I haven't been working\n"
            "❓ Вопрос: Have I been working?"
        ),
    },
    "past_simple": {
        "name": "Past Simple",
        "formula": "Подлежащее + глагол во 2-й форме (или did + глагол)",
        "markers": "yesterday, last week/month/year, ago, in 2020, then",
        "example": "They visited London last year. — Они посещали Лондон в прошлом году.",
        "forms": (
            "✅ Утверждение: I worked / He went\n"
            "❌ Отрицание: I didn't work / He didn't go\n"
            "❓ Вопрос: Did I work? / Did he go?"
        ),
    },
    "past_continuous": {
        "name": "Past Continuous",
        "formula": "Подлежащее + was/were + глагол с -ing",
        "markers": "while, when, at 5pm yesterday, at that moment, all day",
        "example": "I was sleeping at midnight. — Я спал в полночь (в процессе).",
        "forms": (
            "✅ Утверждение: I was working / They were working\n"
            "❌ Отрицание: I wasn't working / They weren't working\n"
            "❓ Вопрос: Was I working? / Were they working?"
        ),
    },
    "past_perfect": {
        "name": "Past Perfect",
        "formula": "Подлежащее + had + глагол в 3-й форме",
        "markers": "before, by the time, after, already, just, never",
        "example": "She had left before I came. — Она ушла до того, как я пришёл.",
        "forms": (
            "✅ Утверждение: I had worked\n"
            "❌ Отрицание: I hadn't worked\n"
            "❓ Вопрос: Had I worked?"
        ),
    },
    "past_perfect_continuous": {
        "name": "Past Perfect Continuous",
        "formula": "Подлежащее + had been + глагол с -ing",
        "markers": "for, since, before, by the time, all day",
        "example": "We had been waiting for 2 hours. — Мы ждали уже 2 часа (к тому моменту).",
        "forms": (
            "✅ Утверждение: I had been working\n"
            "❌ Отрицание: I hadn't been working\n"
            "❓ Вопрос: Had I been working?"
        ),
    },
    "future_simple": {
        "name": "Future Simple",
        "formula": "Подлежащее + will + глагол",
        "markers": "tomorrow, next week, soon, in 2030, I think, probably",
        "example": "I will call you tomorrow. — Я позвоню тебе завтра.",
        "forms": (
            "✅ Утверждение: I will work\n"
            "❌ Отрицание: I won't work\n"
            "❓ Вопрос: Will I work?"
        ),
    },
    "future_continuous": {
        "name": "Future Continuous",
        "formula": "Подлежащее + will be + глагол с -ing",
        "markers": "at this time tomorrow, at 8pm tonight, all day tomorrow",
        "example": "She will be sleeping at 10pm. — Она будет спать в 10 вечера (в процессе).",
        "forms": (
            "✅ Утверждение: I will be working\n"
            "❌ Отрицание: I won't be working\n"
            "❓ Вопрос: Will I be working?"
        ),
    },
    "future_perfect": {
        "name": "Future Perfect",
        "formula": "Подлежащее + will have + глагол в 3-й форме",
        "markers": "by tomorrow, by next year, by the time, before",
        "example": "He will have graduated by June. — Он закончит учёбу к июню.",
        "forms": (
            "✅ Утверждение: I will have worked\n"
            "❌ Отрицание: I won't have worked\n"
            "❓ Вопрос: Will I have worked?"
        ),
    },
    "future_perfect_continuous": {
        "name": "Future Perfect Continuous",
        "formula": "Подлежащее + will have been + глагол с -ing",
        "markers": "by, for (в контексте будущего), by the time",
        "example": "I will have been working for 5 years. — Я буду работать уже 5 лет (к тому моменту).",
        "forms": (
            "✅ Утверждение: I will have been working\n"
            "❌ Отрицание: I won't have been working\n"
            "❓ Вопрос: Will I have been working?"
        ),
    },
}

TENSE_GROUPS = {
    "present": ["present_simple", "present_continuous", "present_perfect", "present_perfect_continuous"],
    "past": ["past_simple", "past_continuous", "past_perfect", "past_perfect_continuous"],
    "future": ["future_simple", "future_continuous", "future_perfect", "future_perfect_continuous"],
}
