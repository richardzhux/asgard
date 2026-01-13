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
        background: "hsl(210, 36%, 97%)",
        foreground: "hsl(215, 25%, 13%)",
        muted: "hsl(213, 18%, 90%)",
        accent: "hsl(196, 45%, 32%)",
        card: "hsl(0, 0%, 100%)",
        border: "hsl(214, 20%, 88%)"
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
