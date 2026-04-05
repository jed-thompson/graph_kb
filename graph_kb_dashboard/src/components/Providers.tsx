'use client';

import { ReactNode } from 'react';
import { WebSocketProvider } from '@/context/WebSocketContext';
import { ThemeProvider } from '@/context/ThemeContext';
import { SidebarProvider } from '@/context/SidebarContext';
import { Toaster } from '@/components/notifications/Toaster';

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider defaultTheme="light">
      <SidebarProvider>
        <WebSocketProvider>
          {children}
          <Toaster />
        </WebSocketProvider>
      </SidebarProvider>
    </ThemeProvider>
  );
}
