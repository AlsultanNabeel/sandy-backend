#!/usr/bin/env python3
"""Generate ESP-SR MultiNet (English) phoneme strings for command phrases.

The English MultiNet model matches PHONEMES, not plain text, so every phrase in
the SANDY_COMMANDS table in main/sandy_voice.c needs a phoneme string. This
prints one for each phrase you pass — paste it into the table's `phonemes` field.

Usage (run inside the ESP-IDF python env, or any env with g2p_en):
    python tools/gen_phonemes.py "SANDY TURN ON THE LIGHT" "SANDY FAN OFF"

Output:
    SANDY TURN ON THE LIGHT  ->  "SaNDm TkN nN jc LiT"

Setup once:  pip install g2p_en   (first run downloads a little nltk data).
The alphabet map below is Espressif's (from managed_components/.../tool/multinet_g2p.py).
"""
import sys

try:
    import nltk
    for pkg in ("averaged_perceptron_tagger_eng", "cmudict"):
        nltk.download(pkg, quiet=True)
    from g2p_en import G2p
except ImportError:
    sys.exit("Missing dep. Run: pip install g2p_en   then rerun.")

ALPHABET = {
    "AE1": "a", "N": "N", " ": " ", "OW1": "b", "V": "V", "AH0": "c", "L": "L",
    "F": "F", "EY1": "d", "S": "S", "B": "B", "R": "R", "AO1": "e", "D": "D",
    "AH1": "c", "EH1": "f", "OW0": "b", "IH0": "g", "G": "G", "HH": "h", "K": "K",
    "IH1": "g", "W": "W", "AY1": "i", "T": "T", "M": "M", "Z": "Z", "DH": "j",
    "ER0": "k", "P": "P", "NG": "l", "IY1": "m", "AA1": "n", "Y": "Y", "UW1": "o",
    "IY0": "m", "EH2": "f", "CH": "p", "AE0": "a", "JH": "q", "ZH": "r", "AA2": "n",
    "SH": "s", "AW1": "t", "OY1": "u", "AW2": "t", "IH2": "g", "AE2": "a",
    "EY2": "d", "ER1": "k", "TH": "v", "UH1": "w", "UW2": "o", "OW2": "b",
    "AY2": "i", "UW0": "o", "AH2": "c", "EH0": "f", "AW0": "t", "AO2": "e",
    "AO0": "e", "UH0": "w", "UH2": "w", "AA0": "n", "AY0": "i", "IY2": "m",
    "EY0": "d", "ER2": "k", "OY2": "u", "OY0": "u",
}

if len(sys.argv) < 2:
    sys.exit('Pass one or more phrases, e.g.: python tools/gen_phonemes.py "SANDY FAN ON"')

g2p = G2p()
for phrase in sys.argv[1:]:
    out = "".join(ALPHABET[c] for c in g2p(phrase) if c in ALPHABET)
    print(f'{phrase}  ->  "{out}"')
