"""Russian names of the opening families. The part after ":" (the variation) stays in English."""

# Key: the family name without apostrophes (the puzzle tags have none).
FAMILIES = {
    "Sicilian Defense": "Сицилианская защита",
    "French Defense": "Французская защита",
    "Caro-Kann Defense": "Защита Каро — Канн",
    "Scandinavian Defense": "Скандинавская защита",
    "Pirc Defense": "Защита Пирца — Уфимцева",
    "Alekhine Defense": "Защита Алёхина",
    "Nimzowitsch Defense": "Защита Нимцовича против 1.e4",
    "Philidor Defense": "Защита Филидора",
    "Modern Defense": "Современная защита",
    "Owen Defense": "Защита Оуэна",
    "Russian Game": "Русская партия",  # the puzzle tags
    "Petrovs Defense": "Русская партия",  # the same opening in the openings book
    "Two Knights Defense": "Защита двух коней",
    "Italian Game": "Итальянская партия",
    "Scotch Game": "Шотландская партия",
    "Ruy Lopez": "Испанская партия",
    "Four Knights Game": "Партия четырёх коней",
    "Vienna Game": "Венская партия",
    "Ponziani Opening": "Партия Понциани",
    "Bishops Opening": "Дебют слона",
    "Kings Pawn Game": "Дебют королевской пешки",
    "Queens Pawn Game": "Дебют ферзевой пешки",
    "Kings Gambit": "Королевский гамбит",
    "Kings Gambit Accepted": "Принятый королевский гамбит",
    "Kings Gambit Declined": "Отказанный королевский гамбит",
    "Queens Gambit": "Ферзевый гамбит",
    "Queens Gambit Accepted": "Принятый ферзевый гамбит",
    "Queens Gambit Declined": "Отказанный ферзевый гамбит",
    "Slav Defense": "Славянская защита",
    "Semi-Slav Defense": "Полуславянская защита",
    "Indian Defense": "Индийская защита",
    "Kings Indian Defense": "Староиндийская защита",
    "Kings Indian Attack": "Староиндийская атака",
    "Nimzo-Indian Defense": "Защита Нимцовича",
    "Grunfeld Defense": "Защита Грюнфельда",
    "Benoni Defense": "Защита Бенони",
    "Dutch Defense": "Голландская защита",
    "English Opening": "Английское начало",
    "Bird Opening": "Дебют Берда",
    "Polish Opening": "Дебют Сокольского",
    "Trompowsky Attack": "Атака Тромповского",
    "Danish Gambit": "Датский гамбит",
    "Englund Gambit": "Гамбит Энглунда",
    "Blackmar-Diemer Gambit": "Гамбит Блэкмара — Димера",
}


def ru_name(name: str) -> str:
    """ "Sicilian Defense: Najdorf Variation" -> "Сицилианская защита: Najdorf Variation"."""
    family, sep, rest = name.partition(":")
    ru = FAMILIES.get(family.replace("'", ""))
    return f"{ru}{sep}{rest}" if ru else name
