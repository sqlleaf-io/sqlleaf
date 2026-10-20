from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from sqlleaf import exception, mappings
from sqlleaf.models.query.base import Query
from sqlleaf.util import iterators


def _extract_do_body_and_language(raw_text: str) -> tuple[str, str]:
    text = raw_text.strip()
    language = "PLPGSQL"

    lang_match = re.search(r"LANGUAGE\s+([a-zA-Z0-9_'\"]+)", text, re.IGNORECASE)
    if lang_match:
        language = lang_match.group(1).strip("'\"").upper()
        text = text[: lang_match.start()] + text[lang_match.end() :]
        text = text.strip()

    dollar_match = re.match(r"^\$([a-zA-Z0-9_]*)\$(.*)\$\1\$$", text, re.DOTALL)
    if dollar_match:
        body = dollar_match.group(2)
    elif text.startswith("'") and text.endswith("'"):
        body = text[1:-1].replace("''", "'")
    else:
        body = text

    return language, body.strip()


@dataclass(frozen=True)
class DoQueryProperties:
    language: str
    body: str
    inner_statements: list[exp.Expr]

    @classmethod
    def from_expression(
        cls, statement: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping
    ) -> DoQueryProperties:
        expr = statement.args.get("expression")
        if isinstance(expr, (exp.Literal, exp.Heredoc)):
            raw_text = expr.this
        elif hasattr(expr, "name") and expr.name:
            raw_text = expr.name
        elif expr is not None:
            raw_text = str(expr)
        else:
            raw_text = ""

        language, body = _extract_do_body_and_language(raw_text)

        if language.upper() not in iterators.SUPPORTED_LANGUAGES:
            exception.raise_error(
                exception.UnsupportedFeatureError,
                message=f"Unsupported language for DO block: {language}",
            )

        parse_dialect = language.lower() if dialect == "postgres" and language.upper() == "PLPGSQL" else dialect
        inner_statements = sqlglot.parse(body, dialect=parse_dialect)
        inner_statements = [
            stmt
            for stmt in inner_statements
            if not isinstance(stmt, (exp.EndStatement, exp.Column, exp.Identifier))
        ]

        return cls(
            language=language,
            body=body,
            inner_statements=inner_statements,
        )


class DoQuery(Query):
    KIND = "do"

    def __init__(
        self,
        expr: exp.Command,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
        )
        self.properties = DoQueryProperties.from_expression(expr, dialect, object_mapping)

    @property
    def language(self) -> str:
        return self.properties.language

    @property
    def body(self) -> str:
        return self.properties.body

    @property
    def inner_statements(self) -> list[exp.Expr]:
        return self.properties.inner_statements
