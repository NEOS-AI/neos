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
          DEFAULT: "#050d4d",
          hover: "#030a3a",
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
        glow: "0 0 20px rgba(5, 13, 77, 0.2)",
      },
      spacing: {
        18: "4.5rem",
        22: "5.5rem",
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-out",
        "fade-in-up": "fadeInUp 0.5s ease-out",
        "fade-in-down": "fadeInDown 0.5s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "slide-in-left": "slideInLeft 0.3s ease-out",
        "scale-in": "scaleIn 0.3s ease-out",
        "pulse-subtle": "pulseSubtle 2s ease-in-out infinite",
        "shimmer": "shimmer 2s linear infinite",
        "bounce-subtle": "bounceSubtle 1s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        fadeInUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeInDown: {
          "0%": { opacity: "0", transform: "translateY(-10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { opacity: "0", transform: "translateX(-20px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        slideInLeft: {
          "0%": { opacity: "0", transform: "translateX(20px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        pulseSubtle: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.8" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-1000px 0" },
          "100%": { backgroundPosition: "1000px 0" },
        },
        bounceSubtle: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-4px)" },
        },
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};

export default config;
