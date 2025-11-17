import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageContentProps {
  content: string;
  isUser: boolean;
  isPending: boolean;
}

/**
 * MessageContent Component
 * Renders message content with markdown support for assistant messages
 */
export default function MessageContent({
  content,
  isUser,
  isPending,
}: MessageContentProps) {
  // User messages - simple pre-wrapped text
  if (isUser) {
    return (
      <div className="whitespace-pre-wrap text-[15px] leading-relaxed">
        {content}
      </div>
    );
  }

  // Pending assistant message - loading dots
  if (isPending && !content) {
    return (
      <div className="flex items-center gap-1 py-2">
        <div className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse" />
        <div
          className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse"
          style={{ animationDelay: "0.2s" }}
        />
        <div
          className="w-2 h-2 bg-claude-text-secondary rounded-full animate-pulse"
          style={{ animationDelay: "0.4s" }}
        />
      </div>
    );
  }

  // Assistant messages - markdown rendering
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="markdown-content prose prose-invert max-w-none text-[15px]"
      components={{
        p: ({ children }) => (
          <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>
        ),
        code: ({ inline, children, ...props }: any) =>
          inline ? (
            <code
              className="bg-black/40 border border-claude-border px-1.5 py-0.5 rounded text-[13px] font-mono text-orange-300"
              {...props}
            >
              {children}
            </code>
          ) : (
            <code
              className="block bg-black/60 border border-claude-border p-4 rounded-lg overflow-x-auto text-[13px] leading-relaxed"
              {...props}
            >
              {children}
            </code>
          ),
        pre: ({ children }) => (
          <pre className="my-4 overflow-hidden rounded-lg">{children}</pre>
        ),
        ul: ({ children }) => <ul className="mb-4 space-y-2">{children}</ul>,
        ol: ({ children }) => <ol className="mb-4 space-y-2">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
      }}
    >
      {content || "..."}
    </ReactMarkdown>
  );
}
