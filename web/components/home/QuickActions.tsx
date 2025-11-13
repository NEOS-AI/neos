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
    <div className="flex flex-wrap justify-center gap-2 mb-8">
      {actions.map((action, idx) => {
        const Icon = action.icon;
        return (
          <button
            key={idx}
            onClick={action.onClick}
            className="
              group
              inline-flex items-center gap-2 px-4 py-2.5
              bg-chip-bg border border-chip-line rounded-2xl
              text-text-primary text-sm font-medium
              transition-all duration-200
              hover:border-brand-accent/50 hover:bg-action-hover hover:shadow-soft
              hover:-translate-y-0.5
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              active:translate-y-0
            "
            aria-label={action.description || action.label}
          >
            <Icon className="w-4 h-4 text-text-secondary group-hover:text-brand-accent transition-colors" />
            <span>{action.label}</span>
          </button>
        );
      })}
    </div>
  );
}
