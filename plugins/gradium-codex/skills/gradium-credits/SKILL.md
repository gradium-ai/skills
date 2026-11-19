---
name: gradium-credits
description: Check Gradium credit balances, plans, and rollover dates for available organizations using the Gradium MCP.
---

# Check credits

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Use the connected Gradium MCP's `get_credits` tool for a user's balance, plan, or rollover question. Report only the organizations and values returned; distinguish remaining from allocated credits and include the relevant organization name and ID when helpful. A missing organization or balance in the response is not proof that it has no credits. If the tool is unavailable or fails, report the actual connection or tool error without claiming a specific account cause.

When the user needs to select among organizations for voice discovery or speech generation, use the returned organization information when it resolves their choice, and pass the selected `org_uid` to the relevant tool. Ask which organization to use if it remains ambiguous. Do not make a credit check a prerequisite for every generation request.
