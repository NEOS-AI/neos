---
name: notebook
description: Edit Jupyter notebook cells with notebook_edit.v1.
when_to_use: The user asked to change a .ipynb notebook.
allowed_tools: [notebook_edit.v1, read_file.v1, glob_files.v1]
---

# notebook

## When to Use

Use when the workspace change is a Jupyter notebook (`.ipynb`).

## Boundaries

Do not use `edit_file.v1` or `write_file.v1` on `.ipynb`.
Do not execute notebook cells. Do not invent outputs.
If `notebook_edit.v1` is not advertised, stop and say the operator has not enabled `coding_model.notebook_edit`.

Call `notebook_edit.v1` with `edit_mode` `replace`, `insert`, or `delete`.
Use `cell_id` from the notebook JSON. Insert without `cell_id` prepends a cell, or creates the notebook if it does not exist.
