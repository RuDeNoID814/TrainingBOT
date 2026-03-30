def get_find_error_prompt(tense_name: str, formula: str, markers: str, used_sentences: list[str] | None = None) -> str:
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
Generate a "find the error" question for the tense {tense_name}.
Write an English sentence that INCORRECTLY uses a verb tense. The sentence should use the WRONG tense where {tense_name} is required.
The student must identify the correct version using {tense_name}.
Provide exactly 4 options: 1 correct fix using {tense_name} and 3 wrong alternatives.
Write a short explanation in Russian why the original sentence is wrong and why the correct answer fits.
</task>

<guidelines>
The sentence must contain a time marker that clearly indicates {tense_name} should be used.
The error should be a wrong tense (e.g., Past Simple instead of Present Perfect), NOT a spelling or grammar error.
Use a unique real-life scenario: travel, work, hobbies, food, weather, technology, sports, health.
Choose diverse subjects — not just "She" or "He".
Keep the sentence natural, 8-15 words, at B1-B2 level.
The "sentence" field must contain the INCORRECT sentence (with the error).
The "correct" field must contain the corrected verb form.
The explanation in Russian must be 1-2 sentences.
</guidelines>"""
