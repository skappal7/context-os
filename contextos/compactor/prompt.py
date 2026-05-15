from __future__ import annotations

SUMMARY_INSTRUCTIONS = """You are a context compactor for a long coding session. Summarise
the conversation transcript below into a dense, third-person narrative paragraph
of AT MOST 100 words.

You MUST preserve:
- Entity names (files, functions, classes, variables)
- Decisions made and the reasoning given for them
- Breaking changes or API surface modifications
- File paths that were modified
- Open questions or unresolved items

You MUST omit:
- Resolved errors and their fixes (unless the fix is itself a load-bearing decision)
- Reasoning chains that led to a final answer (keep the answer, drop the chain)
- Polite filler, acknowledgements, status updates
- Duplicate file contents

Output the summary only — no preamble, no markdown headings, no commentary on the task.
"""


def build_summary_prompt(turns_text: str) -> str:
    return f"{SUMMARY_INSTRUCTIONS}\n\n--- TRANSCRIPT ---\n{turns_text}\n--- END ---\n\nSummary:"
