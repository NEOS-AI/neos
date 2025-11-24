"use client";

import { Brain, Database, Sparkles, Code, BookOpen, MessageSquare } from "lucide-react";
import { LucideIcon } from "lucide-react";

interface QuickAction {
  icon: LucideIcon;
  label: string;
  description?: string;
  onClick: () => void;
}

interface QuickActionsProps {
  actions?: QuickAction[];
}

const defaultActions: QuickAction[] = [
  {
    icon: Sparkles,
    label: "Deep Research",
    description: "Comprehensive analysis",
    onClick: () => console.log("Deep Research"),
  },
  {
    icon: Database,
    label: "RAG Query",
    description: "Search knowledge base",
    onClick: () => console.log("RAG Query"),
  },
  {
    icon: Brain,
    label: "Data Analysis",
    description: "Analyze and visualize",
    onClick: () => console.log("Data Analysis"),
  },
  {
    icon: Code,
    label: "Code Review",
    description: "Review code quality",
    onClick: () => console.log("Code Review"),
  },
  {
    icon: BookOpen,
    label: "Learning",
    description: "Educational content",
    onClick: () => console.log("Learning"),
  },
  {
    icon: MessageSquare,
    label: "Casual Chat",
    description: "General conversation",
    onClick: () => console.log("Casual Chat"),
  },
];

export default function QuickActions({ actions = defaultActions }: QuickActionsProps) {
  return (
    <div className="flex flex-wrap justify-center gap-3 mb-8">
      {actions.map((action, idx) => {
        const Icon = action.icon;
        return (
          <button
            key={idx}
            onClick={action.onClick}
            className="
              group
              inline-flex items-center gap-2.5 px-5 py-3
              bg-gradient-to-r from-white to-gray-50 dark:from-chip-bg dark:to-gray-900/50
              border-2 border-chip-line rounded-2xl
              text-text-primary text-sm font-semibold
              transition-all duration-300
              hover:border-brand-accent/60 hover:shadow-md hover:shadow-brand-accent/20
              hover:-translate-y-1 hover:scale-105
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              active:translate-y-0 active:scale-100
              animate-scale-in
            "
            style={{ animationDelay: `${idx * 50}ms` }}
            aria-label={action.description || action.label}
          >
            <div className="p-1 rounded-lg bg-gradient-to-br from-blue-700/10 to-indigo-800/10 group-hover:from-blue-700/20 group-hover:to-indigo-800/20 transition-colors">
              <Icon className="w-4 h-4 text-text-secondary group-hover:text-brand-accent transition-colors" />
            </div>
            <span className="group-hover:text-brand-accent transition-colors">{action.label}</span>
          </button>
        );
      })}
    </div>
  );
}
