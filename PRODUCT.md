# Product

## Register

Product. This is an internal admin tool, not a marketing surface — design serves the task, it isn't the point.

## What it is

A single-admin internal control panel for managing which Cynet employees can access which of the company's internal MCP (Model Context Protocol) servers (rr-mcp, ceipal-mcp, helpjuice-mcp, qb-mcp, nexus-mcp). One page: sign in with Google, see a table of users × servers, toggle access per server or grant "all", add/remove users.

## Users & purpose

A single technical admin (occasionally a couple of ops teammates later), used occasionally (not a daily-driver dashboard) to grant/revoke access when someone joins, leaves, or needs a new integration. The primary task on the one screen is: scan current grants, flip a checkbox, done. Low frequency, high trust — mistakes here mean the wrong person can query production business data (BigQuery run-rate, ATS candidate data, accounting data), so clarity beats cleverness.

## Brand personality

Quiet, precise, trustworthy — like a well-run infra console (GCP IAM, Cloudflare Access), not a consumer SaaS dashboard. No mascots, no marketing chrome, no gradients-for-flavor. Should feel like the kind of tool that inspires confidence that access control is being taken seriously.

## Anti-references

Not a generic "SaaS admin template" look (sidebar + colorful stat cards + gradient avatars). Not playful or bubbly. Not dense/cryptic like a raw database admin (phpMyAdmin-style) either — legible over dense.

## Accessibility

Standard WCAG AA: ≥4.5:1 body text contrast, checkboxes/buttons keyboard-operable and clearly focus-visible, respect `prefers-reduced-motion`, support both light and dark OS theme automatically.
