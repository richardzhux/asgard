import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { cookies } from "next/headers";
import { createServerComponentClient } from "@supabase/auth-helpers-nextjs";
import Providers from "@/components/providers";
import { AuthControls } from "@/components/auth-controls";

export const metadata: Metadata = {
  title: "Asgard Lit Review",
  description: "Control panel for the lit review pipeline."
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const supabase = createServerComponentClient({ cookies });
  const {
    data: { session }
  } = await supabase.auth.getSession();

  return (
    <html lang="en">
      <body>
        <Providers initialSession={session}>
          <div className="container">
            <header className="flex items-center justify-between py-4">
              <div className="font-semibold text-lg">Asgard</div>
              <AuthControls />
            </header>
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
