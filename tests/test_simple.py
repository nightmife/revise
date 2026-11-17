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
    assert qa[0].question == "Qu'est-ce qu'une pile ?"
    assert qa[0].answer.startswith("Une structure de donnée")
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


def test_acronyms_checked_against_initials():
    cards = cards_from_page("Bases de données\n• Un SGBD (Système de Gestion de Bases de Données) stocke les données\n"
                            "• Le Service public (SP) est une activité\n• Le DUT (pas un sigle ici) compte\n", 2)
    asked = {c.question: c.answer for c in cards}
    assert asked["Que signifie le sigle SGBD ?"] == "Système de Gestion de Bases de Données"
    assert asked["Que signifie le sigle SP ?"] == "Service public"
    assert "Que signifie le sigle DUT ?" not in asked


def test_law_rulings_years_and_enumerations():
    text = ("Le service public\n"
            "• CE, 28 juin 1963, Narcy ; on retrouve trois critères :\n"
            "• Une mission d'intérêt général ;\n• Le contrôle par une personne publique ;\n"
            "• Des prérogatives de puissance publique.\n"
            "En 2007, le Conseil d'État donne un mode d'emploi pour reconnaître le contrôle public.\n"
            "Les deux catégories de SP sont : les SPA, les SPIC\n")
    cards = cards_from_page(text, 4)
    asked = {c.question: c for c in cards}
    assert asked["Arrêt Narcy : quelle juridiction et quelle date ?"].answer == "CE, 28 juin 1963"
    crit = [c for q, c in asked.items() if q.startswith("Cite les trois critères")]
    assert crit and crit[0].answer.count("\n") == 2
    year = [c for c in cards if c.kind == "cloze" and c.answer == "2007"]
    assert year and year[0].question.startswith("En […], le Conseil")
    assert asked["Cite les deux catégories de SP."].answer == "- les SPA\n- les SPIC"


def test_purpose_complexity_and_rejected_terms():
    text = ("Tri fusion\n• Le tri fusion permet de trier un tableau en coupant en deux\n"
            "• La complexité du tri fusion est en O(n log n)\n"
            "• Le commissaire du gouvernement déclare : certains services sont par nature publics\n"
            "• Exemple : voici une valeur qui ne veut rien dire du tout\n"
            "• Les ordres professionnels : ils constituent des services publics.\n")
    asked = {c.question: c.answer for c in cards_from_page(text, 3)}
    assert asked["À quoi sert le tri fusion ?"].startswith("Permet de trier")
    assert asked["Quelle est la complexité du tri fusion ?"] == "O(nlogn)"
    assert not any("commissaire" in q or "Exemple" in q or "ordres" in q for q in asked)


def test_course_cards_drop_headers_and_build_up_slides():
    from revise.engines.simple import course_cards
    footer = "Introduction à l'informatique – Université Lyon 1"
    pages = [f"Titre {i}\n• Une pile{i} est une structure de donnée avec un sommet\n{footer}\n{i}" for i in range(8)]
    pages.insert(3, "Piles\n• Une file est une structure de donnée où l'on retire le premier\n")
    pages.insert(4, "Piles\n• Une file est une structure de donnée où l'on retire le premier\n• Ajout en queue\n")
    cards = course_cards(pages)
    assert not any("Université" in c.question + c.answer for c in cards)
    files = [c for c in cards if c.question == "Qu'est-ce qu'une file ?"]
    assert len(files) == 1 and files[0].page == 5   # la page « à étapes » incomplète est sautée
