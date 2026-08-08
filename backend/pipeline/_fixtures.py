"""Deterministic stand-ins used when ``MOCK=1``.

These exist so the wiring (stage order, progress reporting, caption timing,
render flags) can be exercised end-to-end without a Deepgram or Anthropic key.
They are not a quality signal -- judging selection quality needs real audio.
"""

from __future__ import annotations

MOCK_SPEECH = """
Everyone tells you to wake up at five in the morning. I did it for two years
and it nearly broke me. Here is what nobody says about it. The hour you wake up
matters far less than the hour you stop. I was getting up at five and still
answering messages at midnight, so I was running a four hour sleep debt and
calling it discipline. The turning point was a conversation with my old boss.
He asked me one question. He said, what time do you close the laptop? And I did
not have an answer. That was the whole problem in one sentence. So I flipped it.
I stopped setting a wake up alarm and I set a shutdown alarm instead. Nine
fifteen every night, the laptop closes, no exceptions, no just one more thing.
Within three weeks I was waking up at six thirty on my own without an alarm at
all. My output went up, not down. The work I did in the morning was sharper
because I had actually rested. Here is the part that surprised me the most.
The people I admire who seem impossibly productive are not grinding harder than
everyone else. They have simply decided in advance when they are done. That
decision is the whole trick. You are not lazy for stopping. You are protecting
the thing that makes the work good in the first place. If you take one thing
from this conversation, take that. Set the shutdown alarm, not the wake up
alarm, and watch what happens to your energy in a month.
""".strip()


# Metadata only. Timestamps are derived from the actual fixture transcript at
# runtime so mock candidates are always inside the media and land on real
# sentence boundaries -- hardcoded times drift the moment the script changes.
MOCK_CLIP_META: list[dict[str, object]] = [
    {
        "hook_score": 9,
        "title": "Why waking up at 5am nearly broke me",
        "reason": "Opens by contradicting common advice, then promises the untold cost.",
    },
    {
        "hook_score": 8,
        "title": "The one question that exposed my burnout",
        "reason": "Sets up a question, delivers the answer, complete arc.",
    },
    {
        "hook_score": 7,
        "title": "I set a shutdown alarm instead of a wake-up alarm",
        "reason": "Concrete, repeatable tactic with a specific time attached.",
    },
    {
        "hook_score": 8,
        "title": "Productive people aren't grinding harder",
        "reason": "Reframes a belief the audience holds, lands on a clean takeaway.",
    },
]
