import pytest

from revise.mathtext import render, to_text


@pytest.mark.parametrize("tex,expected", [
    (r"x^2", "x²"), (r"x^{10}", "x¹⁰"), (r"a_i", "aᵢ"), (r"u_{n+1}", "uₙ₊₁"), (r"x^{k/2}", "x^(k/2)"),
    (r"e^{i\pi} + 1 = 0", "e^(iπ) + 1 = 0"), (r"\alpha \leq \beta", "α ≤ β"),
    (r"\frac{a}{b}", "a/b"), (r"\frac{a+b}{2}", "(a + b)/2"), (r"\frac{1}{n^2}", "1/n²"),
    (r"\sqrt{x}", "√x"), (r"\sqrt{x+1}", "√(x + 1)"), (r"\sqrt[3]{x}", "³√x"),
    (r"O(n \log n)", "O(n log n)"), (r"\log_2 n", "log₂ n"), (r"\Theta(n^2)", "Θ(n²)"),
    (r"\sum_{i=1}^{n} i", "Σᵢ₌₁ⁿ i"), (r"\forall x \in \mathbb{R}", "∀ x ∈ ℝ"),
    (r"A \Rightarrow B", "A ⇒ B"), (r"\left( \frac{n}{2} \right)", "(n/2)"),
    (r"\text{si } n > 0", "si n > 0"), (r"\vec{v}", "v⃗"), (r"f \colon A \to B", "f : A → B"),
    (r"\{1, 2\}", "{1, 2}"), (r"\inconnue{x}", "inconnuex"), (r"x^", "x^"), (r"\frac{a}", "a/"), ("", ""),
    (r"\lim_{n \to \infty} u_n", "lim_(n → ∞) uₙ"), (r"\binom{n}{k}", "C(n, k)"),
])
def test_to_text(tex, expected):
    assert to_text(tex) == expected


def test_render_only_touches_formulas():
    assert render("La complexité est $O(n^2)$ au pire.") == "La complexité est O(n²) au pire."
    assert render(r"On a \(a \leq b\) et \[ \frac{1}{2} \]") == "On a a ≤ b et \n\n1/2\n\n"
    assert render("Soit $n$ un entier et $x_1$ réel") == "Soit n un entier et x₁ réel"
    assert render("$$E = mc^2$$") == "\n\nE = mc²\n\n"
    # Rien à convertir : prix, texte sans formule, dollars isolés
    for text in ("Ça coûte 5$ et 10$ en tout", "Entre $5 et $10", "Pas de formule ici", "Un seul $ ici",
                 "prix : 3$, 4$ ou 5$"):
        assert render(text) == text
    # Le code n'est jamais modifié
    code = "Écris `echo $HOME et $PATH` puis\n```bash\nx=$a; y=$b^2\n```\nfin"
    assert render(code) == code
    assert render("`$x^2$` vaut $x^2$") == "`$x^2$` vaut x²"
    # Le résultat reste du Markdown inoffensif (pas d'italique ni de balise créés par la formule)
    assert render("$a * b * c$ et $a < b$") == r"$a * b * c$ et a \< b"
    assert render(r"$a_1 \cdot a\_2 * 3$") == r"a₁ · a\_2 \* 3"


def test_render_accepts_function_notation():
    assert render("coût $O(1)$ ou $f(x)$, pas 5$ (TTC) et 10$") == "coût O(1) ou f(x), pas 5$ (TTC) et 10$"
