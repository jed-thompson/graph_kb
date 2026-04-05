'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { ResearchRisk } from '@/lib/types/research';

interface RiskCardProps {
  risk: ResearchRisk;
}

/**
 * Displays a single research risk with severity, description, and mitigation.
 */
export function RiskCard({ risk }: RiskCardProps) {
  const severityVariant = getSeverityVariant(risk.severity);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <Badge variant={severityVariant}>{risk.severity}</Badge>
          <p className="font-medium">{risk.description}</p>
        </div>
        <Badge variant="outline">{risk.category}</Badge>
      </div>
      {risk.mitigation && <RiskMitigation mitigation={risk.mitigation} />}
    </Card>
  );
}

function getSeverityVariant(severity: string): 'destructive' | 'default' | 'secondary' {
  switch (severity) {
    case 'critical':
      return 'destructive';
    case 'high':
      return 'default';
    default:
      return 'secondary';
  }
}

interface RiskMitigationProps {
  mitigation: string;
}

function RiskMitigation({ mitigation }: RiskMitigationProps) {
  return (
    <div className="mt-3 pt-3 border-t">
      <p className="text-sm text-muted-foreground">
        <span className="font-medium">Mitigation:</span> {mitigation}
      </p>
    </div>
  );
}
