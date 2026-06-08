import { NextResponse } from "next/server";
import { z } from "zod";

import { auth } from "@/app/(auth)/auth";
import { getBackendUrl } from "@/lib/server-config";

const SUPPORTED_MIME_TYPES = [
  // Images
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  // Documents
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
];

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

const FileSchema = z.object({
  file: z
    .instanceof(Blob)
    .refine((file) => file.size <= MAX_FILE_SIZE, {
      message: "File size should be less than 50MB",
    })
    .refine((file) => SUPPORTED_MIME_TYPES.includes(file.type), {
      message:
        "Unsupported file type. Allowed: JPEG, PNG, GIF, WebP, PDF, DOC, DOCX, TXT, MD",
    }),
});

export async function POST(request: Request) {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  if (!session.backendAccessToken) {
    return NextResponse.json(
      { error: "Authentication token is missing. Please sign in again." },
      { status: 401 }
    );
  }

  if (request.body === null) {
    return new Response("Request body is empty", { status: 400 });
  }

  try {
    const formData = await request.formData();
    const file = formData.get("file") as Blob;

    if (!file) {
      return NextResponse.json({ error: "No file uploaded" }, { status: 400 });
    }

    const validatedFile = FileSchema.safeParse({ file });

    if (!validatedFile.success) {
      const errorMessage = validatedFile.error.errors
        .map((error) => error.message)
        .join(", ");

      return NextResponse.json({ error: errorMessage }, { status: 400 });
    }

    const filename = (formData.get("file") as File).name;
    const userId = session.user.backendUserId;
    if (!userId) {
      return NextResponse.json(
        { error: "Backend user ID not available" },
        { status: 400 }
      );
    }

    // 백엔드로 multipart 전송 (Content-Type은 fetch가 자동으로 boundary 포함하여 설정)
    const backendUrl = getBackendUrl();
    const uploadFormData = new FormData();
    uploadFormData.append("file", file, filename);
    uploadFormData.append("user_id", userId);

    const uploadResponse = await fetch(
      `${backendUrl}/api/v1/documents/upload`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.backendAccessToken}`,
          // Content-Type은 지정하지 않음 — fetch가 multipart boundary를 자동 설정
        },
        body: uploadFormData,
      }
    );

    if (!uploadResponse.ok) {
      const errorText = await uploadResponse.text();
      console.error("[Upload] Backend upload failed:", errorText);
      return NextResponse.json(
        { error: "Failed to upload file to backend" },
        { status: uploadResponse.status }
      );
    }

    const uploadData = await uploadResponse.json();
    // uploadData = { document_id, filename, status, message }

    // document_id로 storage_url 조회
    const docResponse = await fetch(
      `${backendUrl}/api/v1/documents/${uploadData.document_id}`,
      {
        headers: {
          Authorization: `Bearer ${session.backendAccessToken}`,
        },
      }
    );

    if (!docResponse.ok) {
      console.error("[Upload] Failed to fetch document info after upload");
      return NextResponse.json(
        { error: "Failed to retrieve uploaded file info" },
        { status: docResponse.status }
      );
    }

    const docData = await docResponse.json();
    // docData.storage_url — S3/RustFS에 저장된 파일 URL

    return NextResponse.json({
      url: docData.storage_url || null,
      name: uploadData.filename || filename,
      contentType: file.type,
      documentId: uploadData.document_id,
      processingStatus: uploadData.status,
    });
  } catch (_error) {
    console.error("[Upload] Unexpected error:", _error);
    return NextResponse.json(
      { error: "Failed to process request" },
      { status: 500 }
    );
  }
}
