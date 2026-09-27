"""apply_pronunciations: whole-word IPA markup for names Kokoro says wrong.

    uv run python tests/test_pronunciations.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.synth import apply_pronunciations, sanitize_for_tts

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


PRON = {"Adidas": "əˈdidəs"}

check("a plain whole-word match gets IPA markup",
      apply_pronunciations("Adidas sales rose.", PRON) == "[Adidas](/əˈdidəs/) sales rose.")
check("a substring hit is left alone",
      apply_pronunciations("Adidasx sales rose.", PRON) == "Adidasx sales rose.")
check("a possessive keeps its 's outside the markup",
      apply_pronunciations("Adidas's ambitions", PRON)
      == "[Adidas](/əˈdidəs/)'s ambitions")
check("the bare-apostrophe possessive left by sanitize_for_tts is a plain word, still matched",
      apply_pronunciations(sanitize_for_tts("Adidas' European sales"), PRON)
      == "[Adidas](/əˈdidəs/) European sales")
check("an empty pronunciation list is a no-op",
      apply_pronunciations("Adidas sales rose.", {}) == "Adidas sales rose.")
check("text with no matching word passes through unchanged",
      apply_pronunciations("Nike sales rose.", PRON) == "Nike sales rose.")

print(f"\n{checks} checks passed")
