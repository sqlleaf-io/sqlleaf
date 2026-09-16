from enum import IntEnum

from sqlglot.tokens import TokenType
from sqlglot import tokenizer_core

# Monkey patch sqlglot's tokenizer with PL/pgSQL keywords
tt = tokenizer_core.TokenType
PLPGSQL_CUSTOM_TOKEN_NAMES = (
    "ASSERT",
    "BY",
    "CLOSE",
    "CONTINUE",
    "DDOT",
    "EXIT",
    "FOREACH",
    "IF",
    "LOOP",
    "MOVE",
    "OPEN",
    "PERFORM",
    "RAISE",
    "RETURN",
    "REVERSE",
    "WHILE",
)
PLPGSQL_KEYWORD_TOKEN_NAMES = (
    *(token for token in PLPGSQL_CUSTOM_TOKEN_NAMES if token != "DDOT"),
    "DECLARE",
    "GET",
)
token_dict = {m.name: m.value for m in TokenType}

next_value = max(token_dict.values()) + 1
for token in PLPGSQL_CUSTOM_TOKEN_NAMES:
    token_dict[token] = next_value
    next_value += 1

TokenType = IntEnum('TokenType', token_dict)
