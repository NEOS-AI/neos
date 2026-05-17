import { z } from "zod";

// ============================================================================
// OpenResponses Standard Input Types
// ============================================================================

/**
 * OpenResponses input_text content part
 */
const inputTextPartSchema = z.object({
  type: z.literal("input_text"),
  text: z.string().min(1).max(2000),
});

/**
 * OpenResponses input_file content part
 */
const inputFilePartSchema = z.object({
  type: z.literal("input_file"),
  file: z.object({
    url: z.string().url(),
    media_type: z.enum(["image/jpeg", "image/png"]),
    name: z.string().min(1).max(100),
  }),
});

/**
 * OpenResponses input part union
 */
const openResponsesPartSchema = z.union([inputTextPartSchema, inputFilePartSchema]);

// ============================================================================
// Legacy Input Types (for backward compatibility)
// ============================================================================

/**
 * @deprecated Use inputTextPartSchema instead
 */
const textPartSchema = z.object({
  type: z.enum(["text"]),
  text: z.string().min(1).max(2000),
});

/**
 * @deprecated Use inputFilePartSchema instead
 */
const filePartSchema = z.object({
  type: z.enum(["file"]),
  mediaType: z.enum(["image/jpeg", "image/png"]),
  name: z.string().min(1).max(100),
  url: z.string().url(),
});

/**
 * @deprecated Use openResponsesPartSchema instead
 */
const legacyPartSchema = z.union([textPartSchema, filePartSchema]);

// ============================================================================
// Combined Part Schema (accepts both formats)
// ============================================================================

/**
 * Part schema that accepts both legacy and OpenResponses formats
 */
const partSchema = z.union([
  // OpenResponses format
  inputTextPartSchema,
  inputFilePartSchema,
  // Legacy format
  textPartSchema,
  filePartSchema,
]);

// ============================================================================
// Request Body Schema
// ============================================================================

export const postRequestBodySchema = z.object({
  id: z.string().uuid(),
  message: z.object({
    id: z.string().uuid(),
    role: z.enum(["user"]),
    parts: z.array(partSchema),
  }),
  selectedChatModel: z.string(),
  selectedVisibilityType: z.enum(["public", "private"]),
  autonomy_level: z.union([z.literal(0), z.literal(1), z.literal(2)]).optional(),
});

export type PostRequestBody = z.infer<typeof postRequestBodySchema>;

// ============================================================================
// Type Exports
// ============================================================================

export type InputTextPart = z.infer<typeof inputTextPartSchema>;
export type InputFilePart = z.infer<typeof inputFilePartSchema>;
export type OpenResponsesPart = z.infer<typeof openResponsesPartSchema>;
export type LegacyTextPart = z.infer<typeof textPartSchema>;
export type LegacyFilePart = z.infer<typeof filePartSchema>;
export type MessagePart = z.infer<typeof partSchema>;

// ============================================================================
// Conversion Utilities
// ============================================================================

/**
 * Convert legacy part to OpenResponses format
 */
export function convertToOpenResponsesPart(
  part: MessagePart
): InputTextPart | InputFilePart {
  if (part.type === "text") {
    return {
      type: "input_text",
      text: part.text,
    };
  }
  if (part.type === "file") {
    return {
      type: "input_file",
      file: {
        url: part.url,
        media_type: part.mediaType,
        name: part.name,
      },
    };
  }
  // Already in OpenResponses format
  return part as InputTextPart | InputFilePart;
}

/**
 * Convert OpenResponses part to legacy format
 */
export function convertToLegacyPart(
  part: MessagePart
): LegacyTextPart | LegacyFilePart {
  if (part.type === "input_text") {
    return {
      type: "text",
      text: part.text,
    };
  }
  if (part.type === "input_file") {
    return {
      type: "file",
      url: part.file.url,
      mediaType: part.file.media_type,
      name: part.file.name,
    };
  }
  // Already in legacy format
  return part as LegacyTextPart | LegacyFilePart;
}
