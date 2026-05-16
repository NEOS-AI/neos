import type { ArtifactKind } from "@/components/artifact";
import type { Document, Suggestion } from "@/lib/db/schema";

interface BEDocumentResponse {
  id: string;
  created_at: string;
  title: string;
  content: string | null;
  kind: string;
  user_id: string;
}

interface BESuggestionResponse {
  id: string;
  document_id: string;
  document_created_at: string;
  original_text: string;
  suggested_text: string;
  description: string | null;
  is_resolved: boolean;
  user_id: string;
  created_at: string;
}

export function adaptBEDocument(doc: BEDocumentResponse): Document {
  return {
    id: doc.id,
    createdAt: new Date(doc.created_at),
    title: doc.title,
    content: doc.content ?? null,
    kind: doc.kind as ArtifactKind,
    userId: doc.user_id,
  };
}

export function adaptBESuggestion(s: BESuggestionResponse): Suggestion {
  return {
    id: s.id,
    documentId: s.document_id,
    documentCreatedAt: new Date(s.document_created_at),
    originalText: s.original_text,
    suggestedText: s.suggested_text,
    description: s.description ?? null,
    isResolved: s.is_resolved,
    userId: s.user_id,
    createdAt: new Date(s.created_at),
  };
}
