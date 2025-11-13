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
              bg-bg-surface border border-line-soft rounded-2xl
              text-left
              transition-all duration-200
              hover:border-brand-accent/30 hover:bg-action-hover hover:shadow-soft
              hover:scale-[1.02]
              focus:outline-none focus:ring-2 focus:ring-brand-accent/50
              active:scale-100
            "
            aria-label={card.title}
          >
            {/* Icon */}
            <div
              className={`
                flex-shrink-0 p-3 rounded-xl
                ${card.color || "bg-brand-accent/10"}
                shadow-sm
              `}
            >
              <Icon className={`w-5 h-5 ${card.color ? "text-white" : "text-brand-accent"}`} />
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0 space-y-2">
              <h3 className="text-lg font-semibold text-text-primary">
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
                transition-all duration-200
                group-hover:text-brand-accent group-hover:translate-x-1
              "
            />
          </button>
        );
      })}
    </div>
  );
}
