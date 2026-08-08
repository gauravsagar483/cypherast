"""Handwritten Cypher/GQL lexer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from cypherast.errors import Position, TokenizeError


class TokenKind(Enum):
    # Special
    EOF = auto()
    IDENT = auto()
    PARAMETER = auto()  # $name
    STRING = auto()
    INTEGER = auto()
    FLOAT = auto()
    BOOLEAN = auto()  # true / false (as keyword literals also exist)
    NULL = auto()

    # Punctuation
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    LBRACE = auto()  # {
    RBRACE = auto()  # }
    COMMA = auto()
    DOT = auto()
    COLON = auto()
    SEMICOLON = auto()
    PIPE = auto()  # |
    DOLLAR = auto()

    # Operators
    EQ = auto()  # =
    NEQ = auto()  # <>
    LT = auto()  # <
    GT = auto()  # >
    LTE = auto()  # <=
    GTE = auto()  # >=
    PLUS = auto()  # +
    MINUS = auto()  # -
    STAR = auto()  # *
    SLASH = auto()  # /
    PERCENT = auto()  # %
    CARET = auto()  # ^
    DOTDOT = auto()  # ..
    ARROW_LEFT = auto()  # <-
    ARROW_RIGHT = auto()  # ->
    DASH = auto()  # - (relationship undirected body uses this)

    # Keywords (uppercased at lex time for matching)
    MATCH = auto()
    OPTIONAL = auto()
    WHERE = auto()
    WITH = auto()
    UNWIND = auto()
    RETURN = auto()
    AS = auto()
    ORDER = auto()
    BY = auto()
    ASC = auto()
    DESC = auto()
    SKIP = auto()
    LIMIT = auto()
    DISTINCT = auto()
    UNION = auto()
    ALL = auto()
    CREATE = auto()
    MERGE = auto()
    SET = auto()
    DELETE = auto()
    DETACH = auto()
    REMOVE = auto()
    FOREACH = auto()
    ON = auto()
    AND = auto()
    OR = auto()
    XOR = auto()
    NOT = auto()
    IN = auto()
    IS = auto()
    NULL_KW = auto()  # NULL keyword (distinct from NULL literal kind for clarity)
    TRUE = auto()
    FALSE = auto()
    CASE = auto()
    WHEN = auto()
    THEN = auto()
    ELSE = auto()
    END = auto()
    STARTS = auto()
    ENDS = auto()
    CONTAINS = auto()
    USING = auto()
    INDEX = auto()
    SCAN = auto()
    JOIN = auto()
    CALL = auto()
    YIELD = auto()
    EXISTS = auto()
    COUNT = auto()
    COLLECT = auto()
    SHORTESTPATH = auto()
    ALLSHORTESTPATHS = auto()
    CYPHER = auto()
    ANY = auto()
    NONE = auto()
    SINGLE = auto()
    # GQL extras (parse-tolerant)
    NEXT = auto()
    INSERT = auto()
    USE = auto()
    FINISH = auto()
    FILTER = auto()
    LET = auto()
    FOR = auto()
    BANG = auto()  # !
    AMP = auto()  # &
    # Clause words Neo4j does not reserve — LOAD, CSV, FROM, HEADERS, FIELDTERMINATOR,
    # GROUP, OF, TRANSACTIONS, ROWS, SEARCH, VECTOR, SCORE, SHOW, CONSTRAINT, ASSERT,
    # UNIQUE — stay IDENT and are matched contextually by the parser, like NULLS /
    # FIRST / LAST in ORDER BY. Reserving them would break `AS rows`, `UNWIND rows`, etc.


KEYWORDS: dict[str, TokenKind] = {
    "MATCH": TokenKind.MATCH,
    "OPTIONAL": TokenKind.OPTIONAL,
    "WHERE": TokenKind.WHERE,
    "WITH": TokenKind.WITH,
    "UNWIND": TokenKind.UNWIND,
    "RETURN": TokenKind.RETURN,
    "AS": TokenKind.AS,
    "ORDER": TokenKind.ORDER,
    "BY": TokenKind.BY,
    "ASC": TokenKind.ASC,
    "ASCENDING": TokenKind.ASC,
    "DESC": TokenKind.DESC,
    "DESCENDING": TokenKind.DESC,
    "SKIP": TokenKind.SKIP,
    "LIMIT": TokenKind.LIMIT,
    "DISTINCT": TokenKind.DISTINCT,
    "UNION": TokenKind.UNION,
    "ALL": TokenKind.ALL,
    "ANY": TokenKind.ANY,
    "NONE": TokenKind.NONE,
    "SINGLE": TokenKind.SINGLE,
    "CREATE": TokenKind.CREATE,
    "MERGE": TokenKind.MERGE,
    "SET": TokenKind.SET,
    "DELETE": TokenKind.DELETE,
    "DETACH": TokenKind.DETACH,
    "REMOVE": TokenKind.REMOVE,
    "FOREACH": TokenKind.FOREACH,
    "ON": TokenKind.ON,
    "AND": TokenKind.AND,
    "OR": TokenKind.OR,
    "XOR": TokenKind.XOR,
    "NOT": TokenKind.NOT,
    "IN": TokenKind.IN,
    "IS": TokenKind.IS,
    "NULL": TokenKind.NULL_KW,
    "TRUE": TokenKind.TRUE,
    "FALSE": TokenKind.FALSE,
    "CASE": TokenKind.CASE,
    "WHEN": TokenKind.WHEN,
    "THEN": TokenKind.THEN,
    "ELSE": TokenKind.ELSE,
    "END": TokenKind.END,
    "STARTS": TokenKind.STARTS,
    "ENDS": TokenKind.ENDS,
    "CONTAINS": TokenKind.CONTAINS,
    "USING": TokenKind.USING,
    "INDEX": TokenKind.INDEX,
    "SCAN": TokenKind.SCAN,
    "JOIN": TokenKind.JOIN,
    "CALL": TokenKind.CALL,
    "CYPHER": TokenKind.CYPHER,
    "YIELD": TokenKind.YIELD,
    "EXISTS": TokenKind.EXISTS,
    "COUNT": TokenKind.COUNT,
    "COLLECT": TokenKind.COLLECT,
    "SHORTESTPATH": TokenKind.SHORTESTPATH,
    "ALLSHORTESTPATHS": TokenKind.ALLSHORTESTPATHS,
    "NEXT": TokenKind.NEXT,
    "INSERT": TokenKind.INSERT,
    "USE": TokenKind.USE,
    "FINISH": TokenKind.FINISH,
    "FILTER": TokenKind.FILTER,
    "LET": TokenKind.LET,
    "FOR": TokenKind.FOR,
}


@dataclass(slots=True)
class Token:
    kind: TokenKind
    text: str
    position: Position
    comments: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"Token({self.kind.name}, {self.text!r}, {self.position})"


class Lexer:
    """Character-by-character Cypher lexer."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._i = 0
        self._line = 1
        self._col = 1
        self._pending_comments: list[str] = []

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while True:
            tok = self.next_token()
            tokens.append(tok)
            if tok.kind is TokenKind.EOF:
                break
        return tokens

    def next_token(self) -> Token:
        self._skip_ws_and_comments()
        if self._eof():
            return Token(TokenKind.EOF, "", self._pos(), self._take_comments())

        pos = self._pos()
        ch = self._peek()

        # String
        if ch in ("'", '"'):
            return self._string(pos)

        # Number
        if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
            return self._number(pos)

        # Parameter $name
        if ch == "$":
            return self._parameter(pos)

        # Backtick identifier
        if ch == "`":
            return self._backtick_ident(pos)

        # Multi-char operators
        two = self.source[self._i : self._i + 2]
        three = self.source[self._i : self._i + 3]
        if three == "<=>":  # not cypher, skip
            pass
        if two == "<>":
            self._advance(2)
            return Token(TokenKind.NEQ, "<>", pos, self._take_comments())
        if two == "<=":
            self._advance(2)
            return Token(TokenKind.LTE, "<=", pos, self._take_comments())
        if two == ">=":
            self._advance(2)
            return Token(TokenKind.GTE, ">=", pos, self._take_comments())
        if two == "<-":
            self._advance(2)
            return Token(TokenKind.ARROW_LEFT, "<-", pos, self._take_comments())
        if two == "->":
            self._advance(2)
            return Token(TokenKind.ARROW_RIGHT, "->", pos, self._take_comments())
        if two == "..":
            self._advance(2)
            return Token(TokenKind.DOTDOT, "..", pos, self._take_comments())
        if two == "!=":  # Neo4j accepts != as synonym for <>
            self._advance(2)
            return Token(TokenKind.NEQ, "!=", pos, self._take_comments())
        if ch == "!":
            self._advance()
            return Token(TokenKind.BANG, "!", pos, self._take_comments())

        single = {
            "(": TokenKind.LPAREN,
            ")": TokenKind.RPAREN,
            "[": TokenKind.LBRACKET,
            "]": TokenKind.RBRACKET,
            "{": TokenKind.LBRACE,
            "}": TokenKind.RBRACE,
            ",": TokenKind.COMMA,
            ".": TokenKind.DOT,
            ":": TokenKind.COLON,
            ";": TokenKind.SEMICOLON,
            "|": TokenKind.PIPE,
            "=": TokenKind.EQ,
            "<": TokenKind.LT,
            ">": TokenKind.GT,
            "+": TokenKind.PLUS,
            "-": TokenKind.MINUS,
            "*": TokenKind.STAR,
            "/": TokenKind.SLASH,
            "%": TokenKind.PERCENT,
            "^": TokenKind.CARET,
            "&": TokenKind.AMP,
        }
        if ch in single:
            self._advance()
            return Token(single[ch], ch, pos, self._take_comments())

        # Identifier / keyword
        if ch.isalpha() or ch == "_":
            return self._ident_or_keyword(pos)

        raise TokenizeError(
            f"Illegal character {ch!r}",
            code="CG1001",
            position=pos,
            source=self.source,
        )

    # --- scanners ---------------------------------------------------------

    def _string(self, pos: Position) -> Token:
        quote = self._advance()
        buf: list[str] = []
        while not self._eof():
            ch = self._advance()
            if ch == "\\" and not self._eof():
                esc = self._advance()
                escapes = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    "\\": "\\",
                    "'": "'",
                    '"': '"',
                    "b": "\b",
                    "f": "\f",
                }
                buf.append(escapes.get(esc, esc))
                continue
            if ch == quote:
                return Token(TokenKind.STRING, "".join(buf), pos, self._take_comments())
            buf.append(ch)
        raise TokenizeError(
            "Unterminated string literal",
            code="CG1002",
            position=pos,
            source=self.source,
        )

    def _number(self, pos: Position) -> Token:
        start = self._i
        is_float = False
        while not self._eof() and self._peek().isdigit():
            self._advance()
        if not self._eof() and self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            self._advance()  # .
            while not self._eof() and self._peek().isdigit():
                self._advance()
        if not self._eof() and self._peek() in ("e", "E"):
            is_float = True
            self._advance()
            if not self._eof() and self._peek() in ("+", "-"):
                self._advance()
            if self._eof() or not self._peek().isdigit():
                raise TokenizeError(
                    "Invalid number literal",
                    code="CG1004",
                    position=pos,
                    source=self.source,
                )
            while not self._eof() and self._peek().isdigit():
                self._advance()
        text = self.source[start : self._i]
        kind = TokenKind.FLOAT if is_float else TokenKind.INTEGER
        return Token(kind, text, pos, self._take_comments())

    def _parameter(self, pos: Position) -> Token:
        self._advance()  # $
        if self._eof() or not (self._peek().isalnum() or self._peek() == "_"):
            raise TokenizeError(
                "Invalid parameter name",
                code="CG1005",
                position=pos,
                source=self.source,
            )
        start = self._i
        while not self._eof() and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()
        name = self.source[start : self._i]
        return Token(TokenKind.PARAMETER, name, pos, self._take_comments())

    def _backtick_ident(self, pos: Position) -> Token:
        self._advance()  # `
        buf: list[str] = []
        while not self._eof():
            ch = self._advance()
            if ch == "`":
                if not self._eof() and self._peek() == "`":
                    self._advance()
                    buf.append("`")
                    continue
                return Token(TokenKind.IDENT, "".join(buf), pos, self._take_comments())
            buf.append(ch)
        raise TokenizeError(
            "Unterminated backtick identifier",
            code="CG1002",
            position=pos,
            source=self.source,
        )

    def _ident_or_keyword(self, pos: Position) -> Token:
        start = self._i
        while not self._eof() and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()
        text = self.source[start : self._i]
        upper = text.upper()
        if upper in KEYWORDS:
            kind = KEYWORDS[upper]
            if kind is TokenKind.TRUE:
                return Token(TokenKind.TRUE, "true", pos, self._take_comments())
            if kind is TokenKind.FALSE:
                return Token(TokenKind.FALSE, "false", pos, self._take_comments())
            if kind is TokenKind.NULL_KW:
                return Token(TokenKind.NULL_KW, "null", pos, self._take_comments())
            return Token(kind, upper, pos, self._take_comments())
        return Token(TokenKind.IDENT, text, pos, self._take_comments())

    # --- helpers ----------------------------------------------------------

    def _skip_ws_and_comments(self) -> None:
        while not self._eof():
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
                continue
            # // line comment
            if ch == "/" and self._peek(1) == "/":
                self._advance(2)
                start = self._i
                while not self._eof() and self._peek() != "\n":
                    self._advance()
                self._pending_comments.append(self.source[start : self._i].rstrip())
                continue
            # /* block comment */
            if ch == "/" and self._peek(1) == "*":
                pos = self._pos()
                self._advance(2)
                start = self._i
                while not self._eof():
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._pending_comments.append(self.source[start : self._i])
                        self._advance(2)
                        break
                    self._advance()
                else:
                    raise TokenizeError(
                        "Unterminated comment",
                        code="CG1003",
                        position=pos,
                        source=self.source,
                    )
                continue
            break

    def _take_comments(self) -> list[str]:
        comments = self._pending_comments
        self._pending_comments = []
        return comments

    def _peek(self, n: int = 0) -> str:
        j = self._i + n
        if j >= len(self.source):
            return ""
        return self.source[j]

    def _advance(self, n: int = 1) -> str:
        ch = ""
        for _ in range(n):
            if self._eof():
                return ch
            ch = self.source[self._i]
            self._i += 1
            if ch == "\n":
                self._line += 1
                self._col = 1
            else:
                self._col += 1
        return ch

    def _eof(self) -> bool:
        return self._i >= len(self.source)

    def _pos(self) -> Position:
        return Position(self._line, self._col, self._i)
