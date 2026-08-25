from __future__ import annotations

import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util, exception, settings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo


@dataclass(frozen=True)
class TableQueryProperties:
    location: exp.LocationProperty | None

    @classmethod
    def from_expression(cls, expr: exp.Create, dialect: str):
        location = None
        if properties := expr.args.get("properties"):
            location = properties.find(exp.LocationProperty)
        return cls(location=location)


class TableQuery(Query):
    KIND = "table"

    def __init__(self, expr: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        self.properties = TableQueryProperties.from_expression(expr, dialect)

        if self.properties.location:
            location_literal = self.properties.location.this
            source_type = self._determine_expression_type(location_literal, dialect)
            source = SourceInfo(expression=location_literal, type=source_type)
        else:
            source = None

        target = util.get_table(expr.this)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
            skip_type_annotation=True,
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherits: t.List[TableQuery] = []
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(expr, self.target_info.expression, dialect)

    @property
    def location(self) -> exp.LocationProperty | None:
        return self.properties.location

    def is_external(self) -> bool:
        return

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns

    def set_column_defs(self) -> None:
        """
        Collect all the column definitions for this table.
        """
        all_columns = []

        for expression in self.statement.this.expressions:
            if isinstance(expression, exp.ColumnDef):
                all_columns.append(expression)
            elif isinstance(expression, exp.LikeProperty):
                like_columns = self._collect_like_columns(expression, self.object_mapping, self.get_target_as_table())
                all_columns.extend(like_columns)
            elif isinstance(expression, exp.Identifier):
                # CREATE TABLE (a INT, b);
                raise exception.InvalidQueryError(message=f"Column '{expression.name}' must define a data type.")
            else:
                raise exception.InvalidQueryError(message=f"Unsupported column expression: {type(expression)}")

        if inherited_props := list[exp.InheritsProperty](self.statement.find_all(exp.InheritsProperty)):
            inherited_columns = self._collect_inherited_columns(inherited_props)
            all_columns = inherited_columns + all_columns

        # Set the column's 'default' type to the column's own type (it is sometimes missing)
        for col_def in all_columns:
            if default := col_def.find(exp.DefaultColumnConstraint):
                default.this.type = col_def.kind

        self.column_defs = all_columns
        self.system_column_defs = settings.system_columns(self.dialect)

    def _collect_inherited_columns(
        self, inherits_properties: t.List[exp.InheritsProperty]
    ) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b INHERITS (a)' and collect all their columns.
        A table can have multiple tables in an INHERITS clause.
        """
        column_defs = []

        for inh_prop in inherits_properties:
            for inh_table in inh_prop.expressions:
                parent_table_query = t.cast(TableQuery, self.object_mapping.lookup_table_query(table=inh_table))
                parent_table_query.inherited_by.append(self)
                self.inherits.append(parent_table_query)

                # Re-assign the columns to a copy of the correct table
                expr = self.target_info.expression
                if expr.parent:
                    schema = util.copy_expression(expr.parent)
                    for parent_col_def in parent_table_query.column_defs:
                        col_def = parent_col_def.copy()
                        schema.append("expressions", col_def)
                        column_defs.append(col_def)

        return column_defs

    def _collect_like_columns(
        self, like_property: exp.LikeProperty, object_mapping: mappings.ObjectMapping, child_object: exp.Table
    ) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b (LIKE a)'.
        A table can have multiple LIKE clauses.
        """
        columns = []
        property_names = []

        for like_prop in like_property.expressions:
            # sqlglot concats properties with '='
            property_names.append(str(like_prop).replace("=", " "))

        properties = self._get_properties_to_include(property_names)

        # Look up the like-table's columns and determine which properties to transfer
        parent_table_query = t.cast(TableQuery, object_mapping.lookup_table_query(table=like_property.this))
        parent_columns = parent_table_query.get_column_defs()

        for parent_col_def in parent_columns:
            new_col = parent_col_def.copy()
            for prop_name, prop_attrs in properties.items():
                prop_expr = new_col.find(prop_attrs["expr"])

                if properties[prop_name]["include"]:
                    # Set the expression's parent to be the new table (it's missing)
                    if prop_expr:
                        for inner_col in prop_expr.find_all(exp.Column):
                            # A GENERATED column expression might refer to other columns
                            try:
                                referenced_parent_col_def = [c for c in parent_columns if c.name == inner_col.name][0]
                            except IndexError:
                                message = f"Column '{inner_col.name}' does not exist in table '{child_object}'."
                                raise exception.MappingError(message=message)

                            inner_col.set("catalog", exp.to_identifier(child_object.catalog))
                            inner_col.set("db", exp.to_identifier(child_object.db))
                            inner_col.set("table", exp.to_identifier(child_object.this))
                            inner_col.type = referenced_parent_col_def.kind
                else:
                    # Discard the column's expression
                    if prop_expr:
                        prop_expr.parent.pop()

            columns.append(new_col)

        return columns

    def _get_properties_to_include(self, options: t.List[str]) -> t.Dict:
        """
        Determine which column properties to keep within a LIKE according to the rules below.

        From the Postgres docs:
            Specifying INCLUDING copies the property, specifying EXCLUDING omits the property.
            EXCLUDING is the default. If multiple specifications are made for the same kind
            of object, the last one is used. It could be useful to write individual EXCLUDING
            clauses after INCLUDING ALL to select all but some specific options.
        """
        # All supported properties
        properties = {
            "DEFAULTS": {"include": False, "expr": exp.DefaultColumnConstraint},
            "GENERATED": {"include": False, "expr": exp.ComputedColumnConstraint},
            "IDENTITY": {"include": False, "expr": exp.GeneratedAsIdentityColumnConstraint},
        }

        for opt in options:
            opt = opt.strip().upper()

            if opt == "INCLUDING ALL":
                for prop in properties:
                    properties[prop]["include"] = True
                continue

            if opt == "EXCLUDING ALL":
                for prop in properties:
                    properties[prop]["include"] = False
                continue

            parts = opt.split()
            action, prop = parts

            if prop not in properties:
                continue  # Ignore unknown properties

            if action == "INCLUDING":
                properties[prop]["include"] = True
            elif action == "EXCLUDING":
                properties[prop]["include"] = False

        return properties
