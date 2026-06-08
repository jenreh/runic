---
agent: Plan
model: Claude Haiku 4.5 (copilot)
tools: [vscode/memory, execute, read, agent, search, web, 'code-reasoning/*', duckduckgo/search, 'memory/*', 'io.github.upstash/context7/*', 'playwright/*', neon/describe_table_schema, neon/explain_sql_statement, neon/get_database_tables, neon/list_projects, neon/list_shared_projects, neon/list_slow_queries, neon/search, todo]
description: 'Interactive prompt refinement workflow: interrogates scope, deliverables, constraints; never writes code.'
---
# Boost

Invoke the `boost` skill and apply its full workflow to refine the following request:

$ARGUMENTS

If no request is provided, ask the user what they'd like to build or improve.
