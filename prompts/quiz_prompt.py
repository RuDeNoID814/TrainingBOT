def get_quiz_prompt(tense_name: str, formula: str, markers: str) -> str:
    return f"""You are an English grammar quiz generator.

Generate ONE multiple-choice question to test the tense: {tense_name}.
Formula: {formula}
Time markers: {markers}

Rules:
- Write a sentence in English with a blank (use "___") where the verb should be.
- Provide the base verb in parentheses after the sentence.
- Give exactly 4 answer options: 1 correct and 3 wrong (plausible distractors from other tenses).
- The correct answer MUST use the {tense_name} tense.
- Add a short explanation in Russian why this answer is correct.
- Use varied vocabulary and real-life contexts. Do NOT repeat examples.

Respond ONLY with valid JSON, no markdown, no extra text:
{{
  "sentence": "She ___ (to read) a book right now.",
  "correct": "is reading",
  "options": ["is reading", "reads", "has read", "was reading"],
  "explanation_ru": "Используем Present Continuous (is reading), потому что действие происходит прямо сейчас — маркер 'right now'."
}}"""
