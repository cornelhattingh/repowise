/**
 * Streaming proxy for the chat SSE endpoint.
 *
 * Next.js rewrites buffer the full response before sending it to the browser,
 * which breaks SSE streaming — the loading indicator spins until the entire
 * response is ready and then it all appears at once.
 *
 * Route Handlers take precedence over rewrites for the same path, and they
 * support returning a ReadableStream body directly, so we proxy the request
 * here and pipe upstream.body straight to the client with zero buffering.
 */

import type { NextRequest } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ repoId: string }> },
) {
  const { repoId } = await params;

  const apiUrl =
    process.env.REPOWISE_API_URL ||
    process.env.NEXT_PUBLIC_REPOWISE_API_URL ||
    "http://localhost:7337";

  const body = await request.text();

  const forwardHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const auth = request.headers.get("Authorization");
  if (auth) forwardHeaders["Authorization"] = auth;

  let upstream: Response;
  try {
    upstream = await fetch(`${apiUrl}/api/repos/${repoId}/chat/messages`, {
      method: "POST",
      headers: forwardHeaders,
      body,
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ detail: `Backend unreachable: ${err}` }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "text/plain" },
    });
  }

  // Pipe the upstream ReadableStream directly — no buffering.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
