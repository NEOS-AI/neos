"use client";

import { Message } from "@/lib/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Clock, CheckCircle2 } from "lucide-react";

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className="group w-full hover:bg-claude-dark/30 transition-colors">
      <div className="max-w-3xl mx-auto px-6 py-6">
        <div className="flex gap-4 items-start">
          {/* Avatar - Always on the left */}
          <div className="flex-shrink-0 mt-1">
            {isUser ? (
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                <User size={16} className="text-white" />
              </div>
            ) : (
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white font-bold text-sm">
                N
              </div>
            )}
          </div>

          {/* Message Content */}
          <div className="flex-1 min-w-0 pt-0.5">
            {/* Role Label */}
            <div className="text-sm font-semibold mb-2 text-claude-text">
              {isUser ? "You" : "NEOS"}
            </div>

            {/* Content */}
            <div className="text-claude-text">
              {isUser ? (
                <div className="whitespace-pre-wrap text-[15px] leading-relaxed">
                  {message.content}
                </div>
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  className="markdown-content prose prose-invert max-w-none text-[15px]"
                  components={{
                    p: ({ children }) => <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>,
                    code: ({ inline, children, ...props }: any) =>
                      inline ? (
                        <code className="bg-black/40 border border-claude-border px-1.5 py-0.5 rounded text-[13px] font-mono text-orange-300" {...props}>
                          {children}
                        </code>
                      ) : (
                        <code className="block bg-black/60 border border-claude-border p-4 rounded-lg overflow-x-auto text-[13px] leading-relaxed" {...props}>
                          {children}
                        </code>
                      ),
                    pre: ({ children }) => <pre className="my-4 overflow-hidden rounded-lg">{children}</pre>,
                    ul: ({ children }) => <ul className="mb-4 space-y-2">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-4 space-y-2">{children}</ol>,
                    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              )}
            </div>

            {/* Metadata */}
            {message.metadata && !isUser && (
              <div className="flex items-center gap-4 mt-3 text-xs text-claude-text-secondary">
                {message.metadata.execution_time && (
                  <div className="flex items-center gap-1.5">
                    <Clock size={12} />
                    <span>{(message.metadata.execution_time / 1000).toFixed(2)}s</span>
                  </div>
                )}
                {message.metadata.quality_score && (
                  <div className="flex items-center gap-1.5">
                    <CheckCircle2 size={12} />
                    <span>{(message.metadata.quality_score * 100).toFixed(0)}%</span>
                  </div>
                )}
                {message.metadata.agent_used && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-orange-500">•</span>
                    <span>{message.metadata.agent_used}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
