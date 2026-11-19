---
name: credits
description: Reports Gradium credit balances, plans, billing periods, and rollover dates from the hosted Gradium MCP's get_credits tool, and resolves which Gradium organization (org_uid) to use. Use when the user asks about Gradium credits, balance, remaining usage, plan, or renewal date, or when another Gradium tool asks for an org_uid.
allowed-tools: mcp__plugin_gradium_gradium__get_credits
---

# Gradium credits

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Call `mcp__plugin_gradium_gradium__get_credits`. It takes no arguments and is free. For a manually configured production connection, the tool is named after that entry, such as `mcp__gradium__get_credits`.

## Report

- The response has two lists. `orgs` holds balances: for each entry, give its name, remaining credits out of allocated credits, plan, and next rollover date. `organizations` lists every organization the user can use, with `org_uid` and `org_name`. Add the `org_uid` when the user may need to choose an organization.
- `allocated_credits` already includes extra credits.
- An organization with no active subscription or no current balance appears in `organizations` but not in `orgs`. Say it has no current balance; do not report it as zero.
- Do not convert credits into money, characters, or minutes of audio. The tool returns no rate.

## Choose an organization

- If `organizations` has one entry, leave `org_uid` out of other Gradium calls.
- If it has several, use the one the user named; otherwise ask. Never choose silently. Reuse the chosen `org_uid` for the rest of the conversation.

Call `get_credits` only when:
- the user asks,
- a tool returns `status: organization_selection_required` and the user wants to see balances before choosing, or
- the user wants to know what a generation cost. Compare the balance before and after, and call the difference approximate if other usage could overlap.

Do not call it before every generation.

## Errors

Quote the error.
- `Sign in to Gradium Studio first.` means this account has no active Studio user.
- An authentication error means the user needs to sign in through `/mcp` (`plugin:gradium:gradium` → **Authenticate**).
