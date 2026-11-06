CASE_TITLE = "The Midnight Diamond"

CASE_BRIEF = (
    "At 11:40 PM last night the 'Star of the East' diamond vanished from the City Museum's "
    "east wing. The alarm was cut for exactly four minutes. CCTV shows you entering the museum "
    "at 10:55 PM for the late-night gala, and nobody saw you leave until 11:52 PM. "
    "You are the suspect. Inspector Noor has a few questions."
)

QUESTION_COUNT = 6

OPENING_QUESTION = "Let's start simple. Why were you at the museum last night?"

# Used when the LLM is slow or unavailable, so the game never stalls.
FALLBACK_QUESTIONS = [
    "Where exactly were you between 11:30 and 11:45 PM?",
    "Did you go anywhere near the east wing?",
    "Who can confirm where you were when the alarm went dark?",
    "A guard says he saw someone in a dark jacket by the display case. What were you wearing?",
    "Why did it take you almost an hour to leave after the gala ended?",
    "If I searched your bag right now, what would I find?",
]
