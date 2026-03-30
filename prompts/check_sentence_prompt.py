def get_check_sentence_prompt(tense_name: str, user_sentence: str) -> str:
    return f"""<context>
Target tense: {tense_name}
Student's sentence: "{user_sentence}"
</context>

<task>
Check if the student's sentence correctly uses {tense_name}.
Determine what tense was actually used.
If incorrect, provide a corrected version using {tense_name}.
Write encouraging feedback in Russian (2-3 sentences max).
</task>

<guidelines>
If the sentence is grammatically correct but uses the wrong tense, mark is_correct as false.
If there are minor spelling mistakes but the tense is correct, mark is_correct as true and mention the typo in feedback.
Be encouraging and supportive in feedback. Explain the mistake gently.
If correct, praise the student and briefly explain why the tense fits.
</guidelines>"""
