'use client';

import { useResearchStore } from '@/lib/store/researchStore';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AlertTriangle, Link2, Network, Shield } from 'lucide-react';

const SEVERITY_VARIANT = {
  low: 'secondary',
  medium: 'default',
  high: 'destructive',
  critical: 'destructive',
} as const;

export function CrossRepoSynthesisPanel() {
  const { crossRepoSynthesis } = useResearchStore();

  if (!crossRepoSynthesis) return null;

  const { summary, apiContractGaps, crossCuttingRisks, dependencyIssues } = crossRepoSynthesis;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Network className="h-5 w-5 text-primary" />
        <h3 className="text-base font-semibold">Cross-Repository Synthesis</h3>
      </div>

      {summary && (
        <p className="text-sm text-muted-foreground">{summary}</p>
      )}

      <Tabs defaultValue="gaps">
        <TabsList className="grid grid-cols-4 w-full">
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="gaps">
            API Gaps {apiContractGaps.length > 0 && `(${apiContractGaps.length})`}
          </TabsTrigger>
          <TabsTrigger value="risks">
            Risks {crossCuttingRisks.length > 0 && `(${crossCuttingRisks.length})`}
          </TabsTrigger>
          <TabsTrigger value="deps">
            Deps {dependencyIssues.length > 0 && `(${dependencyIssues.length})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="mt-3">
          <p className="text-sm">{summary || 'No summary available.'}</p>
        </TabsContent>

        <TabsContent value="gaps" className="mt-3 space-y-2">
          {apiContractGaps.length === 0 ? (
            <p className="text-sm text-muted-foreground">No API contract gaps detected.</p>
          ) : (
            apiContractGaps.map((gap) => (
              <Card key={gap.id} className="p-3 space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <Link2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="text-sm font-medium">{gap.sourceRepo}</span>
                  <span className="text-xs text-muted-foreground">→</span>
                  <span className="text-sm font-medium">{gap.targetRepo}</span>
                  <Badge variant="outline" className="text-xs">{gap.interfaceType?.toUpperCase()}</Badge>
                  <Badge variant={SEVERITY_VARIANT[gap.severity as keyof typeof SEVERITY_VARIANT] ?? 'secondary'} className="text-xs">
                    {gap.severity}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{gap.description}</p>
                {gap.mitigation && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium">Mitigation:</span> {gap.mitigation}
                  </p>
                )}
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="risks" className="mt-3 space-y-2">
          {crossCuttingRisks.length === 0 ? (
            <p className="text-sm text-muted-foreground">No cross-cutting risks detected.</p>
          ) : (
            crossCuttingRisks.map((risk) => (
              <Card key={risk.id} className="p-3 space-y-1.5">
                <div className="flex items-center gap-2">
                  <Shield className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-sm font-medium">{risk.category}</span>
                  <Badge variant={SEVERITY_VARIANT[risk.severity as keyof typeof SEVERITY_VARIANT] ?? 'secondary'} className="text-xs">
                    {risk.severity}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{risk.description}</p>
                {risk.mitigation && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium">Mitigation:</span> {risk.mitigation}
                  </p>
                )}
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="deps" className="mt-3 space-y-2">
          {dependencyIssues.length === 0 ? (
            <p className="text-sm text-muted-foreground">No dependency issues detected.</p>
          ) : (
            dependencyIssues.map((issue) => (
              <Card key={issue.id} className="p-3 space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <AlertTriangle className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="text-sm font-medium">{issue.upstreamRepo}</span>
                  <span className="text-xs text-muted-foreground">→</span>
                  <span className="text-sm font-medium">{issue.downstreamRepo}</span>
                  <Badge variant={SEVERITY_VARIANT[issue.severity as keyof typeof SEVERITY_VARIANT] ?? 'secondary'} className="text-xs">
                    {issue.severity}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{issue.description}</p>
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
