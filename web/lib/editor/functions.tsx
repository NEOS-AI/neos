"use client";

import { defaultMarkdownSerializer, MarkdownParser } from "prosemirror-markdown";
import { type Node } from "prosemirror-model";
import { Decoration, DecorationSet, type EditorView } from "prosemirror-view";
import MarkdownIt from "markdown-it";

import { documentSchema } from "./config";
import { createSuggestionWidget, type UISuggestion } from "./suggestions";

// Lazy-initialize markdown parser to avoid circular dependency
let markdownParser: MarkdownParser | null = null;

function getMarkdownParser() {
  if (!markdownParser) {
    // Disable table support in markdown-it since ProseMirror schema doesn't support it
    const md = new MarkdownIt({
      html: false,
      linkify: true,
      typographer: false,
    }).disable(['table']);

    markdownParser = new MarkdownParser(
      documentSchema,
      md,
      {
        // Block nodes
        blockquote: { block: "blockquote" },
        paragraph: { block: "paragraph" },
        list_item: { block: "list_item" },
        bullet_list: { block: "bullet_list" },
        ordered_list: { block: "ordered_list", getAttrs: (tok: any) => ({ order: +(tok.attrGet("start") || 1) }) },
        heading: { block: "heading", getAttrs: (tok: any) => ({ level: +tok.tag.slice(1) }) },
        code_block: { block: "code_block" },
        hr: { node: "horizontal_rule" },

        // Inline nodes
        text: { node: "text" },
        image: { node: "image", getAttrs: (tok: any) => ({ src: tok.attrGet("src"), alt: tok.content }) },
        hardbreak: { node: "hard_break" },

        // Marks (inline formatting)
        em: { mark: "em" },
        strong: { mark: "strong" },
        link: {
          mark: "link",
          getAttrs: (tok: any) => ({
            href: tok.attrGet("href"),
            title: tok.attrGet("title") || null
          })
        },
        code_inline: { mark: "code" },
      }
    );
  }
  return markdownParser;
}

export const buildDocumentFromContent = (content: string) => {
  console.log("[buildDocumentFromContent] Parsing markdown, length:", content.length);

  try {
    const parser = getMarkdownParser();
    const doc = parser.parse(content);
    console.log("[buildDocumentFromContent] Parsed document:", {
      nodeSize: doc?.nodeSize,
      childCount: doc?.childCount,
      textContent: doc?.textContent?.substring(0, 200),
    });
    return doc!;
  } catch (error) {
    console.error("[buildDocumentFromContent] Error parsing markdown:", error);
    // Return empty document on error
    return documentSchema.node("doc", null, [documentSchema.node("paragraph")]);
  }
};

export const buildContentFromDocument = (document: Node) => {
  return defaultMarkdownSerializer.serialize(document);
};

export const createDecorations = (
  suggestions: UISuggestion[],
  view: EditorView
) => {
  const decorations: Decoration[] = [];

  for (const suggestion of suggestions) {
    decorations.push(
      Decoration.inline(
        suggestion.selectionStart,
        suggestion.selectionEnd,
        {
          class: "suggestion-highlight",
        },
        {
          suggestionId: suggestion.id,
          type: "highlight",
        }
      )
    );

    decorations.push(
      Decoration.widget(
        suggestion.selectionStart,
        (currentView) => {
          const { dom } = createSuggestionWidget(suggestion, currentView);
          return dom;
        },
        {
          suggestionId: suggestion.id,
          type: "widget",
        }
      )
    );
  }

  return DecorationSet.create(view.state.doc, decorations);
};
