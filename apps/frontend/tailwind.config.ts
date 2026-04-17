import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ["Playfair Display", "serif"],
      },
      colors: {
        brand: {
          50: "#f0fafa",
          500: "#0d7678",
          700: "#0a4d4f",
          900: "#052627",
        },
      },
    },
  },
  plugins: [],
};

export default config;
