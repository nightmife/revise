from revise.engines.simple import cards_from_page, title_from_filename

SLIDE_DEF = """Principe d'une pile
• Une pile est une structure de donnée où seul un élément
est accessible à la fois : le sommet de la pile
• LIFO en anglais (Last In First Out)
3
"""

SLIDE_SPEC = """Module Pile
• Procédure dépiler ()
• Précondition : la pile n'est pas vide
• Postcondition : le sommet de la pile est dépilé
• Fonction estVide () : booléen
• Résultat : vrai si la pile est vide, faux sinon
5
"""


def questions(cards):
    return [c.question for c in cards]


def test_sentence_definition_and_cloze():
    cards = cards_from_page(SLIDE_DEF, 3)
    qa = [c for c in cards if c.kind == "qa" and "Qu'est-ce" in c.question]
    assert qa[0].question == "Qu'est-ce que « pile » ?"
    assert qa[0].answer.startswith("une structure de donnée")
    assert "accessible à la fois" in qa[0].answer  # ligne coupée recollée
    cloze = [c for c in cards if c.kind == "cloze"]
    assert cloze and "[…]" in cloze[0].question and cloze[0].answer == "pile"
    assert all(c.page == 3 and c.section == "Principe d'une pile" for c in cards)


def test_spec_labels_use_context_line():
    qs = questions(cards_from_page(SLIDE_SPEC, 5))
    assert "Procédure dépiler () — précondition ?" in qs
    assert "Procédure dépiler () — postcondition ?" in qs
    assert "Fonction estVide () : booléen — résultat ?" in qs
    assert not any(q.startswith("Qu'est-ce que « Précondition") for q in qs)


def test_bullet_summary_card():
    text = "Implémentation d'une pile\n• Par une liste chaînée\n• Par un tableau dynamique\n• Par un tableau statique\n"
    cards = cards_from_page(text, 7)
    assert any(c.question == "Quels sont les points clés de « Implémentation d'une pile » ?" and
               c.answer.count("\n") == 2 for c in cards)


def test_statement_block():
    text = "Complexité\nThéorème (borne inférieure) : tout tri par comparaisons\nfait au moins n log n comparaisons\n"
    cards = cards_from_page(text, 9)
    st = [c for c in cards if c.question.startswith("Énonce")]
    assert st and "borne inférieure" in st[0].question and "n log n" in st[0].answer


def test_skipped_pages_and_noise():
    assert cards_from_page("Plan\n• Introduction\n• Piles\n• Files\n", 2) == []
    assert cards_from_page("12\n", 12) == []
    q = cards_from_page("Exercice\n• Quel est l'invariant de boucle pour le tri ?\n", 4)
    assert not any("Quel" in c.question for c in q)
    # variables de pseudo-code et termes tronqués ignorés
    q = questions(cards_from_page("Exemple\n• p : Pile, s : entier\n• Procédure tri (tab : tableau de réels)\n", 6))
    assert not any("« p »" in x or "« Procédure tri (tab" in x for x in q)


def test_title_from_filename():
    assert title_from_filename("[LIFAPSD] CM8 - Pile et file") == "CM8 - Pile et file"
    assert title_from_filename("[UE] CM5 - TDA (2)") == "CM5 - TDA"
    assert title_from_filename("cours_reseau") == "cours reseau"
