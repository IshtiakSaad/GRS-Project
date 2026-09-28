import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans_Bengali } from "next/font/google";
import { Shell } from "@/components/shell";
import { AuthProvider } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";
import "./globals.css";

// Fonts are downloaded at build time and served from this site: no request to Google.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const bangla = Noto_Sans_Bengali({ subsets: ["bengali"], variable: "--font-bangla", display: "swap" });

export const metadata: Metadata = {
  title: "GRS · অভিযোগ ও সেবা আবেদন",
  description: "Grievance and service requests: apply, follow every step, know when it is due.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#00704f" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="bn" className={`${inter.variable} ${bangla.variable}`}>
      <body className="font-sans antialiased">
        <I18nProvider>
          <AuthProvider>
            <Shell>{children}</Shell>
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
