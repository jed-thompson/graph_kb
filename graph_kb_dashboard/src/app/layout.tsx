import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from '@/components/Providers';
import { AppShell } from '@/components/layout/AppShell';
import { WebSocketStatus } from '@/components/WebSocketStatus';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'GraphKB Dashboard',
  description: 'Code knowledge graph management and exploration',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <AppShell>{children}</AppShell>
          <WebSocketStatus />
        </Providers>
      </body>
    </html>
  );
}
