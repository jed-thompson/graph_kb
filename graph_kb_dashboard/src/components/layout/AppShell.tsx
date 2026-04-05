'use client';

import { usePathname } from 'next/navigation';
import { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { NavigationSidebar } from './NavigationSidebar';
import { useSidebar } from '@/context/SidebarContext';

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isCollapsed } = useSidebar();

  // All pages now use the same navigation sidebar
  // The chat page integrates into the main layout instead of replacing it
  return (
    <div className="min-h-screen bg-background">
      <NavigationSidebar />
      <main className={cn(
        'min-h-screen transition-all duration-300',
        isCollapsed ? 'ml-16' : 'ml-64'
      )}>
        {children}
      </main>
    </div>
  );
}
