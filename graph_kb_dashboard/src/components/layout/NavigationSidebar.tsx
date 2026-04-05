'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import {
  Home,
  BarChart3,
  MessageSquare,
  GitBranch,
  Settings,
  Sun,
  Moon,
  Sparkles,
  FileText,
  Network,
  BookOpen,
  Map,
  HelpCircle,
  ChevronRight,
  ChevronLeft,
  PanelLeftClose,
  PanelLeft,
} from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';
import { useSidebar } from '@/context/SidebarContext';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  badge?: number;
  children?: NavItem[];
}

const navItems: NavItem[] = [
  {
    path: '/',
    label: 'Dashboard',
    icon: <Home className="h-5 w-5" />,
  },
  {
    path: '/repositories',
    label: 'Repositories',
    icon: <GitBranch className="h-5 w-5" />,
    children: [
      { path: '/repositories', label: 'All Repositories', icon: <GitBranch className="h-4 w-4" /> },
      { path: '/graph-stats', label: 'Analytics', icon: <BarChart3 className="h-4 w-4" /> },
      { path: '/visualize', label: 'Visualize', icon: <Network className="h-4 w-4" /> },
    ],
  },
  {
    path: '/chat',
    label: 'Chat',
    icon: <MessageSquare className="h-5 w-5" />,
  },
  {
    path: '/documents',
    label: 'Documents',
    icon: <FileText className="h-5 w-5" />,
  },
  {
    path: '/plan',
    label: 'Plan',
    icon: <Map className="h-5 w-5" />,
  },
  {
    path: '/settings',
    label: 'Settings',
    icon: <Settings className="h-5 w-5" />,
  },
  {
    path: '/help',
    label: 'Help',
    icon: <HelpCircle className="h-5 w-5" />,
  },
];

export function NavigationSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const { isCollapsed, toggleCollapsed, setCollapsed } = useSidebar();
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set(['/repositories']));
  const prevPathnameRef = useRef(pathname);

  // Auto-collapse sidebar when navigating TO chat page (only on initial navigation, not every render)
  useEffect(() => {
    if (prevPathnameRef.current !== pathname && pathname === '/chat') {
      setCollapsed(true);
    }
    prevPathnameRef.current = pathname;
  }, [pathname, setCollapsed]);

  const handleNav = (path: string) => {
    router.push(path);
  };

  const handleToggle = (path: string) => {
    setExpandedItems((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const renderItem = (item: NavItem, isChild = false) => {
    const isActive = isChild
      ? pathname === item.path
      : pathname === item.path || pathname.startsWith(item.path + '/');
    const isExpanded = expandedItems.has(item.path);
    const hasChildren = item.children && item.children.length > 0;

    const navButton = (
      <Button
        onClick={() => {
          if (hasChildren && !isCollapsed) {
            handleToggle(item.path);
          }
          handleNav(item.path);
        }}
        variant={isActive ? 'secondary' : 'ghost'}
        className={cn(
          'w-full justify-start',
          isActive && 'bg-secondary/50 text-muted-foreground'
        )}
      >
        <span className="shrink-0">{item.icon}</span>
        {hasChildren && !isCollapsed && (
          <ChevronRight
            className={cn(
              'h-4 w-4 transition-transform',
              isExpanded && 'rotate-90'
            )}
          />
        )}
        <span className={cn('ml-3', isCollapsed && 'hidden')}>{item.label}</span>
        {item.badge !== undefined && item.badge > 0 && !isCollapsed && (
          <Badge variant="secondary" className="ml-auto">
            {item.badge}
          </Badge>
        )}
      </Button>
    );

    return (
      <div key={item.path} className="space-y-1">
        {isCollapsed ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                {navButton}
              </TooltipTrigger>
              <TooltipContent side="right">
                {item.label}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          navButton
        )}

        {/* Sub items - only show when expanded and not collapsed */}
        {isExpanded && hasChildren && !isCollapsed && (
          <div className="ml-4 pl-2 space-y-1">
            {item.children!.map((child) => {
              const childIsActive = pathname === child.path;
              const childButton = (
                <Button
                  onClick={() => handleNav(child.path)}
                  variant={childIsActive ? 'secondary' : 'ghost'}
                  className={cn(
                    'w-full justify-start pl-2',
                    childIsActive && 'bg-secondary/50 text-muted-foreground'
                  )}
                >
                  <span className="shrink-0">{child.icon}</span>
                  <span className="ml-3">{child.label}</span>
                </Button>
              );

              return (
                <div key={child.path}>
                  {isCollapsed ? (
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          {childButton}
                        </TooltipTrigger>
                        <TooltipContent side="right">
                          {child.label}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : (
                    childButton
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  return (
    <TooltipProvider>
      <nav className={cn(
        'fixed left-0 top-0 bottom-0 bg-card border-r border-border flex flex-col z-50 transition-all duration-300',
        isCollapsed ? 'w-16' : 'w-64'
      )}>
        {/* Brand */}
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg shrink-0">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <span className={cn('font-semibold text-lg', isCollapsed && 'hidden')}>GraphKB</span>
          </div>
        </div>

        {/* Collapse Toggle - at the top */}
        <div className="p-2 border-b border-border">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                onClick={toggleCollapsed}
                variant="ghost"
                className="w-full justify-start"
              >
                <span className="shrink-0">
                  {isCollapsed ? <PanelLeft className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
                </span>
                <span className={cn('ml-3', isCollapsed && 'hidden')}>
                  {isCollapsed ? 'Expand' : 'Collapse'}
                </span>
              </Button>
            </TooltipTrigger>
            {isCollapsed && (
              <TooltipContent side="right">
                {isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
              </TooltipContent>
            )}
          </Tooltip>
        </div>

        {/* Navigation Items */}
        <div className="flex-1 overflow-y-auto py-4 px-2">
          <div className="space-y-1">
            {navItems.map((item) => renderItem(item))}
          </div>
        </div>

        <Separator />

        {/* Theme Toggle */}
        <div className="p-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                onClick={toggleTheme}
                variant="ghost"
                className="w-full justify-start"
              >
                <span className="shrink-0">
                  {theme === 'light' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
                </span>
                <span className={cn('ml-3', isCollapsed && 'hidden')}>
                  {theme === 'light' ? 'Light Mode' : 'Dark Mode'}
                </span>
              </Button>
            </TooltipTrigger>
            {isCollapsed && (
              <TooltipContent side="right">
                {theme === 'light' ? 'Light Mode' : 'Dark Mode'}
              </TooltipContent>
            )}
          </Tooltip>
        </div>
      </nav>
    </TooltipProvider>
  );
}
