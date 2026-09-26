from __future__ import annotations

COMMAND_ALLOWLIST = frozenset(
    {
        "sheet.command.set-range-values",
        "sheet.command.insert-row",
        "sheet.command.insert-col",
        "sheet.command.remove-row",
        "sheet.command.remove-col",
        "sheet.command.add-worksheet-merge",
        "sheet.command.sort-range",
        "sheet.command.addDataValidation",
        "sheet.command.add-conditional-rule",
        "sheet.command.add-table",
        "doc.command.insert-text",
        "doc.command.update-text",
    }
)


def mutation_id(command_id: str) -> bool:
    return ".mutation." in command_id or ".operation." in command_id
