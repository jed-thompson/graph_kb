'use client';

import { useState, useRef, useEffect, useMemo, KeyboardEvent } from 'react';
import { Send, Plus, X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import type { Command } from '@/lib/types/chat';

interface InputAreaProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onCommand?: (command: string, args?: string) => void;
  onAttach?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
}

export function InputArea({
  value,
  onChange,
  onSend,
  onCommand,
  onAttach,
  isLoading = false,
  disabled = false,
}: InputAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showCommandHelp, setShowCommandHelp] = useState(false);
  const [commandFilter, setCommandFilter] = useState('');
  const [filteredCommands, setFilteredCommands] = useState<Command[]>([]);
  const [commandHistory, setCommandHistory] = useState<string[]>(() => {
    if (typeof window !== 'undefined') {
      try {
        return JSON.parse(localStorage.getItem('commandHistory') || '[]');
      } catch {
        return [];
      }
    }
    return [];
  });

  const COMMANDS = useMemo<Command[]>(() => [
    {
      name: 'ask',
      pattern: /^\/ask\s+(.+)$/,
      description: 'Ask a question about the codebase',
      examples: ['/ask Explain the RepositoryDetail component', '/ask What does ingest workflow do?'],
    },
    {
      name: 'ingest',
      pattern: /^\/ingest\s+(.+)$/,
      description: 'Ingest a new repository',
      examples: ['/ingest https://github.com/user/repo', '/ingest https://github.com/user/repo main'],
    },
    {
      name: 'context',
      pattern: /^\/context\s+(add|remove|list|save)(?:\s+(.+))?$/,
      description: 'Manage context entries',
      examples: ['/context save this as "auth context"', '/context list', '/context remove auth-context'],
    },
    {
      name: 'clear',
      pattern: /^\/clear$/,
      description: 'Clear the chat history',
      examples: ['/clear'],
    },
    {
      name: 'model',
      pattern: /^\/model\s+(.+)$/,
      description: 'Switch AI model',
      examples: ['/model claude-sonnet-4', '/model gpt-4'],
    },
    // Agent commands
    {
      name: '@analyst',
      pattern: /^@analyst\s+(.+)$/,
      description: 'Ask the Code Analyst agent',
      examples: ['@analyst explain the auth flow', '@analyst what patterns are used here?'],
    },
    {
      name: '@architect',
      pattern: /^@architect\s+(.+)$/,
      description: 'Ask the Architect agent',
      examples: ['@architect design a caching layer', '@architect how should I structure this module?'],
    },
    {
      name: '@generator',
      pattern: /^@generator\s+(.+)$/,
      description: 'Ask the Code Generator agent',
      examples: ['@generator create a REST endpoint', '@generator write unit tests for this function'],
    },
    {
      name: '@researcher',
      pattern: /^@researcher\s+(.+)$/,
      description: 'Ask the Researcher agent',
      examples: ['@researcher find all uses of deprecated API', '@researcher what libraries do we use for auth?'],
    },
    {
      name: '@reviewer',
      pattern: /^@reviewer\s+(.+)$/,
      description: 'Ask the Reviewer/Critic agent',
      examples: ['@reviewer review this code for issues', '@reviewer what could be improved here?'],
    },
  ], []);

  useEffect(() => {
    if (commandFilter) {
      const filter = commandFilter.toLowerCase();
      const filtered = COMMANDS.filter((cmd) =>
        cmd.name.includes(filter) ||
        (cmd.examples ?? []).some((ex) => ex.toLowerCase().includes(filter))
      );
      setFilteredCommands(filtered);
    } else {
      setFilteredCommands(COMMANDS);
    }
  }, [commandFilter, COMMANDS]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const resizeTextarea = () => {
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 200);
      textarea.style.height = `${newHeight}px`;
    };

    resizeTextarea();
    textarea.addEventListener('input', resizeTextarea);

    return () => textarea.removeEventListener('input', resizeTextarea);
  }, []);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (value.trim().startsWith('/') || value.trim().startsWith('@')) {
        addToHistory(value.trim());
      }
      onSend();
    } else if (e.key === 'Escape') {
      setShowCommandHelp(false);
      setCommandFilter('');
      if (document.activeElement === textareaRef.current) {
        textareaRef.current?.blur();
      }
    }
  };

  const addToHistory = (entry: string) => {
    setCommandHistory((prev) => {
      const deduped = prev.filter((h) => h !== entry);
      const updated = [entry, ...deduped].slice(0, 20);
      localStorage.setItem('commandHistory', JSON.stringify(updated));
      return updated;
    });
  };

  const handleCommandClick = (cmd: Command) => {
    onChange(`/${cmd.name} `);
    setShowCommandHelp(false);
    onCommand?.(cmd.name, '');
    textareaRef.current?.focus();
  };

  const handleHistoryClick = (entry: string) => {
    onChange(entry);
    setShowCommandHelp(false);
    textareaRef.current?.focus();
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    onChange(newValue);
    // Show command help for both / commands and @ agent mentions
    if (newValue.startsWith('/') || newValue.startsWith('@')) {
      setCommandFilter(newValue.slice(1));
      setShowCommandHelp(true);
    } else {
      setShowCommandHelp(false);
    }
  };

  return (
    <div className="relative">
      {showCommandHelp && (
        <Card className="absolute bottom-full left-0 mb-3 p-4 w-80 z-50 border-border bg-popover shadow-lg">
          <ScrollArea className="max-h-64">
            <div className="space-y-2">
              {/* Show command history if available and no filter active */}
              {commandHistory.length > 0 && !commandFilter && (
                <>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 px-3 pb-1">
                    Recent commands
                  </div>
                  {commandHistory.slice(0, 5).map((entry, i) => (
                    <button
                      key={`history-${i}`}
                      onClick={() => handleHistoryClick(entry)}
                      className="w-full text-left hover:bg-accent rounded-md p-3 transition-colors group"
                    >
                      <div className="text-xs font-mono text-primary group-hover:text-primary/90 truncate">
                        {entry}
                      </div>
                    </button>
                  ))}
                  <div className="border-t border-border my-2" />
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 px-3 pb-1">
                    All commands
                  </div>
                </>
              )}
              {filteredCommands.map((cmd) => (
                <button
                  key={cmd.name}
                  onClick={() => handleCommandClick(cmd)}
                  className="w-full text-left hover:bg-accent rounded-md p-3 transition-colors group"
                >
                  <div className="font-medium text-primary group-hover:text-primary/90">
                    /{cmd.name}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {cmd.description}
                  </div>
                  {(cmd.examples?.length ?? 0) > 0 && (
                    <div className="text-xs text-muted-foreground/60 mt-1 font-mono">
                      {cmd.examples?.[0]}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </ScrollArea>
          <div className="text-xs text-muted-foreground mt-2 pt-2 border-t border-border">
            Press <kbd className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono text-[10px]">Esc</kbd> to close
          </div>
        </Card>
      )}

      <Card className="border-t border-border bg-background/95 backdrop-blur-sm p-4 shadow-lg">
        <div className="flex items-end gap-2">
          <Button
            variant="ghost"
            size="icon"
            disabled={disabled || isLoading}
            className="shrink-0 h-10 w-10 rounded-full"
            title="Attach file"
            onClick={onAttach}
          >
            <Plus className="h-5 w-5" />
          </Button>

          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... Use / for commands, @ for agents"
            disabled={disabled || isLoading}
            className={cn(
              'flex-1 min-h-[44px] max-h-[200px] resize-none bg-muted border border-border rounded-xl px-4 py-3 text-foreground placeholder:text-muted-foreground focus:border-primary focus:ring-1 focus:ring-primary/20 transition-all outline-none text-sm',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
          />

          <Button
            onClick={() => {
              if (value.trim().startsWith('/') || value.trim().startsWith('@')) {
                addToHistory(value.trim());
              }
              onSend();
            }}
            disabled={disabled || isLoading || !value.trim()}
            className="shrink-0 rounded-xl px-4 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-500 hover:to-blue-600 text-white font-medium transition-all shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40"
          >
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </Button>
        </div>

        <div className="flex items-center justify-between mt-1 px-2">
          <p className="text-[10px] text-muted-foreground">
            Press <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-[9px]">Enter</kbd> to send,{' '}
            <kbd className="px-1 py-0.5 rounded bg-muted font-mono text-[9px]">Shift+Enter</kbd> for new line
          </p>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 rounded"
            onClick={() => onChange('')}
            disabled={disabled || !value}
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      </Card>
    </div>
  );
}
