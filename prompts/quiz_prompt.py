def get_quiz_prompt(tense_name: str, formula: str, markers: str, used_sentences: list[str] | None = None) -> str:
    # Контекст — что уже было (анти-повтор)
    avoid_block = ""
    if used_sentences:
        examples = "; ".join(used_sentences[-10:])
        avoid_block = f"\n<already_used>\n{examples}\n</already_used>\n"

    return f"""<context>
Target tense: {tense_name}
Formula: {formula}
Time markers: {markers}
</context>
{avoid_block}
<task>
Generate one multiple-choice question to test the tense {tense_name}.
Write an English sentence with a blank (___) where the verb should be. Include the base verb in parentheses.
Provide exactly 4 answer options: 1 correct answer using {tense_name} and 3 wrong but plausible distractors from other tenses.
Write a short explanation in Russian why the correct answer fits, mentioning the tense name and the time marker in the sentence.
</task>

<guidelines>
Use a unique real-life scenario: travel, work, hobbies, food, weather, technology, sports, health, music, nature, science, relationships.
Choose a subject other than "Mark", "She", "He" — use diverse names, professions, or group subjects.
Use a different verb and context from any sentence in <already_used>.
Keep the sentence natural, 8-15 words, at B1-B2 level.
The explanation in Russian must be 1-2 sentences, mention the tense name and the time marker from the sentence.
</guidelines>"""
