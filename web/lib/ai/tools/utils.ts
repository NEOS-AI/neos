/**
 * Tool Utility Functions for OpenResponses Specification
 *
 * Provides utilities to convert internal tool definitions to OpenResponses format.
 * @see https://www.openresponses.org/specification
 */

import type { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import type { Tool } from "ai";

// ============================================================================
// OpenResponses Tool Types
// ============================================================================

/**
 * OpenResponses function tool parameter schema
 */
export interface OpenResponsesToolParameters {
  type: "object";
  properties: Record<string, JsonSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

/**
 * JSON Schema property definition
 */
export interface JsonSchemaProperty {
  type: string;
  description?: string;
  enum?: string[];
  items?: JsonSchemaProperty;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  default?: unknown;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
}

/**
 * OpenResponses function tool definition
 */
export interface OpenResponsesFunctionTool {
  type: "function";
  name: string;
  description: string;
  parameters: OpenResponsesToolParameters;
  strict?: boolean;
}

/**
 * OpenResponses tool definition (currently only function type is supported)
 */
export type OpenResponsesToolDefinition = OpenResponsesFunctionTool;

/**
 * Collection of OpenResponses tools
 */
export interface OpenResponsesToolCollection {
  tools: OpenResponsesToolDefinition[];
}

// ============================================================================
// Conversion Functions
// ============================================================================

/**
 * Convert a Zod schema to OpenResponses tool parameters format
 *
 * @param schema - Zod schema to convert
 * @returns OpenResponses compatible parameter schema
 */
export function zodSchemaToOpenResponsesParameters<T extends z.ZodType>(
  schema: T
): OpenResponsesToolParameters {
  const jsonSchema = zodToJsonSchema(schema, {
    $refStrategy: "none",
    target: "openApi3",
  });

  // Extract properties and required fields from JSON Schema
  const schemaObj = jsonSchema as {
    type?: string;
    properties?: Record<string, JsonSchemaProperty>;
    required?: string[];
    additionalProperties?: boolean;
  };

  return {
    type: "object",
    properties: schemaObj.properties || {},
    required: schemaObj.required,
    additionalProperties: schemaObj.additionalProperties ?? false,
  };
}

/**
 * Convert a Vercel AI SDK tool to OpenResponses format
 *
 * @param name - Tool name (used as function name)
 * @param tool - Vercel AI SDK tool instance
 * @returns OpenResponses tool definition
 *
 * @example
 * ```typescript
 * const createDocTool = createDocument({ session, dataStream });
 * const openResponsesTool = toOpenResponsesTool("createDocument", createDocTool);
 * // Returns:
 * // {
 * //   type: "function",
 * //   name: "createDocument",
 * //   description: "Create a document...",
 * //   parameters: { type: "object", properties: {...}, required: [...] }
 * // }
 * ```
 */
export function toOpenResponsesTool<TArgs, TResult>(
  name: string,
  tool: Tool<TArgs, TResult>
): OpenResponsesFunctionTool {
  // Access tool's internal properties
  const toolAny = tool as unknown as {
    description?: string;
    parameters?: z.ZodType;
  };

  // Get description (default to empty string if not provided)
  const description = toolAny.description || "";

  // Convert parameters schema
  let parameters: OpenResponsesToolParameters = {
    type: "object",
    properties: {},
    additionalProperties: false,
  };

  if (toolAny.parameters) {
    parameters = zodSchemaToOpenResponsesParameters(toolAny.parameters);
  }

  return {
    type: "function",
    name,
    description,
    parameters,
  };
}

/**
 * Convert multiple tools to OpenResponses format
 *
 * @param tools - Record of tool name to tool instance
 * @returns Array of OpenResponses tool definitions
 *
 * @example
 * ```typescript
 * const tools = {
 *   createDocument: createDocument({ session, dataStream }),
 *   updateDocument: updateDocument({ session, dataStream }),
 * };
 * const openResponsesTools = toOpenResponsesTools(tools);
 * ```
 */
export function toOpenResponsesTools(
  tools: Record<string, Tool<unknown, unknown>>
): OpenResponsesToolDefinition[] {
  return Object.entries(tools).map(([name, tool]) =>
    toOpenResponsesTool(name, tool)
  );
}

/**
 * Create an OpenResponses tool collection from tools record
 *
 * @param tools - Record of tool name to tool instance
 * @returns OpenResponses tool collection object
 */
export function createOpenResponsesToolCollection(
  tools: Record<string, Tool<unknown, unknown>>
): OpenResponsesToolCollection {
  return {
    tools: toOpenResponsesTools(tools),
  };
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Convert tool name from camelCase to snake_case
 * OpenResponses convention often uses snake_case for function names
 *
 * @param name - camelCase name
 * @returns snake_case name
 */
export function toSnakeCase(name: string): string {
  return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

/**
 * Create a standardized OpenResponses tool name
 *
 * @param name - Original tool name
 * @param useSnakeCase - Whether to convert to snake_case (default: true)
 * @returns Standardized tool name
 */
export function standardizeToolName(
  name: string,
  useSnakeCase: boolean = true
): string {
  if (useSnakeCase) {
    return toSnakeCase(name);
  }
  return name;
}

/**
 * Validate that a tool definition conforms to OpenResponses specification
 *
 * @param tool - Tool definition to validate
 * @returns Validation result with any errors
 */
export function validateOpenResponsesTool(tool: OpenResponsesFunctionTool): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];

  if (tool.type !== "function") {
    errors.push(`Invalid tool type: ${tool.type}. Expected "function".`);
  }

  if (!tool.name || typeof tool.name !== "string") {
    errors.push("Tool name is required and must be a string.");
  }

  if (!tool.description || typeof tool.description !== "string") {
    errors.push("Tool description is required and must be a string.");
  }

  if (!tool.parameters || tool.parameters.type !== "object") {
    errors.push('Tool parameters must have type "object".');
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
