'use client';

import { Card } from '@/components/ui/card';
import { Inbox } from 'lucide-react';

/**
 * Empty state displayed when no research results exist yet.
 */
export function ResearchResultsEmptyState() {
  return (
    <Card className="p-8">
      <div className="text-center text-muted-foreground">
        <Inbox className="h-12 w-12 mx-auto mb-3 opacity-50" />
        <p className="font-medium">No Results Yet</p>
        <p className="text-sm mt-1">
          Configure your research sources and click &quot;Start Research&quot; to begin gathering context.
        </p>
      </div>
    </Card>
  );
}
