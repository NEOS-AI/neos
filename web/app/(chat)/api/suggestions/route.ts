import { auth } from "@/app/(auth)/auth";
import { adaptBESuggestion } from "@/lib/adapters/artifact-adapters";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const documentId = searchParams.get("documentId");

  if (!documentId) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameter documentId is required."
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:suggestions").toResponse();
  }

  const res = await callBackendAPI(
    `/api/v1/documents/${documentId}/suggestions`
  );

  if (!res.ok) {
    return Response.json([], { status: 200 });
  }

  const raw: unknown[] = await res.json();

  if (!raw.length) {
    return Response.json([], { status: 200 });
  }

  const suggestions = (raw as Parameters<typeof adaptBESuggestion>[0][]).map(
    adaptBESuggestion
  );

  const [first] = suggestions;
  if (first.userId !== session.user.id) {
    return new ChatSDKError("forbidden:api").toResponse();
  }

  return Response.json(suggestions, { status: 200 });
}
