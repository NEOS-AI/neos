"use client";

import { Message } from "@/lib/types";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Clock, CheckCircle2 } from "lucide-react";

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {/* Avatar */}
      {!isUser && (
        <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-white font-semibold flex-shrink-0">
          N
        </div>
      )}

      {/* Message Content */}
      <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start", "max-w-2xl")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3",
            isUser
              ? "bg-primary text-white"
              : "bg-claude-light text-claude-text"
          )}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              className="markdown-content prose prose-invert max-w-none"
              components={{
                // Custom components for better styling
                p: ({ children }) => <p className="mb-4 last:mb-0">{children}</p>,
                code: ({ inline, children, ...props }: any) =>
                  inline ? (
                    <code className="bg-claude-dark px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className="block bg-claude-dark p-3 rounded-lg overflow-x-auto" {...props}>
                      {children}
                    </code>
                  ),
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}
        </div>

        {/* Metadata */}
        {message.metadata && !isUser && (
          <div className="flex items-center gap-3 text-xs text-claude-text-secondary px-2">
            {message.metadata.execution_time && (
              <div className="flex items-center gap-1">
                <Clock size={12} />
                <span>{(message.metadata.execution_time / 1000).toFixed(2)}s</span>
              </div>
            )}
            {message.metadata.quality_score && (
              <div className="flex items-center gap-1">
                <CheckCircle2 size={12} />
                <span>Quality: {(message.metadata.quality_score * 100).toFixed(0)}%</span>
              </div>
            )}
            {message.metadata.agent_used && (
              <div className="flex items-center gap-1">
                <span className="text-primary">•</span>
                <span>{message.metadata.agent_used}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* User Avatar */}
      {isUser && (
        <div className="w-8 h-8 bg-claude-light rounded-lg flex items-center justify-center text-claude-text flex-shrink-0">
          <User size={18} />
        </div>
      )}
    </div>
  );
}
