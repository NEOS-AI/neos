import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        border: "var(--border)",
        primary: {
          DEFAULT: "#CC785C",
          hover: "#B86A4E",
        },
        // Claude-style design tokens
        bg: {
          canvas: "rgb(var(--color-bg-canvas) / <alpha-value>)",
          surface: "rgb(var(--color-bg-surface) / <alpha-value>)",
        },
        text: {
          primary: "rgb(var(--color-text-primary) / <alpha-value>)",
          secondary: "rgb(var(--color-text-secondary) / <alpha-value>)",
          muted: "rgb(var(--color-text-muted) / <alpha-value>)",
        },
        line: {
          soft: "rgb(var(--color-line-soft) / <alpha-value>)",
        },
        brand: {
          accent: "rgb(var(--color-brand-accent) / <alpha-value>)",
        },
        action: {
          hover: "rgba(255, 255, 255, 0.04)",
        },
        chip: {
          bg: "rgb(var(--color-chip-bg) / <alpha-value>)",
          line: "rgb(var(--color-chip-line) / <alpha-value>)",
        },
        // Legacy colors (keep for backward compatibility)
        claude: {
          dark: "#1A1A1A",
          darker: "#0F0F0F",
          light: "#2A2A2A",
          border: "#2A2A2A",
          text: "#E5E5E5",
          "text-secondary": "#9CA3AF",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["Menlo", "Monaco", "Courier New", "monospace"],
      },
      fontSize: {
        "display-1": ["40px", { lineHeight: "1.2", fontWeight: "600" }],
        "body-m": ["15px", { lineHeight: "1.6" }],
        "label-s": ["12px", { lineHeight: "1.4", letterSpacing: "0.02em" }],
      },
      borderRadius: {
        "2xl": "16px",
        "3xl": "24px",
      },
      boxShadow: {
        soft: "0 4px 16px rgba(0, 0, 0, 0.12)",
        "soft-lg": "0 8px 24px rgba(0, 0, 0, 0.15)",
        glow: "0 0 20px rgba(255, 122, 69, 0.2)",
      },
      spacing: {
        18: "4.5rem",
        22: "5.5rem",
      },
    },
  },
  plugins: [],
};

export default config;
