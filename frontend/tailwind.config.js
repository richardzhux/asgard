/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./pages/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(210, 40%, 96%)",
        foreground: "hsl(215, 30%, 15%)",
        muted: "hsl(214, 15%, 85%)",
        accent: "hsl(201, 44%, 36%)",
        card: "hsl(0, 0%, 100%)",
        border: "hsl(214, 18%, 86%)"
      },
      fontFamily: {
        sans: ['"Noto Sans JP"', "Inter", "system-ui", "sans-serif"]
      },
      borderRadius: {
        lg: "14px",
        md: "10px",
        sm: "8px"
      }
    }
  },
  plugins: [require("tailwindcss-animate")]
};
