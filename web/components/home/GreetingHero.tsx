"use client";

import { Sparkles } from "lucide-react";

interface GreetingHeroProps {
  greeting?: string;
  subtext?: string;
}

export default function GreetingHero({
  greeting = "Welcome to NEOS",
  subtext
}: GreetingHeroProps) {
  return (
    <div className="flex items-start gap-4 animate-fade-in-up">
      <div className="flex-shrink-0 w-14 h-14 rounded-2xl bg-gradient-to-br from-orange-400/20 via-amber-500/20 to-amber-600/20 flex items-center justify-center shadow-lg hover:shadow-xl transition-all duration-300 hover:scale-110 animate-pulse-subtle">
        <Sparkles className="w-7 h-7 text-brand-accent" />
      </div>
      <div className="flex-1 pt-1">
        <h1 className="text-display-1 font-semibold leading-tight bg-gradient-to-r from-gray-900 via-gray-800 to-gray-900 dark:from-gray-100 dark:via-white dark:to-gray-100 bg-clip-text text-transparent">
          {greeting}
        </h1>
        {subtext && (
          <p className="text-body-m text-text-secondary mt-3 font-medium animate-fade-in" style={{ animationDelay: '200ms' }}>
            {subtext}
          </p>
        )}
      </div>
    </div>
  );
}
