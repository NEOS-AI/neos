import { NextRequest, NextResponse } from "next/server";
import { requireSession, fetchWithAuth } from "@/lib/session-helper";
import { BACKEND_URL } from "@/lib/env";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { query, session_id, preferences } = body;

    // Validate required fields
    if (!query) {
      return NextResponse.json(
        { error: "Query is required" },
        { status: 400 }
      );
    }

    // 세션 검증 (선택적 - anonymous 사용자 허용)
    const sessionResult = await requireSession(request);
    let userId = "anonymous";
    let backendResponse: Response;

    if (sessionResult) {
      // 인증된 사용자
      const { session, sessionId } = sessionResult;
      userId = session.user?.user_id || "anonymous";

      // Authorization 헤더 포함하여 FastAPI 호출
      backendResponse = await fetchWithAuth(
        `${BACKEND_URL}/api/v1/query`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            query,
            user_id: userId,
            session_id: session_id || generateSessionId(),
            preferences: preferences || {
              max_iterations: 10,
              agent_timeout: 300,
              response_format: "text",
            },
          }),
        },
        sessionId
      );
    } else {
      // Anonymous 사용자 (인증 없이 진행)
      backendResponse = await fetch(`${BACKEND_URL}/api/v1/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          user_id: "anonymous",
          session_id: session_id || generateSessionId(),
          preferences: preferences || {
            max_iterations: 10,
            agent_timeout: 300,
            response_format: "text",
          },
        }),
      });
    }

    if (!backendResponse.ok) {
      const errorData = await backendResponse.json().catch(() => ({}));
      return NextResponse.json(
        {
          error: errorData.detail || "Failed to process query",
          status: backendResponse.status,
        },
        { status: backendResponse.status }
      );
    }

    const data = await backendResponse.json();

    // Return the response with additional metadata
    return NextResponse.json({
      success: true,
      response: data.response,
      metadata: {
        ...data.metadata,
        execution_time: data.execution_time,
        quality_score: data.quality_score,
      },
      session_id: data.metadata?.session_id || session_id,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error("Error processing chat request:", error);
    return NextResponse.json(
      {
        error: "Internal server error",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 }
    );
  }
}

function generateSessionId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}
