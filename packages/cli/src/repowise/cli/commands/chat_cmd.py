"""``repowise chat`` — streaming agentic chat against the codebase wiki."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule

from repowise.cli.helpers import (
    console,
    ensure_repowise_dir,
    get_db_url_for_repo,
    resolve_command_target,
    run_async,
)

_MAX_AGENTIC_LOOPS = 10

_SYSTEM_PROMPT_TEMPLATE = """You are a codebase intelligence assistant for the repository "{repo_name}" located at {repo_path}.

You have access to 6 specialized tools for querying the codebase wiki, dependency graph, git history, and architectural decisions.

## Documentation-first rule (CRITICAL)

When a user asks how to use, instantiate, configure, or extend any component, class, function, module, or API in this repository:
1. ALWAYS call get_context (or search_codebase if you don't know the exact path) BEFORE answering.
2. Base your answer on what the tool returns — not on your training data.
3. Only fall back to your training data if the tool returns no documentation at all (empty result or explicit "not found"). In that case, say clearly: "The wiki has no documentation for this — the following is based on general knowledge and may not reflect this repo's implementation."

Never assume how something works in this codebase from training data alone. This repository may use patterns, APIs, or conventions that differ from what you were trained on.

## Tool usage guidelines

- Questions about how to use a specific component/class/function → get_context with the relevant file or symbol name
- Questions about where something is implemented → search_codebase first, then get_context on the results
- General "what does this repo do" questions with no prior context → get_overview first
- "Why was this built this way" questions → get_why
- Risk or impact of changing something → get_risk
- Batch targets: pass all relevant paths to get_context or get_risk in a single call — never call the same tool twice for different targets
- Cite specific file paths, function names, and line numbers from tool results — be concrete, not general
- Format responses in markdown. File paths in backticks. Code in fenced blocks.
- Synthesize and explain tool results — do not dump raw content
- If a tool returns an error, explain what happened and suggest alternatives"""


async def _run_chat(
    repo_path: Path,
    message: str | None,
    provider_name: str | None,
    model: str | None,
    no_markdown: bool,
) -> None:
    """Set up tool state and run the chat REPL (or single-turn if message given)."""
    from repowise.core.persistence import (
        create_engine,
        create_session_factory,
        init_db,
    )
    from repowise.core.persistence.search import FullTextSearch
    from repowise.core.persistence.vector_store import InMemoryVectorStore
    from repowise.core.providers.embedding.mock import MockEmbedder
    from repowise.core.providers.llm.base import ChatProvider
    from repowise.server.chat_tools import (
        execute_tool,
        get_tool_schemas_for_llm,
        init_tool_state,
    )

    # --- DB setup ---
    db_url = get_db_url_for_repo(repo_path)
    engine = create_engine(db_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    # --- FTS setup ---
    fts = FullTextSearch(engine)
    await fts.ensure_index()

    # --- Vector store (minimal — CLI doesn't load embeddings into memory) ---
    vector_store = InMemoryVectorStore(embedder=MockEmbedder())

    # --- Wire MCP tool globals ---
    init_tool_state(
        session_factory=session_factory,
        fts=fts,
        vector_store=vector_store,
        repo_path=str(repo_path),
    )

    # --- Resolve repo name ---
    from repowise.core.persistence import crud
    from repowise.core.persistence.database import get_session

    repo_name = repo_path.name
    async with get_session(session_factory) as session:
        repo = await crud.get_repository_by_path(session, str(repo_path))
        if repo:
            repo_name = repo.name

    # --- Resolve ChatProvider ---
    if provider_name:
        from repowise.cli.helpers import resolve_provider as _resolve_provider

        provider = _resolve_provider(provider_name, model, repo_path)
    else:
        # Use the server's provider_config which reads from config.yaml / env vars
        try:
            import os

            repowise_dir = repo_path / ".repowise"
            os.environ.setdefault("REPOWISE_CONFIG_DIR", str(repowise_dir))
            from repowise.server.provider_config import get_chat_provider_instance

            provider = get_chat_provider_instance()
        except Exception as exc:
            raise click.ClickException(
                f"No chat provider available: {exc}\n"
                "Run 'repowise init' to configure a provider, or use --provider."
            ) from exc

    if not isinstance(provider, ChatProvider):
        raise click.ClickException(
            f"Provider '{getattr(provider, 'provider_name', provider_name)}' does not support "
            "streaming chat. Use Anthropic, OpenAI, Gemini, Ollama, or LiteLLM."
        )

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        repo_name=repo_name,
        repo_path=str(repo_path),
    )
    tool_schemas = get_tool_schemas_for_llm()

    # In-session message history (OpenAI format) — preserved across turns
    llm_messages: list[dict[str, Any]] = []

    async def _run_turn(user_message: str) -> None:
        """Execute one agentic turn, streaming output to the terminal."""
        llm_messages.append({"role": "user", "content": user_message})

        # Accumulate the full assistant response across agentic loops
        all_text_parts: list[str] = []
        tool_calls_made: list[dict[str, Any]] = []

        async def _tool_executor(name: str, args: dict) -> dict:
            return await execute_tool(name, {"repo": str(repo_path), **args})

        # Print separator before response
        console.print()

        for _loop_idx in range(_MAX_AGENTIC_LOOPS):
            pending_tool_calls: list[dict[str, Any]] = []
            turn_text_parts: list[str] = []

            try:
                async for event in provider.stream_chat(
                    messages=llm_messages,
                    tools=tool_schemas,
                    system_prompt=system_prompt,
                    max_tokens=8192,
                    temperature=0.7,
                    tool_executor=_tool_executor,
                ):
                    if event.type == "text_delta" and event.text:
                        turn_text_parts.append(event.text)
                        all_text_parts.append(event.text)
                        # Stream each token directly — no buffering
                        print(event.text, end="", flush=True)

                    elif event.type == "tool_start" and event.tool_call:
                        tc = event.tool_call
                        pending_tool_calls.append(
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        )
                        console.print(
                            f"\n[dim]  ⚙ {tc.name}[/dim]",
                            end="",
                        )

                    elif event.type == "tool_result" and event.tool_call:
                        # Provider executed tool internally (e.g. Gemini)
                        tc = event.tool_call
                        result = event.tool_result_data or {}
                        tool_calls_made.append(
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments, "result": result}
                        )
                        console.print(f" [green]✓[/green]")
                        # Remove from pending
                        pending_tool_calls = [p for p in pending_tool_calls if p["id"] != tc.id]

            except Exception as exc:
                print()  # end any partial line
                console.print(f"\n[bold red]Error:[/bold red] {exc}")
                return

            # Execute tools the router didn't handle internally
            if pending_tool_calls:
                assistant_text = "".join(turn_text_parts)
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if assistant_text:
                    assistant_msg["content"] = assistant_text
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in pending_tool_calls
                ]
                llm_messages.append(assistant_msg)

                for tc in pending_tool_calls:
                    result = await execute_tool(tc["name"], {"repo": str(repo_path), **tc["arguments"]})
                    tool_calls_made.append(
                        {"id": tc["id"], "name": tc["name"], "arguments": tc["arguments"], "result": result}
                    )
                    console.print(f" [green]✓[/green]")
                    llm_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": tc["name"],
                            "content": json.dumps(result),
                        }
                    )
                continue  # loop back so LLM can synthesize results

            break  # no tool calls — generation complete

        print()  # newline after streamed text

        # Append assistant turn to history
        final_text = "".join(all_text_parts)
        llm_messages.append(
            {
                "role": "assistant",
                "content": final_text,
                **({"tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in tool_calls_made
                ]} if tool_calls_made else {}),
            }
        )

    # --- Single-turn or REPL ---
    if message:
        await _run_turn(message)
    else:
        # Interactive REPL
        console.print(
            f"\n[bold]repowise chat[/bold] — [dim]{repo_name}[/dim]  "
            f"[dim](provider: {getattr(provider, 'provider_name', '?')}"
            f"/{getattr(provider, 'model_name', '?')})[/dim]"
        )
        console.print("[dim]Type your question and press Enter. 'exit' or Ctrl-C to quit.[/dim]")
        console.print()

        while True:
            try:
                user_input = click.prompt("You", prompt_suffix=" > ")
            except (click.Abort, KeyboardInterrupt, EOFError):
                console.print("\n[dim]Bye.[/dim]")
                break

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped.lower() in {"exit", "quit", "bye", ":q"}:
                console.print("[dim]Bye.[/dim]")
                break

            await _run_turn(stripped)


@click.command("chat")
@click.argument("message", required=False, default=None)
@click.option("--path", "path", default=None, type=click.Path(exists=True), help="Repository path.")
@click.option("--provider", "provider_name", default=None, help="Provider override (anthropic, openai, gemini, ollama, litellm).")
@click.option("--model", default=None, help="Model override.")
@click.option(
    "--repo",
    "repo_alias",
    default=None,
    help="Workspace repo alias (implies workspace mode).",
)
@click.option(
    "--no-workspace",
    is_flag=True,
    default=False,
    help="Force single-repo mode even when invoked from a workspace.",
)
@click.option(
    "--no-markdown",
    is_flag=True,
    default=False,
    help="Print plain text instead of rendering markdown.",
)
def chat_command(
    message: str | None,
    path: str | None,
    provider_name: str | None,
    model: str | None,
    repo_alias: str | None,
    no_workspace: bool,
    no_markdown: bool,
) -> None:
    """Stream an agentic chat response about the codebase.

    Pass MESSAGE for a single answer, or omit it for an interactive REPL.

    Examples:

    \b
      repowise chat "What does the auth module do?"
      repowise chat --provider anthropic
      repowise chat --repo backend
    """
    target = resolve_command_target(
        path=path,
        no_workspace_flag=no_workspace,
        repo_alias=repo_alias,
    )
    target.notice(console, command="chat")

    if target.is_workspace:
        if target.repo_filter is not None:
            picked = target.resolve_repo_alias(target.repo_filter)
            if picked is None:
                raise click.ClickException(f"Unknown repo alias: {target.repo_filter}")
            repo_path = picked
        else:
            primary = target.primary_path()
            if primary is None:
                raise click.ClickException("Workspace has no primary repo configured.")
            repo_path = primary
    else:
        assert target.repo_path is not None
        repo_path = target.repo_path

    repowise_dir = repo_path / ".repowise"
    if not repowise_dir.is_dir():
        raise click.ClickException(
            f"Repository not initialised at {repo_path}. Run 'repowise init' first."
        )

    run_async(_run_chat(repo_path, message, provider_name, model, no_markdown))
