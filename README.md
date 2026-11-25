# agent-usage

[한국어](README.ko.md)

A floating desktop widget for Linux that shows how much of your AI coding agent quotas you have used. It reads each agent's own local sign-in, so no proxy is needed.

**Supported agents: Codex, Claude and Antigravity only.**

| Floating bubble | Usage panel |
|---|---|
| ![Bubble with the agent fan open](docs/screenshots/fan.png) | ![Usage panel with Codex expanded](docs/screenshots/panel.png) |

## Features

- A floating bubble that stays on top. Click it to fan out one bubble per agent with its usage and time to reset.
- Click an agent bubble for its detail panel: 5-hour, weekly and per-model windows.
- Codex extras: rate limit reset credits (click the tickets for each expiry date) and the 24-hour image generation limit.
- Several accounts per agent. Add or sign in again from the panel, and the sign-in page opens in your browser.
- Top bar indicators with the current usage of each agent.
- Polls every 5 minutes. When an agent's usage API rate-limits you, the widget waits 5 to 30 minutes and keeps showing the last value.

## Requirements

- Ubuntu with GNOME on X11 (only setup tested so far) and the AppIndicator extension
- `python3-gi`, `python3-gi-cairo`, `gir1.2-ayatanaappindicator3-0.1`
- The CLIs of the agents you use: `codex`, `claude`, `agy`

## Usage

```bash
git clone https://github.com/Changroro/agent-usage.git
cd agent-usage
./bin/agent-usage          # bubble and top bar icons
./bin/agent-usage --open   # also open the panel right away
```

| Action | Result |
|---|---|
| Click the bubble | Fan out the agent bubbles, click again to fold |
| Drag the bubble | Move it. The fan and the open panel follow, and the position is remembered |
| Click an agent bubble | Open that agent's detail panel |
| Right-click the bubble | Show all, connect accounts, refresh, quit |
| Gear icon in the panel | Add, rename, sign in again or remove accounts |

The language follows the system. Set `AGENT_USAGE_LANGUAGE=ko` or `en` to override it.

To start it on login, create `~/.config/autostart/agent-usage.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=agent-usage
Exec=/path/to/agent-usage/bin/agent-usage
```

## Where the data comes from

| Agent | Accounts | Usage |
|---|---|---|
| Codex | `~/.codex`, [Orca](https://github.com/stablyai/orca) accounts, accounts added here (`CODEX_HOME`) | `wham/usage`, reset credit API, image limit headers |
| Claude | `~/.claude`, accounts added here (`CLAUDE_CONFIG_DIR`) | `api/oauth/usage` |
| Antigravity | the system keyring account, accounts added here (separate `HOME`, file token storage) | `agy -p /usage` |

Tokens are only sent to each agent's own API. The widget never refreshes tokens itself and leaves that to each CLI. Added accounts and the bubble position are stored in `~/.config/agent-usage/`.

The image limit is read from the headers of an image request with an empty prompt. The server rejects it, so no image is generated.

**Reset now uses a real Codex reset credit.** It asks for confirmation first, with Cancel as the default.

## Development

```bash
python3 -m unittest discover -s tests
AGENT_USAGE_LANGUAGE=en ./scripts/screenshots.py   # regenerate the README screenshots from sample data
```

Icons come from [LobeHub Icons](https://github.com/lobehub/lobe-icons) (MIT, `assets/LobeHub-LICENSE`).

## License

MIT
