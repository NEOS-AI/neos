import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { ReactNode } from "react";

interface MessageContentProps {
  content: string;
  isUser: boolean;
  isPending: boolean;
}

// Type-safe props for code component
interface CodeProps extends React.HTMLAttributes<HTMLElement> {
  inline?: boolean;
  children?: ReactNode;
}

/**
 * MessageContent Component
 * Renders message content with markdown support for assistant messages
 * Modern styling with better typography
 */
export default function MessageContent({
  content,
  isUser,
  isPending,
}: MessageContentProps) {
  // User messages - simple text with white color
  if (isUser) {
    return (
      <div className="text-white leading-relaxed break-words whitespace-pre-wrap">
        {content}
      </div>
    );
  }

  // Pending assistant message - elegant loading dots
  if (isPending && !content) {
    return (
      <div className="flex items-center gap-1.5 py-4">
        <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
        <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
        <div className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
    );
  }

  // Assistant messages - rich markdown rendering
  const markdownComponents: Partial<Components> = {
    p: ({ children }) => (
      <p className="mb-4 last:mb-0 leading-7 text-gray-800 dark:text-gray-200">
        {children}
      </p>
    ),
    code: ({ inline, children, ...props }: CodeProps) =>
      inline ? (
        <code
          className="bg-gray-200 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 px-1.5 py-0.5 rounded text-sm font-mono text-pink-600 dark:text-pink-400"
          {...props}
        >
          {children}
        </code>
      ) : (
        <code
          className="block bg-gray-900 text-gray-100 p-4 rounded-xl overflow-x-auto text-sm leading-relaxed font-mono border border-gray-700"
          {...props}
        >
          {children}
        </code>
      ),
    pre: ({ children }) => (
      <pre className="my-4 overflow-hidden rounded-xl bg-gray-900 border border-gray-700">
        {children}
      </pre>
    ),
    ul: ({ children }) => (
      <ul className="mb-4 space-y-2 list-disc list-inside text-gray-800 dark:text-gray-200">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="mb-4 space-y-2 list-decimal list-inside text-gray-800 dark:text-gray-200">
        {children}
      </ol>
    ),
    li: ({ children }) => (
      <li className="leading-7">{children}</li>
    ),
    h1: ({ children }) => (
      <h1 className="text-2xl font-bold mb-4 mt-6 text-gray-900 dark:text-gray-100">
        {children}
      </h1>
    ),
    h2: ({ children }) => (
      <h2 className="text-xl font-bold mb-3 mt-5 text-gray-900 dark:text-gray-100">
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="text-lg font-semibold mb-2 mt-4 text-gray-900 dark:text-gray-100">
        {children}
      </h3>
    ),
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-blue-500 pl-4 py-2 my-4 italic text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/50 rounded-r">
        {children}
      </blockquote>
    ),
    a: ({ children, href }) => (
      <a
        href={href}
        className="text-blue-600 dark:text-blue-400 hover:underline font-medium"
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    ),
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="prose prose-slate dark:prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-gray-900 prose-pre:text-gray-100"
      components={markdownComponents}
    >
      {content || "..."}
    </ReactMarkdown>
  );
}
