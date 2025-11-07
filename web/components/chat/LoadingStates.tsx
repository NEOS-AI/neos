"use client";

// Skeleton loader for sidebar conversations
export function ConversationSkeleton() {
  return (
    <div className="animate-pulse p-3 rounded-lg">
      <div className="flex items-center gap-3">
        <div className="w-4 h-4 bg-claude-border rounded" />
        <div className="flex-1 space-y-2">
          <div className="h-3 bg-claude-border rounded w-3/4" />
          <div className="h-2 bg-claude-border rounded w-1/2" />
        </div>
      </div>
    </div>
  );
}

// Skeleton loader for messages
export function MessageSkeleton() {
  return (
    <div className="animate-pulse max-w-3xl mx-auto px-6 py-6">
      <div className="flex gap-4 items-start">
        <div className="w-7 h-7 rounded-md bg-claude-border" />
        <div className="flex-1 space-y-3">
          <div className="h-3 bg-claude-border rounded w-1/4" />
          <div className="space-y-2">
            <div className="h-3 bg-claude-border rounded" />
            <div className="h-3 bg-claude-border rounded w-5/6" />
            <div className="h-3 bg-claude-border rounded w-4/6" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Loading spinner
export function LoadingSpinner({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizeClasses = {
    sm: "w-4 h-4",
    md: "w-6 h-6",
    lg: "w-8 h-8",
  };

  return (
    <div className="flex items-center justify-center">
      <div
        className={`${sizeClasses[size]} border-2 border-claude-border border-t-primary rounded-full animate-spin`}
      />
    </div>
  );
}

// Full page loading
export function PageLoading() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-claude-darker">
      <div className="text-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-orange-400 to-amber-600 flex items-center justify-center text-white text-3xl font-bold mx-auto">
          N
        </div>
        <LoadingSpinner size="lg" />
        <p className="text-claude-text-secondary">Loading NEOS...</p>
      </div>
    </div>
  );
}
