# HarborIQ agent setup notes

## Codex plugin marketplace

Run this in a Codex-enabled environment:

```bash
codex plugin marketplace add aws/agent-toolkit-for-aws
```

## AWS MCP profile mapping

For each Codex MCP config file that contains the `aws-mcp` server entry, include:

```json
"env": {
  "AWS_MCP_PROXY_PROFILES": "HarborIQ"
}
```

This ensures the AWS MCP server uses the `HarborIQ` AWS profile instead of the default profile.
