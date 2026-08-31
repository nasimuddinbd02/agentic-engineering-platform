import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Engineering Agent",
  description: "An engineering control plane around a coding-capable LLM.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="masthead">
          <div className="inner">
            <h1>
              <Link href="/">AI Engineering Agent</Link>
            </h1>
            <span className="tagline">
              the LLM is the reasoning worker; this is the control plane
            </span>
          </div>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
