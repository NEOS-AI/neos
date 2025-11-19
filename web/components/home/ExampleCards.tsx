"use client";

import { ArrowRight, LucideIcon } from "lucide-react";

export interface ExampleCard {
  icon: LucideIcon;
  title: string;
  description: string;
  prompt?: string;
  color?: string;
  onClick?: () => void;
}

interface ExampleCardsProps {
  cards: ExampleCard[];
  columns?: 1 | 2 | 3;
}

export default function ExampleCards({ cards, columns = 2 }: ExampleCardsProps) {
  const gridCols = {
    1: "grid-cols-1",
    2: "grid-cols-1 md:grid-cols-2",
    3: "grid-cols-1 md:grid-cols-2 lg:grid-cols-3",
  }[columns];

  return (
    <div className={`grid ${gridCols} gap-4`}>
      {cards.map((card, idx) => {
        const Icon = card.icon;
        return (
          <button
            key={idx}
            onClick={card.onClick}
            className="
              group
              flex items-start gap-4 p-6
              bg-gradient-to-br from-white to-gray-50/50 dark:from-bg-surface dark:to-gray-900/50
              border-2 border-line-soft rounded-3xl
              text-left
              transition-all duration-300
              hover:border-brand-accent/50 hover:shadow-lg hover:shadow-brand-accent/10
              hover:scale-[1.03] hover:-translate-y-1
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              active:scale-100 active:translate-y-0
              animate-fade-in-up
            "
            style={{ animationDelay: `${idx * 100}ms` }}
            aria-label={card.title}
          >
            {/* Icon */}
            <div
              className={`
                flex-shrink-0 p-3 rounded-xl
                ${card.color || "bg-gradient-to-br from-orange-400/20 via-amber-500/20 to-amber-600/20"}
                shadow-md
                transition-all duration-300
                group-hover:scale-110 group-hover:shadow-lg
              `}
            >
              <Icon className={`w-6 h-6 ${card.color ? "text-white" : "text-brand-accent"}`} />
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0 space-y-2">
              <h3 className="text-lg font-bold text-text-primary group-hover:text-brand-accent transition-colors">
                {card.title}
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed">
                {card.description}
              </p>
            </div>

            {/* Arrow icon */}
            <ArrowRight
              className="
                flex-shrink-0 w-5 h-5 mt-1
                text-text-muted
                transition-all duration-300
                group-hover:text-brand-accent group-hover:translate-x-2
              "
            />
          </button>
        );
      })}
    </div>
  );
}
