"""sanitize_for_tts: symbols become words, quote marks go, apostrophes inside
words stay (stripping them made the voice say "tonight s").

    uv run python tests/test_sanitize.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.synth import sanitize_for_tts

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


check("a possessive keeps its apostrophe",
      sanitize_for_tts("That is tonight's bulletin.") == "That is tonight's bulletin.")
check("a curly apostrophe becomes a straight one and stays",
      sanitize_for_tts("the company’s ambitions") == "the company's ambitions")
check("a contraction keeps its apostrophe",
      sanitize_for_tts("don't stop") == "don't stop")
check("single quote marks around a word are removed",
      sanitize_for_tts("He said 'no' and ‘yes’.") == "He said no and yes.")
check("double quote marks are removed",
      sanitize_for_tts("“Quoted” text") == "Quoted text")
check("dollar amounts are spoken as words",
      sanitize_for_tts("sales of $1.2 billion") == "sales of 1.2 billion dollars")

print(f"\n{checks} checks passed")
