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
    <div className="flex items-center gap-4 mb-8">
      <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-brand-accent/10 flex items-center justify-center">
        <Sparkles className="w-5 h-5 text-brand-accent" />
      </div>
      <div className="flex-1">
        <h1 className="text-display-1 text-text-primary font-semibold">
          {greeting}
        </h1>
        {subtext && (
          <p className="text-body-m text-text-secondary mt-1">
            {subtext}
          </p>
        )}
      </div>
    </div>
  );
}
