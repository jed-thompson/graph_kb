'use client';

import { useEffect, useRef, useMemo, useState } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { CollapsibleSection } from '@/components/ui/collapsible';
import {
  Calculator, ListFilter, Database, Search, Wrench, Send,
  Cpu, MessageSquare, PlayCircle, BarChart3, Loader2, Sparkles, Check,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

/** Only auto-scroll when user is already near the bottom */
const SCROLL_THRESHOLD = 80;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ThinkingStep {
  timestamp: number;
  phase: string;
  message: string;
}

interface StepGroup {
  id: string;
  name: string;
  steps: ThinkingStep[];
  variant: 'default' | 'violet' | 'emerald' | 'amber' | 'sky';
}

interface ThinkingStepsPanelProps {
  steps: ThinkingStep[];
  /** @deprecated No longer used — panel is always full-width */
  isOpen?: boolean;
  /** @deprecated No longer used — groups are individually collapsible */
  onToggle?: () => void;
}

// ---------------------------------------------------------------------------
// Step categorization
// ---------------------------------------------------------------------------

interface StepCategory {
  label: string;
  icon: LucideIcon;
  color: string;
}

const CATEGORIES: Record<string, StepCategory> = {
  starting:      { label: 'Phase Start',      icon: PlayCircle,    color: 'text-blue-500' },
  budget_check:  { label: 'Budget Check',      icon: Calculator,   color: 'text-amber-500' },
  task_selector: { label: 'Task Selection',    icon: ListFilter,   color: 'text-blue-500' },
  fetch_context: { label: 'Fetching Context',  icon: Database,     color: 'text-cyan-500' },
  gap:           { label: 'Gap Analysis',      icon: Search,       color: 'text-orange-500' },
  task_research: { label: 'Task Research',     icon: Search,       color: 'text-indigo-500' },
  tool_plan:     { label: 'Tool Planning',     icon: Wrench,       color: 'text-violet-500' },
  dispatch:      { label: 'Dispatching Agent', icon: Send,         color: 'text-teal-500' },
  started:       { label: 'Task Started',      icon: PlayCircle,   color: 'text-green-500' },
  completed:     { label: 'Task Complete',     icon: Check,        color: 'text-green-500' },
  worker:        { label: 'Executing Task',    icon: Cpu,          color: 'text-green-500' },
  critique:      { label: 'Quality Review',    icon: MessageSquare,color: 'text-pink-500' },
  progress:      { label: 'Progress Update',   icon: BarChart3,    color: 'text-gray-500' },
};

const PREP_TYPES = new Set(['budget_check', 'task_selector', 'fetch_context', 'gap']);
const EXEC_TYPES = new Set(['task_research', 'tool_plan', 'dispatch', 'started', 'worker', 'critique', 'progress']);

function stepType(msg: string): string {
  const m = msg.match(/^([a-z_]+)[:\s.]+/i);
  if (m) return m[1].toLowerCase();
  if (msg.startsWith('Critique')) return 'critique';
  // Map custom orchestrate progress messages to known categories
  if (msg.startsWith('Executing task') || msg.startsWith("Task '")) return 'worker';
  if (msg.startsWith('Reviewing output')) return 'critique';
  if (msg.startsWith('Researching context')) return 'task_research';
  return 'unknown';
}

function extractTaskName(msg: string): string | null {
  const s = msg.match(/^Started:\s*(.+)/);
  if (s) return s[1].trim();
  const q = msg.match(/'([^']+)'/);
  return q ? q[1] : null;
}

function descriptive(msg: string): string {
  let clean = msg.replace(/^[a-z_]+[:\s.]+/i, '').trim();
  clean = clean.replace(/^\[Task\]:\s*/i, '').trim();
  return clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : msg;
}

// ---------------------------------------------------------------------------
// Grouping logic — groups steps by task name
// ---------------------------------------------------------------------------

function groupSteps(steps: ThinkingStep[]): StepGroup[] {
  if (!steps.length) return [];
  const groups: StepGroup[] = [];
  let prep: ThinkingStep[] = [];
  let activeGroupId: string | null = null;

  const flush = (gid?: string) => {
    if (!prep.length) return;
    if (gid) {
      const g = groups.find(x => x.id === gid);
      if (g) g.steps = [...prep, ...g.steps];
    } else {
      groups.push({ id: 'setup', name: 'Setup', steps: [...prep], variant: 'sky' });
    }
    prep = [];
  };

  for (const step of steps) {
    const type = stepType(step.message);
    const name = extractTaskName(step.message);
    const isStarted = step.message.startsWith('Started:');

    if (isStarted && name) {
      flush(activeGroupId ?? undefined);
      activeGroupId = `task-${groups.length}`;
      groups.push({ id: activeGroupId, name, steps: [step], variant: 'violet' });
    } else if (name && EXEC_TYPES.has(type)) {
      const existing = groups.find(g => g.name === name);
      if (existing) {
        existing.steps.push(step);
        activeGroupId = existing.id;
      } else {
        flush(activeGroupId ?? undefined);
        activeGroupId = `task-${groups.length}`;
        groups.push({ id: activeGroupId, name, steps: [step], variant: 'violet' });
      }
    } else if (PREP_TYPES.has(type)) {
      prep.push(step);
    } else if (EXEC_TYPES.has(type) && activeGroupId) {
      groups.find(g => g.id === activeGroupId)?.steps.push(step);
    } else {
      activeGroupId
        ? groups.find(g => g.id === activeGroupId)?.steps.push(step)
        : prep.push(step);
    }
  }

  flush(activeGroupId ?? undefined);
  return groups;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function relTime(ts: number): string {
  const d = Math.floor((Date.now() - ts) / 1000);
  if (d < 5) return 'just now';
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  return `${Math.floor(d / 3600)}h ago`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StepRow({ step, tick }: { step: ThinkingStep; tick: number }) {
  const type = stepType(step.message);
  const cat = CATEGORIES[type] || { label: type, icon: PlayCircle, color: 'text-gray-400' };
  const Icon = cat.icon;
  const desc = descriptive(step.message);
  const truncated = step.message.endsWith('...');
  const isCritiqueResult = step.message.startsWith('Critique [Task]');

  // tick triggers re-render so relTime() recalculates
  void tick;

  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${cat.color}`} />
      <div className="flex-1 min-w-0">
        <p className={`text-xs leading-relaxed ${truncated ? 'text-muted-foreground/50 italic' : 'text-muted-foreground'}`}>
          <span className="font-medium">{cat.label}</span>
          {!truncated && desc ? <span className="ml-1.5">- {desc}</span> : null}
        </p>
        {isCritiqueResult && (
          <p className="text-xs text-muted-foreground/60 mt-1 line-clamp-2 whitespace-pre-wrap">
            {step.message.replace(/^Critique \[Task\]:\s*/i, '')}
          </p>
        )}
      </div>
      <span className="text-[10px] text-muted-foreground/40 whitespace-nowrap shrink-0">
        {relTime(step.timestamp)}
      </span>
    </div>
  );
}

function StatusBadge({ steps }: { steps: ThinkingStep[] }) {
  const complete = steps.some(s => s.message.includes('execution complete'));
  const critiqued = steps.some(s => /^Critique\b/.test(s.message) && !s.message.startsWith('critique'));
  const retried = steps.filter(s => s.message.includes('Executing task')).length > 1;

  if (complete && critiqued) {
    return (
      <Badge variant="secondary" className="text-[10px] bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
        {retried ? 'Reviewed (Revised)' : 'Reviewed'}
      </Badge>
    );
  }
  if (complete) {
    return (
      <Badge variant="secondary" className="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
        Draft Complete
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
      <Loader2 className="h-2.5 w-2.5 animate-spin mr-1" />In Progress
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const VARIANTS: StepGroup['variant'][] = ['sky', 'violet', 'emerald', 'amber', 'default'];

export function ThinkingStepsPanel({ steps }: ThinkingStepsPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const isNearBottom = useRef(true);
  const [tick, setTick] = useState(0);
  const groups = useMemo(() => groupSteps(steps), [steps]);
  const prevLen = useRef(steps.length);

  // Attach scroll listener to Radix Viewport inside ScrollArea
  useEffect(() => {
    const el = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null;
    if (!el) return;
    const onScroll = () => {
      isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Only auto-scroll when user is near the bottom
  useEffect(() => {
    if (steps.length > prevLen.current && isNearBottom.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevLen.current = steps.length;
  }, [steps.length]);

  // Refresh relative timestamps every 30s
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  if (!steps.length) {
    return (
      <div className="w-full text-center py-8">
        <Loader2 className="h-6 w-6 mx-auto text-muted-foreground/30 animate-spin mb-2" />
        <p className="text-sm text-muted-foreground">Agent is starting up...</p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium text-muted-foreground">Thinking Steps</h3>
        <span className="text-xs text-muted-foreground/40 ml-auto">{steps.length} steps</span>
      </div>
      <ScrollArea className="max-h-[600px]" ref={scrollAreaRef}>
        <div className="space-y-3">
          {groups.map((group, gi) => {
            const isLatest = gi === groups.length - 1;
            const variant = group.id === 'setup' ? 'sky' : VARIANTS[gi % VARIANTS.length];

            return (
              <CollapsibleSection
                key={group.id}
                title={group.name}
                variant={variant}
                size="sm"
                defaultOpen={isLatest}
                badge={group.id === 'setup'
                  ? <Badge variant="secondary" className="text-[10px]">Setup</Badge>
                  : <StatusBadge steps={group.steps} />}
              >
                <div className="divide-y divide-border/30">
                  {group.steps.map((step, si) => (
                    <StepRow key={`${step.timestamp}-${si}`} step={step} tick={tick} />
                  ))}
                </div>
              </CollapsibleSection>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  );
}

export default ThinkingStepsPanel;
