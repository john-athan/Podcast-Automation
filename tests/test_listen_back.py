"""The listen-back normaliser and WER: identical/substitution/deletion/empty
cases, number spelling, and the flagging threshold. No model involved.

    uv run python tests/test_listen_back.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.listen_back import normalize_for_wer, word_error_rate

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


def wer(sent: str, transcript: str) -> float:
    rate, _ = word_error_rate(normalize_for_wer(sent), normalize_for_wer(transcript))
    return rate


check("identical text is zero WER", wer("Good evening to you all.", "Good evening to you all.") == 0.0)

check("one substitution costs one word over the reference length",
      wer("the DAX rose today", "the DAX fell today") == 1 / 4)

check("one deletion costs one word over the reference length",
      wer("the DAX rose sharply today", "the DAX rose today") == 1 / 5)

check("an empty transcript against real text is total loss",
      wer("Story one starts here.", "") == 1.0)

check("two empty sides have nothing to compare, zero WER", wer("", "") == 0.0)

check("digits and their spoken form normalise the same way",
      normalize_for_wer("5.28 million dollars") == normalize_for_wer("five point two eight million dollars"))
check("a comma thousands separator normalises like the plain number",
      normalize_for_wer("1,000 dollars") == normalize_for_wer("1000 dollars"))
check("number normalisation makes the WER of an otherwise-perfect read zero",
      wer("shares rose 15 percent to 1,000 dollars",
          "shares rose fifteen percent to one thousand dollars") == 0.0)

diffs = word_error_rate(["the", "dax", "fell"], ["the", "dax", "rose"])[1]
check("the alignment reports the differing word, not just the count",
      diffs == [{"op": "sub", "ref": "fell", "hyp": "rose"}])

check("case and punctuation are ignored",
      wer("The DAX rose, sharply!", "the dax rose sharply") == 0.0)

from podcast.listen_back import join_split_compounds, missed_names

check("a currency symbol reads back as the spoken word",
      wer("sales rose to 1.2 billion dollars", "sales rose to $1.2 billion") == 0.0)
check("euros and pounds read back the same way",
      wer("a fine of 40 million euros", "a fine of \u20ac40 million") == 0.0)


def wer_joined(sent: str, transcript: str) -> float:
    ref, hyp = normalize_for_wer(sent), normalize_for_wer(transcript)
    ref, hyp = join_split_compounds(ref, hyp), join_split_compounds(hyp, ref)
    return word_error_rate(ref, hyp)[0]


check("a compound the transcriber splits is not two errors",
      wer_joined("winds out of the northwest today", "winds out of the north west to day") == 0.0)
check("a real substitution still counts after compound joining",
      wer_joined("winds out of the northwest", "winds out of the southwest") == 1 / 5)

sent = "Adidas chief executive Bjorn Gulden said the German maker grew."
ops = word_error_rate(normalize_for_wer(sent),
                      normalize_for_wer("And did chief executive Bjorn Golden said the German maker grew."))[1]
check("a misheard name is reported, even at the start of a sentence",
      missed_names(sent, ops) == ["adidas", "gulden"])
check("sentence openers are not names",
      missed_names("The market fell. In Munich it rained.",
                   word_error_rate(["the", "market"], ["a", "market"])[1]) == [])

# Flagging threshold: LISTEN_BACK_WER_MAX gates which turns get flagged, not
# whether they get resynthesized (that stays a human decision).
from podcast.config import LISTEN_BACK_WER_MAX

check("a turn right at the default gate reads as not-flagged, one above it flags",
      not (0.15 > LISTEN_BACK_WER_MAX) and (0.16 > LISTEN_BACK_WER_MAX))

print(f"\n{checks} checks passed")
