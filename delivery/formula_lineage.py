"""Conservative, bounded cell-reference inventory; never evaluates formulas."""
from __future__ import annotations

import re
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries, get_column_letter

CELL_RANGE = re.compile(r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?$", re.I)
MAX_EDGES = 20000
MAX_RANGE = 10000
DYNAMIC = {"INDIRECT", "OFFSET", "CELL", "INFO"}


def _target(value, current_sheet, sheets):
    if "!" in value:
        sheet, address = value.rsplit("!", 1)
        sheet = sheet.strip("'").replace("''", "'")
    else:
        sheet, address = current_sheet, value
    if sheet not in sheets or not CELL_RANGE.fullmatch(address):
        raise ValueError("unsupported_or_unknown_reference")
    first_col, first_row, last_col, last_row = range_boundaries(address)
    if (last_col-first_col+1)*(last_row-first_row+1) > MAX_RANGE:
        raise ValueError("reference_range_limit")
    return [f"{sheet}!{get_column_letter(col)}{row}"
            for row in range(first_row,last_row+1)
            for col in range(first_col,last_col+1)]


def analyze(formula_cells, part_to_sheet, defined_names=(), sheet_order=()):
    """Return exact supported edges and explicit coverage gaps.

    Sheet names and formulas remain in the private inventory; API summaries strip
    the graph. Named ranges, structured references and dynamic references are
    intentionally unresolved until a qualified parser handles them.
    """
    sheets = set(part_to_sheet.values())
    graph = {}
    issues = []
    edge_count = 0
    names = {}
    for item in defined_names:
        name = item.get("name")
        if not name:
            continue
        scope = None
        if item.get("localSheetId") is not None:
            try:
                scope = sheet_order[int(item["localSheetId"])]
            except (ValueError, IndexError, TypeError):
                issues.append({"code": "invalid_defined_name_scope", "name": name})
                continue
        names[(scope, name.casefold())] = item.get("formula") or ""
    for cell in formula_cells:
        part, address = cell["part"], cell["cell"]
        sheet = part_to_sheet.get(part)
        if not sheet or not address:
            issues.append({"part": part, "cell": address, "code": "unmapped_formula_cell"})
            continue
        node = f"{sheet}!{address.replace('$','').upper()}"
        refs = set()
        try:
            tokens = Tokenizer("=" + (cell["formula"] or "")).items
            for token in tokens:
                if token.type == "FUNC" and token.subtype == "OPEN" and token.value[:-1].upper() in DYNAMIC:
                    raise ValueError("dynamic_reference")
                if token.type == "OPERAND" and token.subtype == "RANGE":
                    value = token.value
                    key = (sheet, value.casefold())
                    definition = names.get(key, names.get((None, value.casefold())))
                    if definition is not None:
                        # Only a single, static cell/range reference is exact.
                        # Other names (constants, unions and expressions) retain
                        # an explicit coverage gap instead of guessed edges.
                        try:
                            refs.update(_target(definition, sheet, sheets))
                        except ValueError:
                            raise ValueError("unsupported_defined_name") from None
                    else:
                        refs.update(_target(value, sheet, sheets))
                    if edge_count + len(refs) > MAX_EDGES:
                        raise ValueError("dependency_edge_limit")
            edge_count += len(refs)
            graph[node] = sorted(refs)
        except (ValueError, IndexError, TypeError) as exc:
            issues.append({"part": part, "cell": address, "code": str(exc) if isinstance(exc, ValueError) else "formula_parse_error"})
    # Three-color traversal over formula-to-formula edges only. Constants remain
    # visible in the graph but cannot create cycles.
    color = {}
    cycles = set()
    def visit(node):
        color[node] = 1
        for ref in graph[node]:
            if ref not in graph:
                continue
            if color.get(ref) == 1:
                cycles.add(node)
            elif color.get(ref, 0) == 0:
                visit(ref)
        color[node] = 2
    try:
        for node in graph:
            if color.get(node, 0) == 0:
                visit(node)
    except RecursionError:
        issues.append({"code": "dependency_depth_limit"})
    for node in sorted(cycles):
        issues.append({"cell": node, "code": "circular_formula_reference"})
    return {"graph": graph, "issues": issues,
            "coverage": "partial" if issues else ("cell_references_and_defined_names" if defined_names else "cell_references_only"),
            "edge_count": edge_count}
