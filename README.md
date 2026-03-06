# xiaohongshu-mcp-server

<!-- mcp-name: io.github.shanyang-me/xiaohongshu-mcp -->

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for [Xiaohongshu (Little Red Book)](https://www.xiaohongshu.com) - China's leading lifestyle social media platform.

Publish image notes, search content, view note details, and manage your account - all through MCP tools that AI assistants can use directly.

## How It Works

Uses **Playwright** to run a headless Chromium browser that:
1. Loads your XHS session cookies
2. Generates authentic API signatures via the XHS web app's built-in signing function
3. Makes API calls through the browser's network context (bypasses anti-bot detection)
4. Uploads images directly to XHS CDN

No browser automation of UI elements - all interactions go through XHS's internal API.

## Tools

| Tool | Description |
|------|-------------|
| `check_login_status` | Check if you're logged in |
| `get_login_qrcode` | Generate QR code for login |
| `check_qrcode_status` | Poll QR scan status & save session |
| `reload_cookies` | Reload cookies from disk |
| `publish_content` | Publish an image note with title, text, images, and tags |
| `search_feeds` | Search XHS notes by keyword |
| `get_feed_detail` | Get full details of a note |
| `user_profile` | Get user profile information |

## Installation

```bash
pip install xiaohongshu-mcp-server
playwright install chromium
```

For QR code image generation (optional):
```bash
pip install "xiaohongshu-mcp[qrcode]"
```

## Quick Start

### 1. Start the server

**HTTP mode** (for Claude Code, Cursor, etc.):
```bash
xhs-mcp --transport http --port 18060
```

**stdio mode** (for Claude Desktop):
```bash
xhs-mcp --transport stdio
```

### 2. Login

Call the `get_login_qrcode` tool, scan the QR code with the Xiaohongshu app, then call `check_qrcode_status` with the returned `qr_id` and `code`. Cookies are saved to `~/.xhs-mcp/cookies.json` and persist across restarts.

### 3. Use

Ask your AI assistant to publish a note, search for content, etc.

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "xhs-mcp": {
      "command": "xhs-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add xhs-mcp --transport http http://localhost:18060/mcp
```

Then start the server: `xhs-mcp`

### As a LaunchAgent (macOS auto-start)

Create `~/Library/LaunchAgents/com.xhs-mcp.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.xhs-mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/your/venv/bin/xhs-mcp</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/xhs-mcp.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/xhs-mcp.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.xhs-mcp.plist
```

## Example: Publish a Note

```python
# Via MCP tool call
publish_content(
    title="Hello XHS!",
    content="My first post published via MCP.",
    images=["/path/to/photo.jpg"],
    tags=["MCP", "AI"]
)
```

## Requirements

- Python 3.12+
- Chromium (installed via `playwright install chromium`)
- A Xiaohongshu account

## License

MIT
