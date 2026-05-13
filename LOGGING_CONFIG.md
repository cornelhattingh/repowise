# RepoWise Logging Configuration

RepoWise now uses Python's standard `logging` module with comprehensive logging enabled during server startup and chat operations. Logging is configured automatically when you run `repowise serve`.

## Example Startup Output

When you run `repowise serve` with an OpenAI-compatible provider, you'll see:

```
2026-05-13 08:42:26 - repowise.cli.commands.serve_cmd - INFO - RepoWise server starting (log level: INFO)
2026-05-13 08:42:26 - repowise.cli.commands.serve_cmd - INFO - OpenAI-compatible base URL: https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1
2026-05-13 08:42:26 - repowise.server.routers.chat - INFO - Chat request for repo 'MyRepo' at /path/to/repo, message preview: What does this component do?...
2026-05-13 08:42:26 - repowise.server.routers.chat - INFO - Chat provider resolved: openai_compatible (gpt-4o-mini)
2026-05-13 08:42:26 - repowise.server.routers.chat - INFO - Starting agentic loop for repo 'MyRepo' with 8 tools
```

## Log Format

All logs use the standard format:

```
TIMESTAMP - LOGGER_NAME - LOG_LEVEL - MESSAGE
```

Example:
```
2026-05-13 08:42:26 - repowise.cli.commands.serve_cmd - INFO - RepoWise server starting (log level: INFO)
```

## Controlling Log Verbosity

### Option 1: Environment Variable (Recommended)

```powershell
# Show only INFO and above (default)
$env:REPOWISE_LOG_LEVEL = "INFO"

# Show detailed DEBUG information
$env:REPOWISE_LOG_LEVEL = "DEBUG"

# Show only warnings and errors
$env:REPOWISE_LOG_LEVEL = "WARNING"

# Show only errors
$env:REPOWISE_LOG_LEVEL = "ERROR"
```

### Option 2: Debug Flag

Enable debug logging with a single flag:

```powershell
$env:REPOWISE_DEBUG = "true"
# This automatically sets log level to DEBUG
```

## What Gets Logged

### Server Startup (`repowise serve`)

1. **Server initialization**
   - Log level being used
   - Example: `RepoWise server starting (log level: INFO)`

2. **OpenAI-compatible configuration**
   - Base URL being used
   - Example: `OpenAI-compatible base URL: https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1`

### Chat Operations

1. **Chat request received**
   - Repository name and path
   - Message preview (first 50 chars)
   - Example: `Chat request for repo 'MyRepo' at /path/to/repo, message preview: What does this component do?...`

2. **Provider resolution**
   - Provider name and model being used
   - Example: `Chat provider resolved: openai_compatible (gpt-4o-mini)`

3. **Agentic loop start**
   - Number of available tools
   - Example: `Starting agentic loop for repo 'MyRepo' with 8 tools`

4. **Errors during chat**
   - Full error messages with stack traces
   - Example: `Provider error during chat: Connection timeout`
   - Example: `Chat stream error`

## Troubleshooting Chat Failures

If your chats are failing, enable debug logging to see what's happening:

```powershell
# Enable debug logging
$env:REPOWISE_DEBUG = "true"

# Or set log level to DEBUG
$env:REPOWISE_LOG_LEVEL = "DEBUG"

# Start server
uv run repowise serve
```

Then check the console output for:

1. **Provider initialization errors**
   - Look for: `Failed to get chat provider: ...`
   - Check that your API key/base URL are configured correctly

2. **Chat request failures**
   - Look for: `Chat request for repo ...`
   - Verify the repository exists and has indexed data

3. **Provider errors**
   - Look for: `Provider error during chat: ...`
   - This shows the actual error from the LLM provider

4. **Connection errors**
   - Look for timeout or connection messages
   - For Microsoft Foundry, verify the base URL is accessible
   - For Ollama/local, verify the service is running

## Example: Debugging Microsoft Foundry Chat Failures

```powershell
# 1. Enable debug logging
$env:REPOWISE_DEBUG = "true"

# 2. Set Microsoft Foundry credentials
$env:OPENAI_COMPATIBLE_BASE_URL = "https://YOUR-RESOURCE-NAME.openai.azure.com/openai/v1"
$env:OPENAI_COMPATIBLE_API_KEY = "your-api-key"

# 3. Start server and check logs
uv run repowise serve

# 4. In another terminal, send a chat request
curl -X POST http://localhost:7337/api/repos/{repo_id}/chat/messages \
  -H "Content-Type: application/json" \
  -d '{"message": "What does this project do?"}'

# 5. Check the server console for detailed logs showing:
#    - Provider resolution
#    - Agentic loop start
#    - Any errors from the API
```

## Log Output Destinations

Logs are output to **console (stdout/stderr)** during CLI commands and server startup. When running with uvicorn, logs are captured by the server process.

### Capturing Logs to a File

If you want to save logs for later analysis:

```powershell
# Linux/Mac
uv run repowise serve 2>&1 | tee server.log

# PowerShell (Windows)
uv run repowise serve 2>&1 | Tee-Object -FilePath server.log
```

## Common Log Messages

### Success Indicators
- `RepoWise server starting (log level: ...)`
- `OpenAI-compatible base URL: ...`
- `Chat provider resolved: ...`
- `Starting agentic loop for repo ...`

### Error Indicators
- `Failed to get chat provider: ...` → Provider not configured correctly
- `Provider error during chat: ...` → LLM API error (check credentials/quota)
- `Chat stream error` → Unexpected error in chat processing
- `Conversation not found` → Repository ID or conversation ID is invalid

