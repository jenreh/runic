# Branching Rules

This repository only allows a defined list of branch names.

## Allowed Branch Names

- `feature/<slug>`
- `release/<version>`
- `fix/<ticket-ref-and-slug`>
- `hotfix/<slug-or-version>`
- `docs/<slug>`

## Naming Rules

- Use lowercase only.
- Use `/` exactly as shown in the allowed patterns.
- Use kebab-case for descriptive suffixes.
- Use digits and dots for versions where applicable.
- Keep names short and specific.

Examples:

- `feature/add-task-runner-docs`
- `feature/123-update-readme`
- `release/1.2.0`
- `hotfix/fix-taskfile-typo`
- `hotfix/1.2.1`

Branches that do not match the allowed names should be renamed before they are pushed or used for a pull request.
