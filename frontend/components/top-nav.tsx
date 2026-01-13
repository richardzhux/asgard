"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { AuthControls } from "@/components/auth-controls";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/jobs/new", label: "New Job" },
  { href: "/presets", label: "Presets" }
];

export function TopNav() {
  const pathname = usePathname();
  return (
    <header className="flex items-center justify-between py-4 mb-4 border-b border-border/80">
      <div className="flex items-center gap-6">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          Asgard
        </Link>
        <nav className="hidden md:flex items-center gap-2 text-sm">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-full px-3 py-2 transition ${
                  active ? "bg-foreground/10 text-foreground font-medium" : "text-foreground/70 hover:text-foreground hover:bg-border"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-2">
        <Link href="/jobs/new" className="hidden sm:block">
          <Button size="sm">Submit</Button>
        </Link>
        <AuthControls />
      </div>
    </header>
  );
}
