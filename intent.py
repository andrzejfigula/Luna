"""
intent.py — is a sentence asking for something, or just mentioning it?

"Szum morza mnie uspokaja", "Babcia opowiadała mi bajki na dobranoc",
"Lustro w łazience jest brudne" name a feature without asking for it; the
local triggers used to start it anyway. asked() says yes for a short command
("szum morza", "lustro") or a sentence with a request word in it ("włącz szum
morza", "opowiedz mi bajkę na dobranoc", "pokaż lustro").
"""

import re

_REQUEST = re.compile(
    r"\b(?:pokaż|pokaz|pokażesz|włącz|wlacz|puść|pusc|zagraj|zagrajmy|daj|dasz|zróbmy|"
    r"zrobmy|zrób|zrob|zrobisz|pobawmy|chcę|chce|chcemy|możesz|mozesz|mogłabyś|"
    r"moglabys|poproszę|poprosze|proszę|prosze|opowiedz|opowiesz|poczytaj|przeczytaj|"
    r"wymyśl|wymysl|pomóż|pomoz|pomożesz|zacznij|zacznijmy|nastaw|ustaw|start|startuj|"
    r"poćwiczmy|pocwiczmy|potrzebuję|potrzebuje|uruchom|odpal|teraz|chodź|chodz)\b",
    re.I)


def asked(text, bare=3):
    """True for a request: at most `bare` words, or a request word in it."""
    if len(re.findall(r"\w+", text)) <= bare:
        return True
    return bool(_REQUEST.search(text))
