'use client';

import { Button } from '@/components/ui/button';
import { AlertCircle } from 'lucide-react';

interface CascadeWarningBannerProps {
    affectedPhases: string[];
    onConfirm: () => void;
    onCancel: () => void;
}

export function CascadeWarningBanner({ affectedPhases, onConfirm, onCancel }: CascadeWarningBannerProps) {
    return (
        <div className="border-b border-border bg-yellow-50 dark:bg-yellow-900/10 px-6 py-3">
            <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-yellow-600 dark:text-yellow-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                    <p className="text-sm text-yellow-800 dark:text-yellow-200 font-medium">
                        Navigation Warning
                    </p>
                    <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-0.5">
                        Going back will reset the following phases:{' '}
                        <span className="font-medium">
                            {affectedPhases.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(', ')}
                        </span>
                    </p>
                    <p className="text-xs text-yellow-600 dark:text-yellow-400 mt-1">
                        This will discard progress in {affectedPhases.length} phase(s).
                    </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                    <Button variant="outline" size="sm" onClick={onCancel}>
                        Cancel
                    </Button>
                    <Button
                        size="sm"
                        variant="destructive"
                        onClick={onConfirm}
                    >
                        Confirm
                    </Button>
                </div>
            </div>
        </div>
    );
}

export default CascadeWarningBanner;
