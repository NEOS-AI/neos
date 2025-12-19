import { auth } from "@/app/(auth)/auth";
import type { ArtifactKind } from "@/components/artifact";
import { callBackendAPI } from "@/lib/backend-api";
import { ChatSDKError } from "@/lib/errors";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");

  if (!id) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameter id is missing"
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:document").toResponse();
  }

  // 백엔드 API 호출
  try {
    const response = await callBackendAPI(`/api/v1/documents/${id}`);

    if (!response.ok) {
      const error = await response.json();
      return Response.json(error, { status: response.status });
    }

    const documents = await response.json();
    return Response.json(documents, { status: 200 });
  } catch (error) {
    console.error("Document GET error:", error);
    return new ChatSDKError("internal_error:document").toResponse();
  }
}

export async function POST(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");

  if (!id) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameter id is required."
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("not_found:document").toResponse();
  }

  const {
    content,
    title,
    kind,
  }: { content: string; title: string; kind: ArtifactKind } =
    await request.json();

  // 백엔드 API 호출
  try {
    const response = await callBackendAPI(`/api/v1/documents`, {
      method: "POST",
      body: JSON.stringify({
        id,
        content,
        title,
        kind,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      return Response.json(error, { status: response.status });
    }

    const document = await response.json();
    return Response.json(document, { status: 200 });
  } catch (error) {
    console.error("Document POST error:", error);
    return new ChatSDKError("internal_error:document").toResponse();
  }
}

export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  const timestamp = searchParams.get("timestamp");

  if (!id) {
    return new ChatSDKError(
      "bad_request:api",
      "Parameter id is required."
    ).toResponse();
  }

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:document").toResponse();
  }

  // 백엔드 API 호출
  try {
    const timestampParam = timestamp ? `?timestamp=${timestamp}` : "";
    const response = await callBackendAPI(
      `/api/v1/documents/${id}${timestampParam}`,
      {
        method: "DELETE",
      }
    );

    if (!response.ok) {
      const error = await response.json();
      return Response.json(error, { status: response.status });
    }

    return new Response(null, { status: 204 });
  } catch (error) {
    console.error("Document DELETE error:", error);
    return new ChatSDKError("internal_error:document").toResponse();
  }
}
