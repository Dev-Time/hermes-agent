---
name: ynab-cli
description: "Use when managing YNAB budgets, accounts, transactions, or categories. Trigger on \"ynab\", \"budget\", \"transactions\"."
version: 1.0.0
author: Dev-Time
license: MIT
metadata:
  hermes:
    tags: [Budget, Finance, YNAB, Personal Finance, API, CLI]
    homepage: https://github.com/nickmackenzie/ynab-cli
prerequisites:
  commands: [ynab-cli]
  env:
    - YNAB_ACCESS_TOKEN
    - YNAB_BUDGET_ID (optional)
---

# YNAB CLI

Interact with the YNAB API via the `ynab-cli` tool. This tool returns structured JSON, making it ideal for automation and agent use.

## When to Use

- Managing budgets, accounts, transactions, categories, payees, or months
- Automating YNAB tasks (e.g., "list all unapproved transactions", "create a $50 transaction in Groceries")
- Bulk operations where structured data is needed

## Setup

Build the CLI tool first:

```bash
go build -o ynab-cli ./cmd/ynab-cli
```

Required environment variables:

- `YNAB_ACCESS_TOKEN`: Your YNAB Personal Access Token
- `YNAB_BUDGET_ID`: (Optional) Default budget ID

## Quick Reference

| Command | Purpose | Example |
|---------|---------|---------|
| `budgets list` | List all budgets | `ynab-cli budgets list` |
| `accounts list` | List accounts | `ynab-cli accounts list --budget-id <id>` |
| `transactions list` | List transactions | `ynab-cli transactions list --since 2024-01-01` |
| `transactions create` | Create transaction | `ynab-cli transactions create --account-id <id> --date 2024-04-24 --amount -50000` |
| `categories list` | List categories | `ynab-cli categories list` |

## Core Pattern

Always prefer the CLI over raw API calls when available. The CLI handles authentication and returns standard JSON.

### Success Response Format

```json
{
  "success": true,
  "data": { ... }
}
```

### Error Response Format

```json
{
  "success": false,
  "error": "Error message"
}
```

## Common Mistakes

- **Forgetting budget-id**: Most commands require a budget ID. Use `--budget-id` if not set in environment
- **Amount format**: YNAB uses milliunits ($1.00 = 1000). Always convert dollars to milliunits
- **Date format**: Use ISO 8601 format (YYYY-MM-DD)
