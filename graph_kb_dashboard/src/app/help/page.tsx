'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Terminal, Bot, MessageSquare, GitBranch, FileText, Search, Settings, Network, BookOpen, ClipboardList, Sparkles, Zap, Code, Database, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface ExpandableSectionProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

function ExpandableSection({ title, icon, children, defaultOpen = false }: ExpandableSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <Card className="mb-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full text-left"
      >
        <CardHeader className="hover:bg-muted/50 transition-colors">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-3 text-lg">
              {icon}
              {title}
            </CardTitle>
            {isOpen ? (
              <ChevronDown className="h-5 w-5 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-5 w-5 text-muted-foreground" />
            )}
          </div>
        </CardHeader>
      </button>
      {isOpen && <CardContent className="pt-0">{children}</CardContent>}
    </Card>
  );
}

interface CommandItemProps {
  command: string;
  description: string;
  example?: string;
  params?: string[];
}

function CommandItem({ command, description, example, params }: CommandItemProps) {
  return (
    <div className="py-3 border-b border-border last:border-0">
      <div className="flex items-start gap-3">
        <code className="px-2 py-1 bg-primary/10 text-primary rounded text-sm font-mono shrink-0">
          {command}
        </code>
        <div className="flex-1">
          <p className="text-sm text-foreground">{description}</p>
          {params && params.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {params.map((param) => (
                <Badge key={param} variant="outline" className="text-xs">
                  {param}
                </Badge>
              ))}
            </div>
          )}
          {example && (
            <p className="mt-2 text-xs text-muted-foreground font-mono bg-muted/50 px-2 py-1 rounded">
              Example: {example}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

interface AgentItemProps {
  name: string;
  aliases: string[];
  description: string;
  tasks: string[];
}

function AgentItem({ name, aliases, description, tasks }: AgentItemProps) {
  return (
    <div className="py-3 border-b border-border last:border-0">
      <div className="flex items-start gap-3">
        <div className="flex items-center gap-2 shrink-0">
          <Bot className="h-4 w-4 text-purple-500" />
          <code className="px-2 py-1 bg-purple-500/10 text-purple-500 rounded text-sm font-mono">
            @{aliases[0]}
          </code>
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium">{name}</p>
          <p className="text-sm text-muted-foreground mt-1">{description}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {tasks.map((task) => (
              <Badge key={task} variant="secondary" className="text-xs">
                {task}
              </Badge>
            ))}
          </div>
          {aliases.length > 1 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Aliases: {aliases.map((a) => `@${a}`).join(', ')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function HelpPage() {
  return (
    <div className="min-h-screen bg-background p-8 ml-16 lg:ml-64">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Sparkles className="h-8 w-8 text-primary" />
            GraphKB Help
          </h1>
          <p className="text-muted-foreground mt-2">
            Comprehensive guide to using GraphKB's features, commands, and agents.
          </p>
        </div>

        {/* Quick Start */}
        <ExpandableSection
          title="Quick Start"
          icon={<Zap className="h-5 w-5 text-yellow-500" />}
          defaultOpen
        >
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Get started with GraphKB in minutes:
            </p>
            <ol className="list-decimal list-inside space-y-3 text-sm">
              <li>
                <strong>Ingest a Repository:</strong> Go to Repositories and add a GitHub URL, or use{' '}
                <code className="px-1 bg-muted rounded">/ingest https://github.com/owner/repo</code>
              </li>
              <li>
                <strong>Ask Questions:</strong> Use the Chat page to ask questions about your code
              </li>
              <li>
                <strong>Generate Specs:</strong> Use <code className="px-1 bg-muted rounded">@spec</code> or{' '}
                <code className="px-1 bg-muted rounded">/spec</code> to create feature specifications
              </li>
              <li>
                <strong>Search Code:</strong> Use the Search page to find specific code patterns
              </li>
            </ol>
          </div>
        </ExpandableSection>

        {/* Slash Commands */}
        <ExpandableSection title="Slash Commands" icon={<Terminal className="h-5 w-5 text-green-500" />}>
          <div className="divide-y divide-border">
            <CommandItem
              command="/ingest"
              description="Ingest a GitHub repository into the knowledge base"
              example="/ingest https://github.com/owner/repo main"
              params={['url', 'branch']}
            />
            <CommandItem
              command="/ingest --resume"
              description="Resume an interrupted or paused ingestion"
              example="/ingest --resume my-repo"
              params={['repo_id']}
            />
            <CommandItem
              command="/ask-code"
              description="Ask a question about code in a repository"
              example="/ask-code How does authentication work?"
              params={['repo_id', 'question']}
            />
            <CommandItem
              command="/spec"
              description="Generate a feature specification with wizard guidance"
              example="/spec Create a user authentication system"
              params={['query', 'repo_id', 'template']}
            />
            <CommandItem
              command="/diff"
              description="Check for updates/changes in a repository"
              example="/diff owner/repo"
              params={['url']}
            />
            <CommandItem
              command="/list_repos"
              description="List all ingested repositories"
            />
            <CommandItem
              command="/status"
              description="Check ingestion or indexing status"
              params={['repo_id']}
            />
            <CommandItem
              command="/docs"
              description="List or browse documents"
              params={['parent', 'category']}
            />
            <CommandItem
              command="/steering"
              description="Manage steering/guideline documents"
              params={['add', 'list', 'remove']}
            />
            <CommandItem
              command="/agents"
              description="List available agents and their capabilities"
            />
            <CommandItem
              command="/help"
              description="Show this help information"
            />
            <CommandItem
              command="/clear"
              description="Clear the chat history"
            />
          </div>
        </ExpandableSection>

        {/* Agents */}
        <ExpandableSection title="Agents" icon={<Bot className="h-5 w-5 text-purple-500" />}>
          <p className="text-sm text-muted-foreground mb-4">
            Mention agents with <code className="px-1 bg-muted rounded">@agent_name</code> to route queries to specialized handlers.
          </p>
          <div className="divide-y divide-border">
            <AgentItem
              name="Code Analyst"
              aliases={['analyst', 'analyzer']}
              description="Analyzes code structure, patterns, and provides insights"
              tasks={['code analysis', 'pattern detection', 'architecture review']}
            />
            <AgentItem
              name="Architect"
              aliases={['architect', 'arch']}
              description="Designs system architecture and technical specifications"
              tasks={['system design', 'architecture planning', 'technical specs']}
            />
            <AgentItem
              name="Code Generator"
              aliases={['generator', 'gen']}
              description="Generates code based on specifications and requirements"
              tasks={['code generation', 'boilerplate creation', 'implementation']}
            />
            <AgentItem
              name="Researcher"
              aliases={['researcher', 'research']}
              description="Researches topics and gathers information"
              tasks={['research', 'information gathering', 'documentation lookup']}
            />
            <AgentItem
              name="Reviewer/Critic"
              aliases={['reviewer', 'critic']}
              description="Reviews code and provides feedback"
              tasks={['code review', 'quality assessment', 'feedback']}
            />
            <AgentItem
              name="Tool Planner"
              aliases={['planner', 'tools']}
              description="Plans tool usage and execution strategies"
              tasks={['tool planning', 'execution strategy', 'workflow design']}
            />
            <AgentItem
              name="Consistency Checker"
              aliases={['consistency', 'checker']}
              description="Checks for consistency across codebase and specifications"
              tasks={['consistency checking', 'validation', 'quality assurance']}
            />
            <AgentItem
              name="Lead Engineer"
              aliases={['lead', 'engineer']}
              description="Provides engineering leadership and technical guidance"
              tasks={['technical leadership', 'design decisions', 'best practices']}
            />
            <AgentItem
              name="Doc Extractor"
              aliases={['doc', 'docs', 'extractor']}
              description="Extracts and processes documentation"
              tasks={['documentation extraction', 'content parsing', 'metadata extraction']}
            />
            <AgentItem
              name="Feature Spec"
              aliases={['spec', 'featurespec', 'specgen', 'specification']}
              description="Generates comprehensive feature specifications"
              tasks={['specification generation', 'requirement analysis', 'wizard guidance']}
            />
          </div>
        </ExpandableSection>

        {/* Natural Language Intents */}
        <ExpandableSection
          title="Natural Language Intents"
          icon={<MessageSquare className="h-5 w-5 text-blue-500" />}
        >
          <p className="text-sm text-muted-foreground mb-4">
            GraphKB understands natural language commands. Just type what you want to do:
          </p>
          <div className="grid gap-3">
            <div className="p-3 bg-muted/50 rounded-lg">
              <p className="text-sm font-medium">Repository Management</p>
              <p className="text-xs text-muted-foreground mt-1">
                "Add the repo https://github.com/owner/repo" • "Resume ingestion for my-repo" •
                "List all repositories" • "Check status of my-repo"
              </p>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <p className="text-sm font-medium">Code Questions</p>
              <p className="text-xs text-muted-foreground mt-1">
                "How does authentication work?" • "Explain the database schema" •
                "What design patterns are used?"
              </p>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <p className="text-sm font-medium">Documentation</p>
              <p className="text-xs text-muted-foreground mt-1">
                "Generate API documentation" • "Create a technical spec for user auth" •
                "Upload a document"
              </p>
            </div>
            <div className="p-3 bg-muted/50 rounded-lg">
              <p className="text-sm font-medium">Agent Queries</p>
              <p className="text-xs text-muted-foreground mt-1">
                "@architect design a caching system" • "@analyst review this code" •
                "@spec create a feature spec for payments"
              </p>
            </div>
          </div>
        </ExpandableSection>

        {/* Navigation Pages */}
        <ExpandableSection title="Navigation & Pages" icon={<Network className="h-5 w-5 text-cyan-500" />}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <GitBranch className="h-5 w-5 text-green-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Repositories</p>
                <p className="text-xs text-muted-foreground">Manage and ingest GitHub repositories</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <MessageSquare className="h-5 w-5 text-blue-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Chat</p>
                <p className="text-xs text-muted-foreground">Interactive chat with code context</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <Search className="h-5 w-5 text-yellow-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Search</p>
                <p className="text-xs text-muted-foreground">Search code and documentation</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <FileText className="h-5 w-5 text-orange-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Documents</p>
                <p className="text-xs text-muted-foreground">Upload and manage documents</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <ClipboardList className="h-5 w-5 text-purple-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Feature Spec</p>
                <p className="text-xs text-muted-foreground">Generate feature specifications</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <Network className="h-5 w-5 text-cyan-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Visualize</p>
                <p className="text-xs text-muted-foreground">Graph visualization of code relationships</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <BookOpen className="h-5 w-5 text-teal-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Steering</p>
                <p className="text-xs text-muted-foreground">Manage steering/guideline documents</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <Settings className="h-5 w-5 text-gray-500 shrink-0" />
              <div>
                <p className="font-medium text-sm">Settings</p>
                <p className="text-xs text-muted-foreground">Configure application settings</p>
              </div>
            </div>
          </div>
        </ExpandableSection>

        {/* Steering Documents */}
        <ExpandableSection title="Steering Documents" icon={<BookOpen className="h-5 w-5 text-teal-500" />}>
          <div className="space-y-4">
            <div className="p-4 bg-teal-500/10 border border-teal-500/20 rounded-lg">
              <p className="text-sm font-medium text-teal-700 dark:text-teal-300">What are Steering Documents?</p>
              <p className="text-sm text-muted-foreground mt-2">
                Steering documents are project-specific guidelines and conventions that influence how agents behave
                and generate content. They provide context about your project&apos;s standards, patterns, and preferences.
              </p>
            </div>

            <div className="space-y-3">
              <p className="text-sm font-medium">Purpose:</p>
              <ul className="list-disc list-inside space-y-2 text-sm text-muted-foreground">
                <li><strong>Code Style:</strong> Define coding conventions, naming patterns, and formatting rules</li>
                <li><strong>Architecture:</strong> Document architectural decisions and preferred patterns</li>
                <li><strong>Domain Knowledge:</strong> Provide business context and domain-specific terminology</li>
                <li><strong>Agent Behavior:</strong> Customize how agents analyze and generate content for your project</li>
                <li><strong>Specification Templates:</strong> Define templates for feature specs and documentation</li>
              </ul>
            </div>

            <div className="space-y-3">
              <p className="text-sm font-medium">Example Steering Documents:</p>
              <div className="grid gap-2">
                <div className="p-3 bg-muted/50 rounded text-xs font-mono">
                  <span className="text-teal-500">architecture.md</span>
                  <span className="text-muted-foreground"> — Microservices architecture, REST API conventions</span>
                </div>
                <div className="p-3 bg-muted/50 rounded text-xs font-mono">
                  <span className="text-teal-500">coding-standards.md</span>
                  <span className="text-muted-foreground"> — TypeScript strict mode, async/await patterns</span>
                </div>
                <div className="p-3 bg-muted/50 rounded text-xs font-mono">
                  <span className="text-teal-500">domain-glossary.md</span>
                  <span className="text-muted-foreground"> — Business terms, entity definitions</span>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">
                Add steering documents before running feature specs or asking agents for best results.
                They&apos;ll incorporate your conventions into their analysis and output.
              </p>
            </div>
          </div>
        </ExpandableSection>

        {/* Underlying Tools */}
        <ExpandableSection title="Underlying Tools & Technologies" icon={<Code className="h-5 w-5 text-red-500" />}>
          <div className="space-y-4">
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Database className="h-4 w-4 text-blue-500" />
                <p className="font-medium text-sm">Neo4j Graph Database</p>
              </div>
              <p className="text-xs text-muted-foreground">
                Stores code entities, relationships, and dependencies as a connected graph for powerful traversal queries.
              </p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Search className="h-4 w-4 text-green-500" />
                <p className="font-medium text-sm">Vector Embeddings (PostgreSQL pgvector)</p>
              </div>
              <p className="text-xs text-muted-foreground">
                Semantic search using vector embeddings for finding conceptually similar code and documentation.
              </p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <RefreshCw className="h-4 w-4 text-purple-500" />
                <p className="font-medium text-sm">LangGraph Workflows</p>
              </div>
              <p className="text-xs text-muted-foreground">
                Multi-agent orchestration using LangGraph for complex reasoning tasks with human-in-the-loop support.
              </p>
            </div>
            <div className="p-4 bg-muted/50 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <Bot className="h-4 w-4 text-orange-500" />
                <p className="font-medium text-sm">LLM Integration</p>
              </div>
              <p className="text-xs text-muted-foreground">
                Configurable LLM backend supporting OpenAI, Anthropic, and local models for code understanding and generation.
              </p>
            </div>
          </div>
        </ExpandableSection>

        {/* Keyboard Shortcuts */}
        <ExpandableSection title="Tips & Best Practices" icon={<Sparkles className="h-5 w-5 text-yellow-500" />}>
          <div className="space-y-3">
            <div className="flex items-start gap-3">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">Use <code className="px-1 bg-muted rounded">@agent</code> mentions for specific tasks to get more targeted responses</p>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">For large repositories, ingestion may take time. Use <code className="px-1 bg-muted rounded">/ingest --resume</code> if interrupted</p>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">Add steering documents to customize agent behavior for your project's conventions</p>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">Use the Feature Spec wizard for comprehensive requirement gathering before implementation</p>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Tip</Badge>
              <p className="text-sm">The Graph Visualization shows code relationships - useful for understanding architecture</p>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Pro</Badge>
              <p className="text-sm">
                <strong>Query Routing:</strong> GraphKB intelligently routes your questions based on complexity:
              </p>
              <div className="mt-2 ml-8 text-xs text-muted-foreground space-y-1">
                <p><code className="px-1 bg-muted rounded">Simple questions</code> (e.g., &quot;What does X do?&quot;) use fast retrieval</p>
                <p><code className="px-1 bg-muted rounded">Complex questions</code> (e.g., &quot;Trace the auth flow&quot;) use deep analysis with iterative reasoning and tool calls</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Badge variant="outline">Pro</Badge>
              <p className="text-sm">
                <strong>Intent Badges:</strong> Look for colored badges at the top of responses to see how your query was classified:
              </p>
              <div className="mt-2 ml-8 text-xs text-muted-foreground space-y-1">
                <p><span className="inline-flex items-center gap-1 text-amber-400"><span className="text-base">⚡</span> Quick Query</span> — Fast code lookup and simple questions</p>
                <p><span className="inline-flex items-center gap-1 text-purple-400"><span className="text-base">🧠</span> Deep Analysis</span> — Complex reasoning with multi-step investigation</p>
                <p><span className="inline-flex items-center gap-1 text-emerald-400"><span className="text-base">🌿</span> Repository Ingest</span> — Codebase indexing operations</p>
                <p><span className="inline-flex items-center gap-1 text-violet-400"><span className="text-base">📄</span> Feature Spec</span> — Specification generation workflow</p>
              </div>
            </div>
          </div>
        </ExpandableSection>
      </div>
    </div>
  );
}
