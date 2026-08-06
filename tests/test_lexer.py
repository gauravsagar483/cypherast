"""Lexer tests."""

from cypherast.lexer import Lexer, TokenKind


def test_keywords_and_idents():
    toks = Lexer("MATCH (n:Person) RETURN n.name").tokenize()
    kinds = [t.kind for t in toks if t.kind is not TokenKind.EOF]
    assert TokenKind.MATCH in kinds
    assert TokenKind.RETURN in kinds
    assert TokenKind.IDENT in kinds


def test_string_and_number():
    toks = Lexer("RETURN 42, 3.14, 'hi'").tokenize()
    texts = [(t.kind, t.text) for t in toks if t.kind is not TokenKind.EOF]
    assert (TokenKind.INTEGER, "42") in texts
    assert (TokenKind.FLOAT, "3.14") in texts
    assert (TokenKind.STRING, "hi") in texts


def test_parameter():
    toks = Lexer("RETURN $name").tokenize()
    p = next(t for t in toks if t.kind is TokenKind.PARAMETER)
    assert p.text == "name"


def test_arrows():
    toks = Lexer("()-->()<--()").tokenize()
    kinds = [t.kind for t in toks if t.kind is not TokenKind.EOF]
    assert TokenKind.ARROW_RIGHT in kinds
    assert TokenKind.ARROW_LEFT in kinds
