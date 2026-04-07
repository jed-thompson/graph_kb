'use client';

import { useRef, useEffect, useState } from 'react';
import { ChatProvider, useChat } from '@/context/ChatContext';
import { AttachmentProvider, useAttachments } from '@/context/AttachmentContext';
import { InputArea } from '@/components/chat/InputArea';
import { Message } from '@/components/chat/Message';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Input } from '@/components/ui/input';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { MessageSquare, Sparkles, Trash2, Bot, GitBranch, Loader2, Paperclip, X as XIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import Link from 'next/link';
import { ChatHistory } from '@/components/chat/ChatHistory';
import { ResearchControls } from '@/components/research/ResearchControls';
import { cn } from '@/lib/utils';

function ChatPageContent() {
  const {
    messages,
    input,
    setInput,
    sendMessage,
    streamMessage,
    clearChat,
    isStreaming,
    isLoading,
    repositories,
    selectedRepoId,
    setSelectedRepoId,
    // Session management
    createNewChat,
    switchChat,
    deleteChat,
    renameChat,
    activeSessionId,
    sessions,
    // Plan name prompt
    planNameDialogOpen,
    startPlanWithName,
    cancelPlanNameDialog,
  } = useChat();

  const { files: attachedFiles, addFile, removeFile, clearAll: clearAttachments } = useAttachments();

  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isResearchPanelOpen, setIsResearchPanelOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or streaming updates
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

  const handleClear = () => {
    clearChat();
    setInput('');
  };

  const handleSend = () => {
    // Use streaming by default for a better UX
    streamMessage();
  };

  const getRepoName = (repoId: string | null) => {
    const repo = repositories.find((r) => r.id === repoId);
    if (repo) {
      const parts = repo.git_url.split('/');
      return parts[parts.length - 1] || repo.id;
    }
    return 'No repository selected';
  };

  return (
    <div className="flex h-[calc(100vh-2rem)] min-h-0 m-4 bg-background rounded-xl border border-border/50 shadow-sm overflow-hidden">
      {/* Chat Sidebar */}
      <div className={cn(
        'border-r border-border bg-card/50 backdrop-blur-sm flex flex-col min-h-0 transition-all duration-300 relative',
        isSidebarCollapsed ? 'w-12' : 'w-64'
      )}>
        {/* Collapse Toggle Button */}
        <Button
          variant="ghost"
          size="icon"
          className="absolute -right-3 top-4 z-10 h-6 w-6 rounded-full border border-border bg-card shadow-sm hover:bg-accent"
          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        >
          {isSidebarCollapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronLeft className="h-3 w-3" />
          )}
        </Button>

        <div className={cn('p-4 border-b border-border', isSidebarCollapsed && 'p-2')}>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary shrink-0" />
            {!isSidebarCollapsed && (
              <>
                <h2 className="font-semibold">Chat Assistant</h2>
              </>
            )}
          </div>
          {!isSidebarCollapsed && (
            <p className="text-xs text-muted-foreground mt-1">Code knowledge assistant</p>
          )}
        </div>

        {/* Chat History Section */}
        {!isSidebarCollapsed && (
          <div className="border-b border-border">
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider p-2 pb-1">
              Chat History
            </div>
            <ChatHistory
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelectSession={switchChat}
              onCreateSession={createNewChat}
              onDeleteSession={deleteChat}
              onRenameSession={renameChat}
            />
          </div>
        )}

        {!isSidebarCollapsed ? (
          <>
            <div className="flex-1 p-3 overflow-y-auto">
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2 px-2">
                  Quick Actions
                </div>
                <Button variant="ghost" className="w-full justify-start text-sm h-8" size="sm" onClick={createNewChat}>
                  <MessageSquare className="h-4 w-4 mr-2" />
                  New Conversation
                </Button>
                <Link href="/repositories">
                  <Button variant="ghost" className="w-full justify-start text-sm h-8" size="sm">
                    <Bot className="h-4 w-4 mr-2" />
                    Browse Repositories
                  </Button>
                </Link>
              </div>

              <Separator className="my-4" />

              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2 px-2">
                Commands
              </div>
              <div className="space-y-0.5">
                {[
                  { cmd: '/ask', desc: 'Ask a question' },
                  { cmd: '/ingest', desc: 'Add repository' },
                  { cmd: '/clear', desc: 'Clear chat' },
                ].map((item) => (
                  <TooltipProvider key={item.cmd}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          className="w-full justify-start text-xs h-7 px-2"
                          onClick={() => setInput(`${item.cmd} `)}
                        >
                          <Badge variant="secondary" className="mr-2 text-[10px] h-4 px-1.5">
                            {item.cmd}
                          </Badge>
                          <span className="text-muted-foreground">{item.desc}</span>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{item.cmd} - {item.desc}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                ))}
              </div>

            </div>

            <div className="p-3 border-t border-border">
              <Button
                variant="outline"
                className="w-full h-8 text-sm"
                onClick={handleClear}
                disabled={messages.length === 0}
              >
                <Trash2 className="h-3.5 w-3.5 mr-2" />
                Clear Chat
              </Button>
            </div>
          </>
        ) : (
          /* Collapsed view - icon-only buttons */
          <div className="flex-1 flex flex-col items-center py-4 gap-2">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-9 w-9" onClick={createNewChat}>
                    <MessageSquare className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  New Conversation
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link href="/repositories">
                    <Button variant="ghost" size="icon" className="h-9 w-9">
                      <Bot className="h-4 w-4" />
                    </Button>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="right">
                  Browse Repositories
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <Separator className="my-2 w-8" />

            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-9 w-9"
                    onClick={handleClear}
                    disabled={messages.length === 0}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  Clear Chat
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* Header */}
        <div className="flex-shrink-0 border-b border-border bg-card/50 backdrop-blur-sm px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold">Chat</h1>
              <p className="text-sm text-muted-foreground hidden sm:block">Ask questions about your codebase</p>
            </div>
            <Button
              variant={isResearchPanelOpen ? 'default' : 'outline'}
              size="sm"
              className="h-9 gap-2 shrink-0"
              onClick={() => setIsResearchPanelOpen((o) => !o)}
            >
              <GitBranch className="h-4 w-4" />
              <span className="hidden sm:inline">Repos</span>
            </Button>
            <Select value={selectedRepoId || ''} onValueChange={setSelectedRepoId}>
              <SelectTrigger className="w-48 lg:w-56 h-9">
                <GitBranch className="h-4 w-4 mr-2" />
                <SelectValue placeholder="Select repository" />
              </SelectTrigger>
              <SelectContent>
                {repositories.length === 0 ? (
                  <div className="px-2 py-4 text-sm text-muted-foreground">
                    No repositories available
                  </div>
                ) : (
                  repositories.map((repo) => (
                    <SelectItem key={repo.id} value={repo.id}>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{getRepoName(repo.id)}</span>
                        <Badge variant={repo.status === 'ready' ? 'secondary' : 'outline'} className="ml-2 text-xs">
                          {repo.status}
                        </Badge>
                      </div>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 min-h-0" ref={scrollRef}>
          <div className="px-4 py-4">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-[calc(100vh-20rem)] text-muted-foreground">
                <div className="text-center space-y-4">
                  <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center mx-auto">
                    <MessageSquare className="h-7 w-7 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-base font-medium text-foreground">Start a conversation</p>
                    <p className="text-sm mt-1">
                      {selectedRepoId
                        ? 'Ask anything about your codebase'
                        : 'Ask a general question, or select a repository for code-specific answers'}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 justify-center max-w-md mx-auto">
                    {[
                      'Explain the architecture',
                      'Find authentication flow',
                      'List API endpoints',
                    ].map((suggestion) => (
                      <Button
                        key={suggestion}
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => setInput(suggestion)}
                      >
                        {suggestion}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4 w-full max-w-2xl md:max-w-3xl lg:max-w-4xl xl:max-w-5xl mx-auto">
                {messages.map((message) => (
                  <Message
                    key={message.id}
                    message={message}
                    isStreaming={isStreaming && message.metadata?.isStreaming === true}
                  />
                ))}

                {/* Loading spinner while waiting for initial LLM response (before streaming starts) */}
                {isLoading && !isStreaming && (
                  <div className="flex gap-4">
                    <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0">
                      <span className="text-primary-foreground font-medium text-xs">AI</span>
                    </div>
                    <div className="flex-1 rounded-2xl p-4 bg-muted">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span className="text-sm">Thinking...</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Input Area */}
        <div className="flex-shrink-0 border-t border-border bg-card/50 backdrop-blur-sm px-4 py-3">
          <div className="w-full max-w-2xl md:max-w-3xl lg:max-w-4xl xl:max-w-5xl mx-auto">
            {/* Attachment chips */}
            {attachedFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {attachedFiles.map((file) => (
                  <Badge
                    key={file.id}
                    variant="secondary"
                    className="flex items-center gap-1 pl-2 pr-1 py-1"
                  >
                    <Paperclip className="h-3 w-3" />
                    <span className="text-xs max-w-[120px] truncate">{file.name}</span>
                    <button
                      onClick={() => removeFile(file.id)}
                      className="ml-1 rounded-full hover:bg-muted p-0.5"
                      aria-label={`Remove ${file.name}`}
                    >
                      <XIcon className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
                <button
                  onClick={clearAttachments}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Clear all
                </button>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              onChange={(e) => {
                const fileList = e.target.files;
                if (fileList) {
                  Array.from(fileList).forEach((f) => addFile(f));
                }
                e.target.value = '';
              }}
            />
            <InputArea
              value={input}
              onChange={setInput}
              onSend={handleSend}
              onAttach={() => fileInputRef.current?.click()}
              isLoading={isStreaming || isLoading}
            />
          </div>
        </div>
      </div>

      {/* Right research panel */}
      <div className={cn(
        'border-l border-border bg-card/50 backdrop-blur-sm flex flex-col min-h-0 transition-all duration-300 overflow-hidden',
        isResearchPanelOpen ? 'w-80' : 'w-0'
      )}>
        {isResearchPanelOpen && (
          <>
            <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-primary" />
                <span className="font-semibold text-sm">Repos</span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setIsResearchPanelOpen(false)}
              >
                <XIcon className="h-4 w-4" />
              </Button>
            </div>
            <ScrollArea className="flex-1 min-h-0">
              <ResearchControls
                repositories={repositories.map((r) => ({
                  id: r.id,
                  name: r.git_url.split('/').pop() || r.id,
                  status: r.status,
                }))}
              />
            </ScrollArea>
          </>
        )}
      </div>

      {/* Plan name prompt dialog */}
      <PlanNameDialog
        open={planNameDialogOpen}
        onSubmit={startPlanWithName}
        onCancel={cancelPlanNameDialog}
      />
    </div>
  );
}

function PlanNameDialog({
  open,
  onSubmit,
  onCancel,
}: {
  open: boolean;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');

  const handleSubmit = () => {
    const trimmed = name.trim();
    if (trimmed) {
      onSubmit(trimmed);
      setName('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSubmit();
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Name Your Plan</DialogTitle>
          <DialogDescription>
            Give your plan workflow a descriptive name so you can find it later.
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          placeholder="e.g. User Auth Refactor"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={!name.trim()}>Start Plan</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChatPageInner() {
  const { getContextFiles } = useAttachments();
  return (
    <ChatProvider getAttachmentFiles={getContextFiles}>
      <ChatPageContent />
    </ChatProvider>
  );
}

export default function ChatPage() {
  return (
    <AttachmentProvider>
      <ChatPageInner />
    </AttachmentProvider>
  );
}
